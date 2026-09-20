"""The mnd.io attribute proxy (MANEDPY_PLAN.md §4).

__getattr__ rules: reject names starting with "_" immediately (the classic
proxy bug — protects __deepcopy__, IPython's _ipython_canary_*, etc.); search
$MANEDPATH -> mnd.search_path -> CWD -> ./mnd/; a miss raises
ManedScriptNotFound naming every directory searched; __dir__ globs *.mnd so
tab-completion works.
"""

from .errors import ManedScriptNotFound


class IoProxy:
    def __init__(self, facade):
        object.__setattr__(self, "_facade", facade)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise ManedScriptNotFound(
            "manedpy is a scaffold: libmaned_c does not exist yet "
            "(MANEDPY_PLAN.md Phases 0-2b)"
        )

    def __dir__(self):
        return []
