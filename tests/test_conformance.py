"""The cross-binding conformance corpus, walked (MANEDPY_PLAN.md §6, gate 5).

One fixture set shipped in the maned-capi-* tarball, so the parity corpus
exists ONCE and cannot fork. Every case is compared BYTE-FOR-BYTE: an
expectation that only matches after json.loads would not catch a key-order or
separator change, which is exactly the drift this gate exists to see.
"""

import os

import pytest

from manedpy import maned as mnd

from conftest import flags_of, load_cases

# conftest has already resolved $MANEDPY_LIB by the time this module is
# imported, so the corpus can be enumerated at collection time and every case
# gets its own test id.
_LIB = os.environ.get("MANEDPY_LIB")
_DIR = (
    os.path.join(os.path.dirname(os.path.dirname(_LIB)), "conformance")
    if _LIB
    else None
)
_CASES = load_cases(_DIR) if _DIR and os.path.isdir(_DIR) else []


@pytest.mark.parametrize(
    "name,script,request_spec,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_conformance_case(name, script, request_spec, expected):
    with mnd.load(script, reload=True, **flags_of(request_spec)) as s:
        response = s.request(
            request_spec["method"],
            request_spec["target"],
            None,
            request_spec.get("body", "").encode("utf-8"),
        )
    assert response.status == expected["status"], "%s: body %r" % (
        name,
        response.body,
    )
    assert response.content_type == expected["content_type"], name
    assert response.body == expected["body"].encode("utf-8"), (
        "%s: response bytes differ\n  got      %r\n  expected %r"
        % (name, response.body, expected["body"].encode("utf-8"))
    )


def test_corpus_is_not_empty(conformance_dir):
    """A silently empty corpus would make the gate above vacuously green."""
    assert len(load_cases(conformance_dir)) >= 9
