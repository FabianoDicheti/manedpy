"""Result(dict) — the /run.json document, plus accessors (MANEDPY_PLAN.md §4).

A dict subclass: result["outputs"]["a"] and json.dumps(result) both work. The
dict IS the contract; the accessors are sugar.
"""


class Result(dict):
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

    # .raw (original bytes) and .status are attached by Script.run.
