"""The mnd.io attribute proxy (MANEDPY_PLAN.md §4).

__getattr__ rules: reject names starting with "_" immediately (the classic
proxy bug — protects __deepcopy__, IPython's _ipython_canary_*, etc.); search
$MANEDPATH -> mnd.search_path -> CWD -> ./mnd/; a miss raises
ManedScriptNotFound naming every directory searched; __dir__ globs *.mnd so
tab-completion works.
"""

import glob
import os

from .errors import ManedScriptNotFound

MANEDPATH = "MANEDPATH"


class IoProxy:
    """`mnd.io.scoring(payload)` == `mnd.load(<found>/scoring.mnd).run(payload)`.

    A hit returns the Script, which is callable, so the sugar is one attribute
    lookup and nothing else.
    """

    def __init__(self, facade):
        object.__setattr__(self, "_facade", facade)

    def __getattr__(self, name):
        # Underscore names are rejected before any filesystem work. Skipping
        # this is the classic proxy bug: copy.deepcopy, pickle and IPython all
        # probe dunders on unknown objects and get baffling failures back.
        if name.startswith("_"):
            raise AttributeError(name)
        facade = object.__getattribute__(self, "_facade")
        directories = search_directories(facade)
        for directory in directories:
            candidate = os.path.join(directory, name + ".mnd")
            if os.path.isfile(candidate):
                return facade.load(candidate)
        raise ManedScriptNotFound(
            "no %s.mnd on the maned search path; searched, in order: %s. "
            "Set $%s, append to maned.search_path, or call maned.load() with "
            "an explicit path."
            % (name, ", ".join(directories) or "(nothing)", MANEDPATH)
        )

    def __setattr__(self, name, value):
        raise AttributeError(
            "mnd.io is a read-only view of the search path; use "
            "maned.search_path to change where scripts are found"
        )

    def __dir__(self):
        names = set()
        for directory in search_directories(object.__getattribute__(self, "_facade")):
            for path in glob.glob(os.path.join(directory, "*.mnd")):
                stem = os.path.basename(path)[: -len(".mnd")]
                if stem and not stem.startswith("_") and stem.isidentifier():
                    names.add(stem)
        return sorted(names)

    def __repr__(self):
        return "<manedpy mnd.io search_path=%s>" % (
            search_directories(object.__getattribute__(self, "_facade")),
        )


def search_directories(facade):
    """$MANEDPATH -> maned.search_path -> CWD -> ./mnd/, deduplicated.

    Order is the contract, and the refusal message quotes this list verbatim:
    this repo's house style is refusal-by-name ("the refusal message is the
    API contract").
    """
    directories = []
    for entry in os.environ.get(MANEDPATH, "").split(os.pathsep):
        if entry:
            directories.append(entry)
    directories.extend(os.fspath(p) for p in getattr(facade, "search_path", []))
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = None
    if cwd:
        directories.append(cwd)
        directories.append(os.path.join(cwd, "mnd"))
    seen = set()
    ordered = []
    for directory in directories:
        absolute = os.path.abspath(directory)
        if absolute not in seen:
            seen.add(absolute)
            ordered.append(absolute)
    return ordered
