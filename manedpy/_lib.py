"""Library discovery + ctypes.CDLL + ABI checks (MANEDPY_PLAN.md §4).

Honours $MANEDPY_LIB, else loads manedpy/_lib/libmaned_c.<ext> by absolute
path; checks MND_ABI_MIN <= mnd_abi_version() <= MND_ABI_MAX (a range, never an
exact match — an additive bump must not brick every installed manedpy); asserts
sizeof(mnd_response) against maned_c_abi.json; registers the atexit hook that
closes live handles (hazard 4); uses CDLL, never PyDLL (PyDLL holds the GIL
across the call, and a two-second matmul must not block the interpreter).
"""

import atexit
import ctypes
import json
import os
import sys
import threading
import warnings
import weakref

from . import _ffi

#: Accept a RANGE (MANEDPY_PLAN.md §8.3). Adding a route or an MND_* flag
#: never bumps the ABI version; only removing an entry point, changing a
#: signature or changing a struct layout does. Widen MAX when that happens
#: and this file has been taught the new layout.
MND_ABI_MIN = 1
MND_ABI_MAX = 1

#: The maned version this package was built against, stamped by the release
#: job that drops the library into manedpy/_lib/. None in a source checkout,
#: where the library always comes from $MANEDPY_LIB.
BUILT_AGAINST = None

_LIB_ENV = "MANEDPY_LIB"
_BUNDLED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib")

_lock = threading.Lock()
_dll = None
_lib_path = None
_lib_version = None

#: Every open Script, so the atexit hook can close handles the interpreter
#: would otherwise drop on the floor — leaving a bark-vm child holding a pipe
#: (hazard 4). A WeakSet: a garbage-collected Script has already closed itself.
_live = weakref.WeakSet()
_live_lock = threading.Lock()


class ManedLibraryError(RuntimeError):
    """The library could not be found, loaded, or trusted."""


def library_path():
    """$MANEDPY_LIB, else the bundled library. Absolute, always.

    No @rpath / RPATH / LD_LIBRARY_PATH involvement at all: an absolute path
    is the only discovery rule that cannot silently pick up a stale library
    from somewhere else on the machine.
    """
    override = os.environ.get(_LIB_ENV)
    if override:
        path = os.path.abspath(os.path.expanduser(override))
        if not os.path.exists(path):
            raise ManedLibraryError(
                "$%s points at %s, which does not exist" % (_LIB_ENV, path)
            )
        return path
    for name in _bundled_names():
        path = os.path.join(_BUNDLED_DIR, name)
        if os.path.exists(path):
            return path
    raise ManedLibraryError(
        "no libmaned_c found: $%s is unset and none of %s exists in %s. "
        "Point $%s at a libmaned_c from a maned-capi-* tarball."
        % (
            _LIB_ENV,
            ", ".join(_bundled_names()),
            _BUNDLED_DIR,
            _LIB_ENV,
        )
    )


def _bundled_names():
    if sys.platform == "darwin":
        return ("libmaned_c.dylib",)
    if sys.platform.startswith("win"):
        # Windows is an explicit v1 non-goal (hazard 7): the serve and net
        # layers are POSIX throughout. Named only so the error says so.
        return ("maned_c.dll",)
    return ("libmaned_c.so.1", "libmaned_c.so")


def load_library():
    """Load, bind and validate the library exactly once per process."""
    global _dll, _lib_path, _lib_version
    if _dll is not None:
        return _dll
    with _lock:
        if _dll is not None:
            return _dll
        path = library_path()
        try:
            dll = ctypes.CDLL(path)
        except OSError as exc:
            raise ManedLibraryError("cannot load %s: %s" % (path, exc)) from exc
        _ffi.bind(dll)
        _check_abi(dll, path)
        _check_layout(path)
        version = (dll.mnd_version() or b"").decode("utf-8", "replace")
        _warn_on_version_mismatch(version, path)
        _lib_path = path
        _lib_version = version
        _dll = dll
        return _dll


def _check_abi(dll, path):
    version = int(dll.mnd_abi_version())
    if not (MND_ABI_MIN <= version <= MND_ABI_MAX):
        raise ManedLibraryError(
            "%s reports ABI version %d; this manedpy accepts %d..%d. "
            "Either $%s points at a stale library or manedpy needs upgrading."
            % (path, version, MND_ABI_MIN, MND_ABI_MAX, _LIB_ENV)
        )


def _check_layout(path):
    """Assert our mnd_response against the library's own layout manifest.

    ctypes derives its own padding, so manedpy cannot get the layout wrong on
    its own — but it CAN be handed a library built for another architecture
    via $MANEDPY_LIB, and without this nothing would notice until the first
    garbage body_len.
    """
    manifest = _read_abi_manifest(path)
    if manifest is None:
        return
    spec = manifest.get("structs", {}).get("mnd_response")
    if not spec:
        return
    actual_size = ctypes.sizeof(_ffi.MndResponse)
    expected_size = spec.get("sizeof")
    if expected_size is not None and actual_size != expected_size:
        raise ManedLibraryError(
            "mnd_response layout mismatch: %s says sizeof=%d, ctypes derives "
            "%d — the library is probably built for another architecture"
            % (path, expected_size, actual_size)
        )
    for field, expected in (spec.get("fields") or {}).items():
        got = getattr(_ffi.MndResponse, field, None)
        if got is None:
            raise ManedLibraryError(
                "mnd_response has no field %r, but %s declares one" % (field, path)
            )
        if got.offset != expected:
            raise ManedLibraryError(
                "mnd_response.%s at offset %d, but the layout manifest says %d"
                % (field, got.offset, expected)
            )


def _read_abi_manifest(lib_path):
    """maned_c_abi.json as shipped beside the library in the capi tarball."""
    lib_dir = os.path.dirname(lib_path)
    for candidate in (
        os.path.join(lib_dir, "maned_c_abi.json"),
        os.path.join(os.path.dirname(lib_dir), "maned_c_abi.json"),
    ):
        if os.path.exists(candidate):
            try:
                with open(candidate, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError) as exc:
                raise ManedLibraryError(
                    "cannot read the ABI layout manifest %s: %s" % (candidate, exc)
                ) from exc
    return None


def _warn_on_version_mismatch(version, path):
    """A silently swapped library sharing an ABI version is undebuggable."""
    if BUILT_AGAINST and version and version != BUILT_AGAINST:
        warnings.warn(
            "manedpy was built against maned %s but $%s loaded %s (maned %s); "
            "the ABI version matches, so this may still work"
            % (BUILT_AGAINST, _LIB_ENV, path, version),
            RuntimeWarning,
            stacklevel=3,
        )


def lib_path():
    """The absolute path of the loaded library, or None before first load."""
    return _lib_path


def lib_version():
    """mnd_version() of the loaded library, or None before first load."""
    return _lib_version


# --- handle registry: hazard 4 and hazard 5 ------------------------------


def register(script):
    """Track an open Script so the atexit hook can close it."""
    with _live_lock:
        _live.add(script)


def unregister(script):
    with _live_lock:
        _live.discard(script)


def live_count():
    with _live_lock:
        return len(_live)


def _close_all():
    """atexit: SIGKILL-free shutdown of any bark-vm child (hazard 4).

    __del__ is not guaranteed at interpreter shutdown, so close() has to be
    driven from somewhere that is. close() is idempotent, so double-closing a
    Script that already went out of scope is free.
    """
    with _live_lock:
        scripts = list(_live)
    for script in scripts:
        try:
            script.close()
        except Exception:  # never let shutdown raise
            pass


def _after_fork_in_child():
    """os.register_at_fork: a Lock held at fork time deadlocks the child.

    Handles hold no fds between calls (dispatch.h: each flow gets a FRESH
    DeviceSession), so a handle is fork-safe between calls but not during
    one. Replacing the locks is what makes the between-calls case usable;
    `spawn` remains the documented safe pattern.
    """
    global _live_lock, _lock
    _lock = threading.Lock()
    _live_lock = threading.Lock()
    with _live_lock:
        scripts = list(_live)
    for script in scripts:
        reinit = getattr(script, "_reinit_lock", None)
        if reinit is not None:
            reinit()


atexit.register(_close_all)
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)
