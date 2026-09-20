"""manedpy — call .mnd scripts from Python, in-process.

Scaffold per MANEDPY_PLAN.md §4. Blocked on the maned_lang C ABI and shared
library (MANEDPY_PLAN.md Phases 0-2b): libmaned_c does not exist yet, so every
entry point raises NotImplementedError.

`maned` is a singleton facade object, not the module itself: `mnd.load`,
`mnd.io`, `mnd.set_kernel_threads` and `mnd.search_path` all live on it.
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
from ._facade import maned

__all__ = [
    "maned",
    "ManedError",
    "ManedLoadError",
    "ManedInputError",
    "ManedRouteError",
    "ManedRuntimeError",
    "ManedUnsupportedError",
    "ManedInternalError",
    "ManedScriptNotFound",
]
