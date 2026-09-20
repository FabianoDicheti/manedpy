"""The `maned` singleton facade (MANEDPY_PLAN.md §4).

Holds load(), io, set_kernel_threads(), search_path and the script cache keyed
by (realpath, st_mtime_ns, st_size, flags).
"""

from ._io import IoProxy

_BLOCKED = (
    "manedpy is a scaffold: libmaned_c does not exist yet "
    "(MANEDPY_PLAN.md Phases 0-2b)"
)


class _Maned:
    def __init__(self):
        self.search_path = []
        self.io = IoProxy(self)

    def load(self, path, *, concurrent=False, reload=False):
        raise NotImplementedError(_BLOCKED)

    def set_kernel_threads(self, n):
        # Process-global (src/interp/parallel.cpp:16) — never a Script kwarg.
        raise NotImplementedError(_BLOCKED)

    def clear_cache(self):
        raise NotImplementedError(_BLOCKED)


maned = _Maned()
