# manedpy

Call `.mnd` scripts from Python, in-process — the JSON document `/run.json` returns,
minus the socket.

```python
from manedpy import maned as mnd

payload = {"x": [[2, 0], [0, 2]], "w": [[3, 4], [5, 6]]}
result = mnd.io.scoring(payload)
```

**Status: scaffold only. Nothing here is functional.** This repo tracks
`MANEDPY_PLAN.md` in the maned workspace; the binding is blocked on the maned_lang side
of that plan (Phase 0 C++ edits, the `mnd_*` C ABI, and the `libmaned_c` shared library —
Phases 0–2b), none of which exist yet. Files in `manedpy/` are stubs that raise
`NotImplementedError` and exist to fix the public API surface early.

## Licensing — read this before packaging

The Python source in this repo is **Apache-2.0**. A built *wheel* is **mixed-licence**:
it bundles `libmaned_c`, a proprietary-but-redistributable binary covered by section 3 of
the maned `LICENSE` (shipped beside it as `LICENSE-libmaned_c`). `pyproject.toml` must
use `license-files` listing both — never a bare Apache SPDX expression, which would
misdescribe the wheel.

## Known limits (by design, v1)

- **Calls cannot be interrupted.** Ctrl-C in a REPL and "interrupt kernel" in Jupyter do
  nothing until the native call returns. Use `multiprocessing` with `spawn` for work long
  enough to want to cancel.
- **Relative data paths in `.mnd` files resolve against the process CWD**, not the
  script's directory. Prefer absolute paths in scripts.
- **Windows is a non-goal.** The serve and net layers are POSIX throughout.
- `set_kernel_threads` is process-global; it changes timing, not values.
