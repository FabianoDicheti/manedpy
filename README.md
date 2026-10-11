# manedpy

Call `.mnd` scripts from Python, in-process — the JSON document `/run.json` returns,
minus the socket.

```python
from manedpy import maned as mnd

payload = {"x": [[2, 0], [0, 2]], "w": [[3, 4], [5, 6]]}
result = mnd.io.scoring(payload)
```

`scoring.mnd` must declare `in::x` and `in::w`: a payload key with no matching `in::` is a
400. `mnd.load(path)` is the real API and `mnd.io.<name>` is sugar over it.

A response computed here is **byte-identical** to what `maned-serve` answers over HTTP for
the same script and body — that is a CI fact, not a promise: `tests/test_rest_parity.py`
launches `maned-serve`, POSTs the same bytes, and compares.

## Quickstart

```sh
pip install manedpy
```

The wheel bundles the engine library — nothing else to install (macOS
universal, Linux x86-64/arm64; Python ≥3.9). Then, step by step:

1. Save a script as `scoring.mnd`:

```mnd
mnd::quantmax=30000;
mnd::quantmin=-30000;
mnd::quantres=0;

in::w = [[1,2],[0,1]];

calc::lambda_flow scoring(x, w) {
    w x matmul y =
} return y;

out::y = csv("y.csv");
```

2. Save this as `scoring.py` next to it:

```python
from manedpy import maned as mnd

script = mnd.load("scoring.mnd")
result = script.run({"x": [[2, 0], [0, 2]]})
print("y =", result.outputs["y"])
```

3. Run it:

```sh
$ python scoring.py
y = [[2, 4], [0, 2]]
```

The same pair lives in [`examples/`](examples/), runnable as
`python examples/scoring.py` — alongside three deep dives:
`files.py` (file routes: bytes in, output files back), `decimals.py`
(exact decimals), `routed.py` (the local Bark VM).

## Installing from a source checkout

A wheel bundles `libmaned_c` in `manedpy/_lib/`. In a source checkout that directory is
empty, so point `$MANEDPY_LIB` at a `libmaned_c` from a `maned-capi-*` tarball:

```sh
export MANEDPY_LIB=/path/to/maned-capi-*/lib/libmaned_c.dylib
```

The library is loaded by **absolute path** with `ctypes.CDLL` — no `@rpath`, no `RPATH`, no
`LD_LIBRARY_PATH`. On load, manedpy checks that `mnd_abi_version()` falls in the range it
accepts and asserts its `mnd_response` layout against the `maned_c_abi.json` shipped beside
the library, which is what catches a stale or wrong-architecture `$MANEDPY_LIB`.

## The API

| Python | Route |
|---|---|
| `s.run(payload)` / `s(payload)` | `POST /run.json` → `Result` |
| `s.frame(payload)` | `POST /frame` → `Result` |
| `s.frame_csv(payload)` | `POST /frame.csv` → `bytes` |
| `s.run_files(**named_bytes)` | `POST /run` multipart → `{name: bytes}` — the only way to get real PNG bytes back |
| `s.health()` | `GET /health` → dict |
| `s.inputs` / `s.outputs` / `s.routes` | cached from `/health` |
| `s.request(method, target, content_type, body)` | the raw escape hatch: status, bytes, notes, nothing raised |

`Result` is a `dict` subclass, so `result["outputs"]["a"]` and `json.dumps(result)` both
work, plus `.outputs`, `.profiles`, `.frames`, `.notes`, `.raw` and `.status`.

Errors are a hierarchy under `ManedError`, all carrying `.status`, `.body` and `.script`:
400/413/431 → `ManedInputError` (also a `ValueError`), 404/405 → `ManedRouteError`, 500 →
`ManedRuntimeError` (also a `RuntimeError`), 501 → `ManedUnsupportedError`, a load failure →
`ManedLoadError`, and status `0` → `ManedInternalError`, which means an exception escaped
the engine rather than any HTTP condition.

Scripts are cached on `(realpath, mtime, size, flags)`, so editing a `.mnd` and re-running
in the same REPL picks the change up. `mnd.load(..., reload=True)` and `mnd.clear_cache()`
override that.

### Threading

A `Script` takes a lock per call by default, which makes the routed case correct by
construction. Non-routed scripts are provably safe to call concurrently on one handle, so
`mnd.load(path, concurrent=True)` drops the lock — and is refused at load time if the
script routes to a device.

## Licensing — read this before packaging

The Python source in this repo is **Apache-2.0**. A built *wheel* is **mixed-licence**:
it bundles `libmaned_c`, a proprietary-but-redistributable binary covered by section 3 of
the maned `LICENSE` (shipped beside it as `LICENSE-libmaned_c`). `pyproject.toml` must
use `license-files` listing both — never a bare Apache SPDX expression, which would
misdescribe the wheel.

## Known limits (by design, v1)

- **Calls cannot be interrupted.** `ctypes.CDLL` releases the GIL, which is the point — but
  it also means a `KeyboardInterrupt` is not delivered until the native call returns. Ctrl-C
  in a REPL and "interrupt kernel" in Jupyter do nothing until then. Use `multiprocessing`
  with `spawn` for work long enough to want to cancel.
- **Relative data paths in `.mnd` files resolve against the process CWD**, not the
  script's directory. `maned-serve` behaves the same way; load errors say so. Prefer
  absolute paths in scripts.
- **Windows is a non-goal.** The serve and net layers are POSIX throughout.
- `set_kernel_threads` is process-global; it changes timing, not values.
- `requests_served` is not exposed: in-process it counts calls on one handle, which looks
  like a server metric and is not one.

## Tests

```sh
python3 -m venv .venv && .venv/bin/pip install pytest
MANEDPY_LIB=/path/to/capi/lib/libmaned_c.dylib .venv/bin/python -m pytest
```

The suite walks the conformance corpus shipped in the capi tarball (`<case>.mnd` +
`.request.json` + `.expect.json`, compared byte-for-byte), runs the REST-parity gate against
a `maned-serve` subprocess (`$MANED_SERVE`, or a sibling binary in the workspace), and
diffs `_ffi.SIGNATURES` against `maned_c.h` so the ctypes table cannot drift from the header.
