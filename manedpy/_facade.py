"""The `maned` singleton facade (MANEDPY_PLAN.md §4).

Holds load(), io, set_kernel_threads(), search_path and the script cache keyed
by (realpath, st_mtime_ns, st_size, flags).
"""

import os
import threading

from . import _ffi
from . import _lib
from ._io import IoProxy
from .errors import ManedLoadError
from .script import Script


class _Maned:
    """One object, so `mnd.load`, `mnd.io` and `mnd.set_kernel_threads` sit
    together. Module-level __getattr__ magic would put them on the module and
    be harder to debug."""

    def __init__(self):
        #: Extra directories mnd.io searches, after $MANEDPATH and before CWD.
        self.search_path = []
        self.io = IoProxy(self)
        self._cache = {}
        self._cache_lock = threading.Lock()

    # --- loading ---------------------------------------------------------

    def load(
        self,
        path,
        *,
        concurrent=False,
        reload=False,
        synthesize_outputs=False,
        no_vm_fallback=False,
    ):
        """Parse -> lint -> inline -> plan -> validate once; return a Script.

        `concurrent=True` drops the per-Script lock and is refused at load
        time unless the script is non-routed: a routed script drives
        single-connection device channels, and the library checking that beats
        the user reading a table.

        `synthesize_outputs` makes a return-only script servable;
        `no_vm_fallback` turns an unreachable device into a hard error.
        Caching is keyed on the flags too, so the same path under two flag
        sets is two handles.
        """
        dll = _lib.load_library()
        flags = 0
        if synthesize_outputs:
            flags |= _ffi.MND_SYNTHESIZE_OUTPUTS
        if no_vm_fallback:
            flags |= _ffi.MND_NO_VM_FALLBACK

        key = self._cache_key(path, flags, concurrent)
        if not reload:
            with self._cache_lock:
                cached = self._cache.get(key)
            if cached is not None and not cached.closed:
                return cached

        handle, load_notes = _ffi.open_script(dll, os.fspath(path), flags)
        if concurrent and dll.mnd_script_is_routed(handle):
            _ffi.close_script(dll, handle)
            raise ManedLoadError(
                "%s: concurrent=True is refused for a routed script — "
                "@device / host=\"local\" flows drive single-connection "
                "channels that are not thread-safe. Open a second Script for "
                "parallelism, or drop concurrent=True to take the default "
                "per-Script lock." % path,
                script=str(path),
            )

        script = Script(
            dll,
            handle,
            os.fspath(path),
            flags,
            concurrent,
            load_notes,
            owner=self,
        )
        script._cache_key = key
        with self._cache_lock:
            previous = self._cache.get(key)
            self._cache[key] = script
        if previous is not None and previous is not script:
            previous.close()
        return script

    def clear_cache(self):
        """Close and forget every cached Script."""
        with self._cache_lock:
            scripts = list(self._cache.values())
            self._cache.clear()
        for script in scripts:
            script.close()

    def _cache_key(self, path, flags, concurrent):
        """(realpath, st_mtime_ns, st_size, flags).

        mtime is in the key on purpose: editing a .mnd and re-running in the
        same REPL must pick the change up, which is what a notebook user
        expects and what they will otherwise file a bug about. A path that
        does not exist yet still gets a key — mnd_open will produce the real
        refusal, which is better worded than anything stat() could say.
        """
        real = os.path.realpath(os.fspath(path))
        try:
            info = os.stat(real)
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = (None, None)
        return (real, stamp[0], stamp[1], flags, bool(concurrent))

    def _forget(self, script):
        """Script.close() calls this so a closed Script never gets handed out."""
        key = getattr(script, "_cache_key", None)
        if key is None:
            return
        with self._cache_lock:
            if self._cache.get(key) is script:
                del self._cache[key]

    # --- process-global knobs -------------------------------------------

    def set_kernel_threads(self, n):
        """Interpreter worker-thread count — PROCESS-GLOBAL.

        Deliberately module level and never a Script kwarg, so nobody writes
        mnd.load(x, threads=4) and expects isolation. It changes timing,
        never values.
        """
        dll = _lib.load_library()
        dll.mnd_set_kernel_threads(int(n))

    # --- introspection ---------------------------------------------------

    @property
    def lib_path(self):
        """The absolute path of the loaded libmaned_c (None before first use)."""
        return _lib.lib_path()

    @property
    def lib_version(self):
        """mnd_version() of the loaded library (None before first use)."""
        return _lib.lib_version()

    def __repr__(self):
        return "<manedpy.maned lib=%s>" % (_lib.lib_path() or "not loaded")


maned = _Maned()
