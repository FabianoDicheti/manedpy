"""Result(dict) — the /run.json document, plus accessors (MANEDPY_PLAN.md §4).

A dict subclass: result["outputs"]["a"] and json.dumps(result) both work. The
dict IS the contract; the accessors are sugar.
"""


class Result(dict):
    #: .raw (original response bytes) and .status are attached by Script.run;
    #: declared here so a Result built by hand still answers them.
    raw = b""
    status = None

    @property
    def outputs(self):
        return self.get("outputs", {})

    @property
    def profiles(self):
        return self.get("profiles", {})

    @property
    def frames(self):
        return self.get("frames", {})

    @property
    def notes(self):
        return self.get("notes", [])

    def __repr__(self):
        return "Result(%s)" % dict.__repr__(self)


def build(document, raw, status):
    """The one place a Result is stamped with its response bytes and status."""
    result = Result(document)
    result.raw = raw
    result.status = status
    return result
