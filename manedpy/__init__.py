"""manedpy — call .mnd scripts from Python, in-process.

The binding of MANEDPY_PLAN.md §4 over the mnd_* C ABI (maned_c.h): a request
answered in-process is byte-identical to what maned-serve answers over HTTP
for the same script and body, minus the socket.

`maned` is a singleton facade object, not the module itself: `mnd.load`,
`mnd.io`, `mnd.set_kernel_threads` and `mnd.search_path` all live on it.

    from manedpy import maned as mnd

    result = mnd.io.scoring({"x": [[2, 0], [0, 2]], "w": [[3, 4], [5, 6]]})

Calls cannot be interrupted (MANEDPY_PLAN.md hazard 2) — see Script.run.
"""

from .errors import (
    ManedError,
    ManedLoadError,
    ManedInputError,
    ManedRouteError,
    ManedRuntimeError,
    ManedUnsupportedError,
    ManedInternalError,
    ManedScriptNotFound,
)
from ._lib import ManedLibraryError, MND_ABI_MIN, MND_ABI_MAX
from ._facade import maned
from .result import Result
from .script import Script

__version__ = "0.1.0"

#: Convenience aliases — the facade is still the real API.
load = maned.load
clear_cache = maned.clear_cache
set_kernel_threads = maned.set_kernel_threads

__all__ = [
    "maned",
    "load",
    "clear_cache",
    "set_kernel_threads",
    "Script",
    "Result",
    "ManedError",
    "ManedLibraryError",
    "ManedLoadError",
    "ManedInputError",
    "ManedRouteError",
    "ManedRuntimeError",
    "ManedUnsupportedError",
    "ManedInternalError",
    "ManedScriptNotFound",
    "MND_ABI_MIN",
    "MND_ABI_MAX",
    "__lib_version__",
]


def __getattr__(name):
    """`manedpy.__lib_version__` — mnd_version() of the loaded library.

    Lazy, because importing manedpy must not fail on a machine where
    libmaned_c is missing: the refusal belongs at the first load(), where the
    message can say what to do about it.
    """
    if name == "__lib_version__":
        from ._lib import load_library, lib_version

        load_library()
        return lib_version()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
