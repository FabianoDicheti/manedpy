"""Gate 5: in-process bytes == maned-serve's bytes, over a real socket.

The whole design in one assertion. For every /run.json case in the corpus,
maned-serve answers the same body over HTTP that manedpy's raw request path
answers in-process, byte for byte.

Scope, per MANEDPY_PLAN.md Phase 1's note: /run.json only. /run and /frame
salt the multipart boundary with requests_served, and /health embeds both
requests_served and the script path — the in-process handle and the
subprocess can never agree on either, so /health is compared structurally
instead.
"""

import http.client
import json
import os

import pytest

from manedpy import maned as mnd

from conftest import ServeProcess, flags_of, load_cases

_LIB = os.environ.get("MANEDPY_LIB")
_DIR = (
    os.path.join(os.path.dirname(os.path.dirname(_LIB)), "conformance")
    if _LIB
    else None
)
_ALL = load_cases(_DIR) if _DIR and os.path.isdir(_DIR) else []

#: mnd_open flag name -> the maned-serve flag that sets the same bit. A case
#: whose flags are all spellable here is loaded identically on both sides and
#: can be compared; one naming a flag with no CLI counterpart is EXCLUDED
#: rather than silently compared against a differently-loaded server. The
#: conformance walker still covers those in-process.
_SERVE_FLAGS = {
    "synthesize_outputs": "--synthesize-outputs",
    "no_vm_fallback": "--no-vm-fallback",
}


def _serve_args(request_spec):
    """The CLI flags for this case, or None when one has no CLI spelling."""
    args = []
    for flag in request_spec.get("flags", []):
        if flag not in _SERVE_FLAGS:
            return None
        args.append(_SERVE_FLAGS[flag])
    return args


_PARITY = [
    c
    for c in _ALL
    if c[2]["target"] == "/run.json" and _serve_args(c[2]) is not None
]


def _post(port, target, body, content_type="application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        conn.request("POST", target, body=body, headers={"Content-Type": content_type})
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type"), response.read()
    finally:
        conn.close()


def _get(port, target):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        conn.request("GET", target)
        response = conn.getresponse()
        return response.status, response.getheader("Content-Type"), response.read()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "name,script,request_spec,expected", _PARITY, ids=[c[0] for c in _PARITY]
)
def test_run_json_parity(maned_serve, name, script, request_spec, expected):
    body = request_spec.get("body", "").encode("utf-8")

    with mnd.load(script, reload=True, **flags_of(request_spec)) as s:
        in_process = s.request("POST", "/run.json", None, body)

    with ServeProcess(
        maned_serve, script, max_requests=8, extra_args=_serve_args(request_spec)
    ) as server:
        status, content_type, over_http = _post(server.port, "/run.json", body)

    assert status == in_process.status, name
    assert content_type == in_process.content_type, name
    assert over_http == in_process.body, (
        "%s: HTTP and in-process bodies differ\n  http      %r\n  in-process %r"
        % (name, over_http, in_process.body)
    )
    # ...and both still match the frozen expectation, so a corpus that drifted
    # in lockstep with the engine cannot make this gate vacuously green.
    assert in_process.body == expected["body"].encode("utf-8"), name


def test_health_parity_is_structural(maned_serve):
    """/health is not byte-comparable; its contract fields still are.

    requests_served tracks a different call history in each process and
    `script` differs the moment one side is given a different spelling of the
    path, so only flows/inputs/outputs/profiles/routes are asserted.
    """
    if not _ALL:
        pytest.skip("no conformance corpus")
    script = _ALL[0][1]

    with mnd.load(script, reload=True) as s:
        local = s.health()

    with ServeProcess(maned_serve, script, max_requests=4) as server:
        status, _, raw = _get(server.port, "/health")
    remote = json.loads(raw.decode("utf-8"))

    assert status == 200
    assert "requests_served" not in local, "Script.health() must not expose it"
    for field in ("status", "flows", "inputs", "outputs", "profiles", "routes"):
        assert local[field] == remote[field], field


def test_parity_corpus_is_not_empty():
    assert _PARITY, "no /run.json cases found — gate 5 would be vacuous"


def test_flagged_cases_are_in_the_gate():
    """A flag the CLI cannot spell silently shrinks gate 5; say so loudly.

    Every /run.json case in the corpus must be comparable: if one names a
    flag with no maned-serve counterpart it drops out of _PARITY above, and
    the gate gets quietly weaker rather than red.
    """
    flagged = [c for c in _ALL if c[2]["target"] == "/run.json" and c[2].get("flags")]
    if not flagged:
        pytest.skip("no flagged /run.json cases in this corpus")
    covered = {c[0] for c in _PARITY}
    missing = [c[0] for c in flagged if c[0] not in covered]
    assert not missing, (
        "no maned-serve flag for %s — those cases are excluded from gate 5"
        % missing
    )
