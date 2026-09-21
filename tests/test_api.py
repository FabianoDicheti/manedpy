"""The Python surface: refusals, threading, caching, routes, error mapping.

Everything MANEDPY_PLAN.md §4 promises a caller that the conformance corpus
cannot see, because it is about the binding rather than about the engine.
"""

import concurrent.futures
import json
import os
import shutil
import time

import pytest

import manedpy
from manedpy import maned as mnd
from manedpy.errors import (
    ManedInputError,
    ManedInternalError,
    ManedLoadError,
    ManedRouteError,
    ManedRuntimeError,
    ManedScriptNotFound,
    ManedUnsupportedError,
    error_for_status,
)
from manedpy.result import Result
from manedpy.script import decode_multipart, encode_multipart, encode_payload


@pytest.fixture
def matmul(conformance_dir):
    return os.path.join(conformance_dir, "01_local_matmul.mnd")


@pytest.fixture
def frame_script(conformance_dir):
    return os.path.join(conformance_dir, "03_frame_records.mnd")


@pytest.fixture(autouse=True)
def _clean_cache():
    mnd.clear_cache()
    saved = list(mnd.search_path)
    yield
    mnd.search_path[:] = saved
    mnd.clear_cache()


# --- library and ABI -----------------------------------------------------


def test_library_loads_and_reports_a_version(lib_path):
    assert manedpy.__lib_version__
    assert mnd.lib_path == os.path.abspath(lib_path)


def test_abi_range_is_a_range_not_an_equality():
    assert manedpy.MND_ABI_MIN <= manedpy.MND_ABI_MAX


def test_bad_library_path_is_refused(monkeypatch):
    from manedpy import _lib

    monkeypatch.setenv("MANEDPY_LIB", "/nonexistent/libmaned_c.dylib")
    with pytest.raises(_lib.ManedLibraryError) as excinfo:
        _lib.library_path()
    assert "does not exist" in str(excinfo.value)


# --- loading and refusals ------------------------------------------------


def test_load_failure_raises_ManedLoadError_with_the_cwd_caveat(conformance_dir):
    # 09_synthesized.mnd declares no out:: — it needs MND_SYNTHESIZE_OUTPUTS.
    path = os.path.join(conformance_dir, "09_synthesized.mnd")
    with pytest.raises(ManedLoadError) as excinfo:
        mnd.load(path)
    message = str(excinfo.value)
    assert "declares no out::" in message
    assert "current working directory" in message


def test_synthesize_outputs_flag_makes_it_loadable(conformance_dir):
    path = os.path.join(conformance_dir, "09_synthesized.mnd")
    with mnd.load(path, synthesize_outputs=True) as s:
        assert [o["name"] for o in s.outputs] == ["y"]
        assert s.run({"x": [[3, -1], [2, 4]]}).outputs == {"y": [[3, 0], [2, 4]]}


def test_missing_script_not_found_names_every_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("MANEDPATH", str(tmp_path / "alpha"))
    mnd.search_path.append(str(tmp_path / "beta"))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ManedScriptNotFound) as excinfo:
        mnd.io.nothing_here
    message = str(excinfo.value)
    for expected in (
        str(tmp_path / "alpha"),
        str(tmp_path / "beta"),
        str(tmp_path),
        str(tmp_path / "mnd"),
    ):
        assert os.path.realpath(expected) in message or expected in message


def test_io_rejects_underscore_names_without_touching_the_disk():
    with pytest.raises(AttributeError):
        mnd.io._ipython_canary_method_should_not_exist_
    with pytest.raises(AttributeError):
        mnd.io.__deepcopy__


def test_io_finds_and_calls_a_script(tmp_path, monkeypatch, matmul):
    shutil.copy(matmul, tmp_path / "scoring.mnd")
    monkeypatch.setenv("MANEDPATH", str(tmp_path))
    script = mnd.io.scoring
    assert script.path.endswith("scoring.mnd")
    assert mnd.io.scoring({"h0": [[3, 1], [2, 4]]}).outputs["a"] == [[7, 9], [2, 4]]


def test_io_dir_globs_the_search_path(tmp_path, monkeypatch, matmul):
    shutil.copy(matmul, tmp_path / "alpha.mnd")
    shutil.copy(matmul, tmp_path / "beta.mnd")
    monkeypatch.setenv("MANEDPATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    names = dir(mnd.io)
    assert "alpha" in names and "beta" in names


# --- routes --------------------------------------------------------------


def test_run_returns_a_Result_with_raw_and_status(matmul):
    with mnd.load(matmul) as s:
        result = s.run({"h0": [[3, 1], [2, 4]]})
    assert isinstance(result, Result) and isinstance(result, dict)
    assert result["outputs"]["a"] == [[7, 9], [2, 4]]
    assert result.outputs == result["outputs"]
    assert result.notes == []
    assert result.status == 200
    assert result.raw == b'{"outputs":{"a":[[7,9],[2,4]]},"notes":[]}'
    assert json.loads(json.dumps(result)) == dict(result)


def test_call_is_run(matmul):
    with mnd.load(matmul) as s:
        assert s({"h0": [[3, 1], [2, 4]]}) == s.run({"h0": [[3, 1], [2, 4]]})


def test_frame_and_frame_csv(frame_script):
    payload = {"t": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]}
    with mnd.load(frame_script) as s:
        assert s.frame(payload) == {"t": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]}
        assert s.frame_csv(payload) == b"a,b\n1,2\n3,4\n"


def test_run_files_round_trips_bytes(matmul):
    with mnd.load(matmul) as s:
        parts = s.run_files(h0=b"3,1\n2,4\n")
    assert parts == {"a": b"7,9\n2,4\n"}


def test_run_files_multi_output_returns_every_part(conformance_dir):
    path = os.path.join(conformance_dir, "04_multi_output.mnd")
    with mnd.load(path) as s:
        parts = s.run_files(h0=b"3,1\n2,4\n")
    assert parts == {"a": b"7,9\n2,4\n", "t": b"7,2\n9,4\n"}


def test_run_files_refuses_non_bytes(matmul):
    with mnd.load(matmul) as s:
        with pytest.raises(TypeError):
            s.run_files(h0="3,1\n2,4\n")


def test_health_hides_requests_served_but_keeps_the_contract(matmul):
    with mnd.load(matmul) as s:
        document = s.health()
        assert "requests_served" not in document
        assert [i["name"] for i in s.inputs] == ["h0", "w"]
        assert [o["name"] for o in s.outputs] == ["a"]
        assert "POST /run.json" in s.routes
        assert s.routed is False


# --- payload encoding ----------------------------------------------------


def test_allow_nan_is_off(matmul):
    with mnd.load(matmul) as s:
        with pytest.raises(ValueError) as excinfo:
            s.run({"h0": [[float("nan"), 1], [2, 4]]})
        assert "integer-only" in str(excinfo.value)
        with pytest.raises(ValueError):
            s.run({"h0": [[float("inf"), 1], [2, 4]]})


def test_payload_is_compact_json():
    assert encode_payload({"a": 1, "b": [1, 2]}) == b'{"a":1,"b":[1,2]}'
    assert encode_payload(None) == b"{}"
    assert encode_payload(b"raw") == b"raw"


def test_multipart_round_trip_survives_nuls_and_crlf():
    blobs = {"img": b"\x89PNG\r\n\x1a\n\x00\x00binary\r\n", "csv": b"1,2\n"}
    body = encode_multipart("abc123", blobs)
    assert decode_multipart("multipart/form-data; boundary=abc123", body) == blobs


def test_parse_float_hook_is_honoured(conformance_dir, tmp_path):
    """quantres > 0 returns decimal TEXT; parse_float lets a caller keep it."""
    from decimal import Decimal

    source = os.path.join(conformance_dir, "01_local_matmul.mnd")
    with open(source, encoding="utf-8") as fh:
        text = fh.read().replace("mnd::quantres=0;", "mnd::quantres=2;")
    path = tmp_path / "quantized.mnd"
    path.write_text(text, encoding="utf-8")
    with mnd.load(str(path)) as s:
        result = s.run({"h0": [[3, 1], [2, 4]]}, parse_float=Decimal)
    flat = [v for row in result.outputs["a"] for v in row]
    assert all(isinstance(v, (int, Decimal)) for v in flat)


# --- error mapping -------------------------------------------------------


def test_400_is_a_ManedInputError_and_a_ValueError(matmul):
    with mnd.load(matmul) as s:
        with pytest.raises(ManedInputError) as excinfo:
            s.run({"h0": [[3, 1], [2]]})
    assert isinstance(excinfo.value, ValueError)
    assert excinfo.value.status == 400
    assert b"ragged array" in excinfo.value.body
    assert excinfo.value.script.endswith("01_local_matmul.mnd")


def test_unknown_input_keeps_the_engines_did_you_mean(matmul):
    with mnd.load(matmul) as s:
        with pytest.raises(ManedInputError) as excinfo:
            s.run({"h1": [[1, 0], [0, 1]]})
    assert "did you mean 'h0'?" in str(excinfo.value)


def test_404_is_a_ManedRouteError(matmul):
    with mnd.load(matmul) as s:
        response = s.request("GET", "/nope", None, b"")
        assert response.status == 404
        with pytest.raises(ManedRouteError):
            from manedpy.errors import raise_for_response

            raise_for_response(response, s.path)


def test_405_is_a_ManedRouteError(matmul):
    from manedpy.errors import raise_for_response

    with mnd.load(matmul) as s:
        response = s.request("PUT", "/run.json", None, b"{}")
        assert response.status == 405
        with pytest.raises(ManedRouteError):
            raise_for_response(response, s.path)


def test_500_is_a_ManedRuntimeError_and_a_RuntimeError(conformance_dir):
    path = os.path.join(conformance_dir, "08_err_runtime.mnd")
    with mnd.load(path) as s:
        with pytest.raises(ManedRuntimeError) as excinfo:
            s.run({"h0": [[1, 2, 3], [4, 5, 6], [7, 8, 9]]})
    assert isinstance(excinfo.value, RuntimeError)
    assert excinfo.value.status == 500


def test_status_zero_maps_to_ManedInternalError():
    """status 0 is an escaped C++ exception, distinct from every HTTP code."""
    assert error_for_status(0) is ManedInternalError
    assert error_for_status(501) is ManedUnsupportedError
    assert error_for_status(413) is ManedInputError
    assert error_for_status(431) is ManedInputError


# --- concurrency ---------------------------------------------------------


def test_concurrent_true_is_refused_for_a_routed_script(tmp_path, matmul):
    """A routed script drives single-connection channels; the library checks.

    Skipped when no routed script is available: the corpus is deliberately
    device-free so it can run anywhere.
    """
    source = open(matmul, encoding="utf-8").read()
    routed = source.replace(
        "calc::lambda_flow f(h0, w) {",
        'device::rex { host = "local"; vm = "/opt/bark-vm"; }\n\n'
        "calc::lambda_flow f(h0, w) @device(rex) {",
    )
    path = tmp_path / "routed.mnd"
    path.write_text(routed, encoding="utf-8")
    try:
        script = mnd.load(str(path))
    except ManedLoadError as exc:
        pytest.skip("no routed script available here: %s" % exc)
    is_routed = script.routed
    script.close()
    if not is_routed:
        pytest.skip("the @device spelling used here did not produce a routed script")
    with pytest.raises(ManedLoadError) as excinfo:
        mnd.load(str(path), concurrent=True)
    assert "concurrent=True is refused" in str(excinfo.value)


def test_concurrent_true_gives_identical_results_from_eight_threads(matmul):
    payload = {"h0": [[3, 1], [2, 4]]}
    with mnd.load(matmul, concurrent=True) as s:
        assert s.routed is False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: s.run(payload).raw, range(200)))
    assert len(set(results)) == 1
    assert results[0] == b'{"outputs":{"a":[[7,9],[2,4]]},"notes":[]}'


def test_the_default_lock_also_survives_eight_threads(matmul):
    payload = {"h0": [[3, 1], [2, 4]]}
    with mnd.load(matmul) as s:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: s.run(payload).raw, range(200)))
    assert len(set(results)) == 1


# --- caching and lifetime ------------------------------------------------


def test_the_same_path_is_cached(matmul):
    assert mnd.load(matmul) is mnd.load(matmul)


def test_reload_bypasses_the_cache(matmul):
    first = mnd.load(matmul)
    second = mnd.load(matmul, reload=True)
    assert first is not second
    assert first.closed, "the superseded handle must be closed, not leaked"


def test_flags_are_part_of_the_cache_key(conformance_dir):
    path = os.path.join(conformance_dir, "09_synthesized.mnd")
    a = mnd.load(path, synthesize_outputs=True)
    b = mnd.load(path, synthesize_outputs=True, no_vm_fallback=True)
    assert a is not b


def test_editing_the_script_invalidates_the_cache(tmp_path, matmul):
    path = tmp_path / "edit_me.mnd"
    shutil.copy(matmul, path)
    first = mnd.load(str(path))
    assert first.run({"h0": [[3, 1], [2, 4]]}).outputs["a"] == [[7, 9], [2, 4]]

    text = path.read_text(encoding="utf-8").replace(
        "in::w = [[1,2],[0,1]];", "in::w = [[1,0],[0,1]];"
    )
    time.sleep(0.01)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(time.time_ns(), time.time_ns() + 1_000_000_000))

    second = mnd.load(str(path))
    assert second is not first
    assert second.run({"h0": [[3, 1], [2, 4]]}).outputs["a"] == [[3, 1], [2, 4]]


def test_clear_cache_closes_everything(matmul):
    script = mnd.load(matmul)
    mnd.clear_cache()
    assert script.closed
    assert mnd.load(matmul) is not script


def test_close_is_idempotent_and_a_closed_script_refuses(matmul):
    script = mnd.load(matmul)
    script.close()
    script.close()
    with pytest.raises(Exception):
        script.run({"h0": [[3, 1], [2, 4]]})


def test_the_atexit_registry_tracks_open_handles(matmul):
    from manedpy import _lib

    before = _lib.live_count()
    script = mnd.load(matmul, reload=True)
    assert _lib.live_count() == before + 1
    script.close()
    assert _lib.live_count() == before


def test_close_waits_for_an_in_flight_call(matmul, monkeypatch):
    """mnd_close on a handle another thread is inside is a use-after-free.

    concurrent=True drops the per-call lock, so close() has to hold a
    separate in-flight count rather than rely on that lock to have drained.
    """
    import threading

    import manedpy.script as script_module

    real = script_module._ffi.request
    entered = threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        time.sleep(0.3)
        return real(*args, **kwargs)

    script = mnd.load(matmul, concurrent=True, reload=True)
    monkeypatch.setattr(script_module._ffi, "request", slow)

    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(script.run({"h0": [[3, 1], [2, 4]]}))
    )
    worker.start()
    assert entered.wait(5)
    start = time.monotonic()
    script.close()
    elapsed = time.monotonic() - start
    worker.join(5)

    assert elapsed >= 0.2, "close() returned while a call was still running"
    assert outcome and outcome[0].outputs["a"] == [[7, 9], [2, 4]]


def test_the_atexit_hook_closes_live_handles(matmul):
    """Hazard 4: __del__ is not guaranteed at interpreter shutdown.

    An unclosed handle can leave a bark-vm child holding a pipe, so the
    closing is driven from atexit as well.
    """
    from manedpy import _lib

    script = mnd.load(matmul, reload=True)
    _lib._close_all()
    assert script.closed


def test_the_atexit_hook_actually_fires(tmp_path):
    """Gate 9: prove the registration, not just the function body.

    A sentinel is pushed into the live registry and the interpreter is let go
    normally; if _close_all is not really an atexit hook, the marker file
    never appears.
    """
    import subprocess
    import sys

    marker = tmp_path / "closed.marker"
    program = (
        "from manedpy import _lib\n"
        "class Sentinel:\n"
        "    def close(self):\n"
        "        open(%r, 'w').write('closed')\n"
        # A module-level name: the registry is a WeakSet, so a sentinel with
        # no strong reference would be collected before exit.
        "sentinel = Sentinel()\n"
        "_lib.register(sentinel)\n" % str(marker)
    )
    subprocess.run(
        [sys.executable, "-c", program],
        check=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=dict(os.environ),
    )
    assert marker.exists(), "the atexit hook did not close the live registry"


def test_after_fork_replaces_the_lock(matmul):
    """Hazard 5: a threading.Lock held at fork time deadlocks the child."""
    from manedpy import _lib

    script = mnd.load(matmul, reload=True)
    before = script._lock
    _lib._after_fork_in_child()
    assert script._lock is not before
    assert script.run({"h0": [[3, 1], [2, 4]]}).outputs["a"] == [[7, 9], [2, 4]]
    script.close()


def test_survives_a_real_fork(matmul):
    """The whole at-fork path, in a child that actually calls run()."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        code = 1
        try:
            os.close(read_fd)
            with mnd.load(matmul, reload=True) as s:
                out = s.run({"h0": [[3, 1], [2, 4]]}).outputs["a"]
            os.write(write_fd, json.dumps(out).encode())
            code = 0
        finally:
            os._exit(code)
    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as fh:
        payload = fh.read()
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
    assert json.loads(payload.decode()) == [[7, 9], [2, 4]]


def test_set_kernel_threads_changes_timing_not_values(matmul):
    with mnd.load(matmul) as s:
        baseline = s.run({"h0": [[3, 1], [2, 4]]}).raw
        mnd.set_kernel_threads(2)
        assert s.run({"h0": [[3, 1], [2, 4]]}).raw == baseline
        mnd.set_kernel_threads(1)
