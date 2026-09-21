"""mnd_response struct, open/request wrappers, free discipline (MANEDPY_PLAN.md §4).

Two ownership rules: char* out-params from mnd_open -> mnd_free_string;
mnd_response* -> mnd_response_free. Python never calls libc.free.
This file is a transcription of maned_c.h — a drift-check test must diff every
signature against the header (MANEDPY_PLAN.md §8.3).
"""

import ctypes
import os

from .errors import ManedLoadError

# --- maned_c.h, verbatim -------------------------------------------------

MND_ABI_VERSION = 1

MND_SYNTHESIZE_OUTPUTS = 1 << 0  # return-only scripts servable
MND_NO_VM_FALLBACK = 1 << 1  # unreachable device = hard error

#: Keyword name -> flag bit, for mnd.load(path, **flags).
FLAG_NAMES = {
    "synthesize_outputs": MND_SYNTHESIZE_OUTPUTS,
    "no_vm_fallback": MND_NO_VM_FALLBACK,
}


class MndResponse(ctypes.Structure):
    """struct mnd_response.

    `body` is deliberately c_void_p, not c_char_p: the header says the body
    MAY CONTAIN NULs and that body_len is the truth, so ctypes must never be
    allowed to strlen() it into a Python bytes object.
    """

    _fields_ = [
        ("status", ctypes.c_int32),
        ("content_type", ctypes.c_char_p),
        ("body", ctypes.c_void_p),
        ("body_len", ctypes.c_size_t),
        ("notes", ctypes.c_char_p),
    ]


#: name -> (restype, argtypes). The one table the drift check diffs against
#: the header; nothing else in this package may name an mnd_* signature.
SIGNATURES = {
    "mnd_abi_version": (ctypes.c_int32, []),
    "mnd_version": (ctypes.c_char_p, []),
    "mnd_open": (
        ctypes.c_void_p,
        [
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_char_p),
        ],
    ),
    "mnd_close": (None, [ctypes.c_void_p]),
    "mnd_request": (
        ctypes.POINTER(MndResponse),
        [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ],
    ),
    "mnd_response_free": (None, [ctypes.POINTER(MndResponse)]),
    "mnd_free_string": (None, [ctypes.c_char_p]),
    "mnd_set_kernel_threads": (None, [ctypes.c_int32]),
    "mnd_script_is_routed": (ctypes.c_int32, [ctypes.c_void_p]),
}


def bind(dll):
    """Apply SIGNATURES to a freshly loaded CDLL.

    mnd_open returns c_void_p rather than a typed pointer on purpose: ctypes
    narrows a plain c_int restype to 32 bits and would truncate the handle.
    """
    for name, (restype, argtypes) in SIGNATURES.items():
        fn = getattr(dll, name)
        fn.restype = restype
        fn.argtypes = argtypes
    return dll


# --- the two ownership rules --------------------------------------------


class Response:
    """One mnd_response, copied out of C storage before it is freed.

    Nothing here is ever NULL (the header's nullability rule), but the
    defensive `or` fallbacks stay: a binding that trusts a contract it cannot
    enforce turns an engine bug into a segfault.
    """

    __slots__ = ("status", "content_type", "body", "notes")

    def __init__(self, status, content_type, body, notes):
        self.status = status
        self.content_type = content_type
        self.body = body
        self.notes = notes

    def __repr__(self):
        return "Response(status=%r, content_type=%r, body_len=%d)" % (
            self.status,
            self.content_type,
            len(self.body),
        )


def take_string(dll, cptr):
    """Consume a char* out-param: copy the bytes, then mnd_free_string it."""
    if not cptr.value:
        return None
    text = cptr.value.decode("utf-8", "replace")
    dll.mnd_free_string(cptr)
    cptr.value = None
    return text


def open_script(dll, path, flags):
    """mnd_open -> (handle, load_notes). Raises ManedLoadError on NULL.

    Hazard 1 (MANEDPY_PLAN.md §5): the message gets the CWD caveat appended,
    because a relative csv()/image() path inside the script resolves against
    Python's working directory and that is the #1 support question.
    """
    err = ctypes.c_char_p()
    notes = ctypes.c_char_p()
    handle = dll.mnd_open(
        str(path).encode("utf-8"), flags, ctypes.byref(err), ctypes.byref(notes)
    )
    message = take_string(dll, err)
    note_text = take_string(dll, notes)
    if not handle:
        detail = message or "mnd_open failed without a message"
        raise ManedLoadError(
            "%s: %s (data paths inside the script resolve against the current "
            "working directory, %s, not the script's directory)"
            % (path, detail, _cwd()),
            status=None,
            body=message,
            script=str(path),
        )
    return handle, note_text


def request(dll, handle, method, target, content_type, body):
    """mnd_request -> Response, with mnd_response_free always paired.

    The static bad_alloc sentinel is freed exactly like any other response —
    mnd_response_free recognizes it and no-ops (MANEDPY_PLAN.md Phase 1).
    """
    payload = body or b""
    raw = dll.mnd_request(
        handle,
        method.encode("ascii"),
        target.encode("ascii"),
        content_type.encode("ascii") if content_type else None,
        payload,
        len(payload),
    )
    if not raw:
        # The header says this cannot happen. Refuse loudly rather than
        # dereference NULL.
        raise RuntimeError("mnd_request returned NULL, which the ABI forbids")
    try:
        r = raw.contents
        data = ctypes.string_at(r.body, r.body_len) if r.body_len else b""
        return Response(
            int(r.status),
            (r.content_type or b"").decode("utf-8", "replace"),
            data,
            (r.notes or b"").decode("utf-8", "replace"),
        )
    finally:
        dll.mnd_response_free(raw)


def close_script(dll, handle):
    """mnd_close; NULL is a no-op on the C side too."""
    if handle:
        dll.mnd_close(ctypes.c_void_p(handle))


def _cwd():
    try:
        return os.getcwd()
    except OSError:  # a deleted CWD is not a reason to lose the load error
        return "<unavailable>"
