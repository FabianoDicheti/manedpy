"""Script: per-handle lock, routes, close/__enter__/__del__ (MANEDPY_PLAN.md §4).

Routes: run/__call__ -> POST /run.json; frame -> /frame; frame_csv ->
/frame.csv; run_files -> /run multipart (the only way to get real PNG bytes
back); health -> GET /health; .inputs/.outputs cached from /health.

Default: a per-Script lock (routed scripts are not thread-safe). concurrent=True
is refused at load unless mnd_script_is_routed() == 0.
"""

_BLOCKED = (
    "manedpy is a scaffold: libmaned_c does not exist yet "
    "(MANEDPY_PLAN.md Phases 0-2b)"
)


class Script:
    def __call__(self, payload):
        return self.run(payload)

    def run(self, payload):
        # NOTE for implementers and users: calls are uninterruptible — a
        # KeyboardInterrupt during a long mnd_request is delivered only when
        # the call returns (MANEDPY_PLAN.md hazard 2).
        raise NotImplementedError(_BLOCKED)

    def frame(self, payload):
        raise NotImplementedError(_BLOCKED)

    def frame_csv(self, payload):
        raise NotImplementedError(_BLOCKED)

    def run_files(self, **named_bytes):
        raise NotImplementedError(_BLOCKED)

    def health(self):
        raise NotImplementedError(_BLOCKED)

    def close(self):
        raise NotImplementedError(_BLOCKED)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
