"""Gate 8: _ffi.SIGNATURES is a third copy of maned_c.h — diff it (§8.3).

The header lives in two repos and the ctypes argtypes table is a transcription
of it, so the contract has three statements and exactly one meaning. This
parses the header shipped beside the library and diffs every declaration
against the table; the drift it catches is the same shape gate_manifest.sh and
include/maned/version.h both exist to prevent.
"""

import ctypes
import os
import re

import pytest

from manedpy import _ffi

_C_TO_CTYPES = {
    "void": None,
    "int32_t": ctypes.c_int32,
    "uint32_t": ctypes.c_uint32,
    "size_t": ctypes.c_size_t,
    "const char *": ctypes.c_char_p,
    "char *": ctypes.c_char_p,
    "char **": ctypes.POINTER(ctypes.c_char_p),
    # Opaque handles cross as void*: ctypes narrows a plain int restype to 32
    # bits, which would truncate a 64-bit pointer.
    "mnd_script *": ctypes.c_void_p,
    "const mnd_script *": ctypes.c_void_p,
    "mnd_response *": ctypes.POINTER(_ffi.MndResponse),
}

_DECL = re.compile(
    r"^\s*(?P<ret>(?:const\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\**)\s*"
    r"(?P<name>mnd_[a-z_]+)\s*\((?P<args>[^;]*?)\)\s*;",
    re.MULTILINE | re.DOTALL,
)


@pytest.fixture(scope="module")
def header(capi_dir):
    path = os.path.join(capi_dir, "include", "maned_c.h")
    if not os.path.exists(path):
        pytest.skip("no maned_c.h beside the library")
    with open(path, encoding="utf-8") as fh:
        return _strip_comments(fh.read())


def _strip_comments(text):
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)


def _normalize(type_text):
    text = " ".join(type_text.split())
    text = text.replace("* *", "**").replace(" *", " *")
    text = re.sub(r"\s*\*", " *", text).strip()
    text = re.sub(r"\*\s+\*", "**", text)
    return text


def _map(type_text):
    normalized = _normalize(type_text)
    if normalized not in _C_TO_CTYPES:
        raise AssertionError("no ctypes mapping for C type %r" % normalized)
    return _C_TO_CTYPES[normalized]


def _parse(header_text):
    declared = {}
    for match in _DECL.finditer(header_text):
        args_text = match.group("args").strip()
        if args_text in ("", "void"):
            argtypes = []
        else:
            argtypes = []
            for arg in args_text.split(","):
                arg = " ".join(arg.split())
                # Drop the parameter name: the last identifier, unless the
                # declaration is anonymous.
                arg = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*$", "", arg).strip()
                argtypes.append(_map(arg))
        declared[match.group("name")] = (_map(match.group("ret")), argtypes)
    return declared


def test_every_header_declaration_is_bound(header):
    declared = _parse(header)
    assert declared, "parsed no mnd_* declarations out of maned_c.h"
    assert set(declared) == set(_ffi.SIGNATURES), (
        "_ffi.SIGNATURES and maned_c.h disagree on the entry points: "
        "only in header %s, only in _ffi %s"
        % (
            sorted(set(declared) - set(_ffi.SIGNATURES)),
            sorted(set(_ffi.SIGNATURES) - set(declared)),
        )
    )
    for name, (restype, argtypes) in declared.items():
        assert _ffi.SIGNATURES[name] == (restype, argtypes), name


def test_the_flag_constants_match_the_header(header):
    for macro, value in (
        ("MND_SYNTHESIZE_OUTPUTS", _ffi.MND_SYNTHESIZE_OUTPUTS),
        ("MND_NO_VM_FALLBACK", _ffi.MND_NO_VM_FALLBACK),
        ("MND_ABI_VERSION", _ffi.MND_ABI_VERSION),
    ):
        match = re.search(r"#define\s+%s\s+(.+)" % macro, header)
        assert match, macro
        # C integer suffixes (1u << 0) are not Python literals.
        expression = re.sub(
            r"\b(\d+)[uUlL]+\b", r"\1", match.group(1).strip()
        )
        assert eval(expression) == value, macro  # noqa: S307


def test_the_struct_layout_matches_the_manifest(capi_dir):
    """The same assertion _lib makes at load time, stated as a test."""
    import json

    path = os.path.join(capi_dir, "maned_c_abi.json")
    if not os.path.exists(path):
        pytest.skip("no maned_c_abi.json beside the library")
    with open(path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    spec = manifest["structs"]["mnd_response"]
    assert ctypes.sizeof(_ffi.MndResponse) == spec["sizeof"]
    for field, offset in spec["fields"].items():
        assert getattr(_ffi.MndResponse, field).offset == offset, field
