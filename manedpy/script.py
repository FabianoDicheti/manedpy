"""Script: per-handle lock, routes, close/__enter__/__del__ (MANEDPY_PLAN.md §4).

Routes: run/__call__ -> POST /run.json; frame -> /frame; frame_csv ->
/frame.csv; run_files -> /run multipart (the only way to get real PNG bytes
back); health -> GET /health; .inputs/.outputs cached from /health.

Default: a per-Script lock (routed scripts are not thread-safe). concurrent=True
is refused at load unless mnd_script_is_routed() == 0.
"""

import json
import secrets
import threading

from . import _ffi
from . import _lib
from . import result as _result
from .errors import ManedError, raise_for_response

_JSON = "application/json"


class _NoLock:
    """The lock a concurrent=True Script uses: none at all.

    testConcurrentHandleIsIdenticalGap025 proves 8x25 concurrent handle()
    calls on one NON-routed handle are identical, so serializing them buys
    nothing and costs a second parse of the program per thread.
    """

    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Script:
    """One loaded .mnd, one mnd_script handle.

    Construct through manedpy.maned.load(); the constructor takes an already
    open handle because a failed mnd_open has no Script to attach itself to.
    """

    def __init__(self, dll, handle, path, flags, concurrent, load_notes, owner=None):
        self._dll = dll
        self._handle = handle
        self._lock = _NoLock() if concurrent else threading.Lock()
        # _gate guards _closed and _inflight only — never the call itself, so
        # a concurrent=True Script still runs its requests in parallel. It
        # exists so close() cannot free a handle a live call is still using:
        # that is a use-after-free in C, i.e. a dead Jupyter kernel.
        self._gate = threading.Lock()
        self._idle = threading.Condition(self._gate)
        self._inflight = 0
        self._closed = False
        self._health = None
        self._owner = owner
        self.path = path
        self.flags = flags
        self.concurrent = concurrent
        self.load_notes = load_notes
        self.routed = bool(dll.mnd_script_is_routed(handle))
        _lib.register(self)

    # --- the raw request path -------------------------------------------

    def request(self, method, target, content_type=None, body=b""):
        """One request -> one _ffi.Response, unmapped and unparsed.

        The escape hatch every typed route below is built on, and what a
        conformance harness walks the fixture corpus with. Callers get the
        status, the exact bytes and the notes; nothing is raised for a 4xx.
        """
        with self._gate:
            if self._closed:
                raise ManedError(
                    "%s: this Script is closed" % self.path, script=self.path
                )
            self._inflight += 1
        try:
            with self._lock:
                return _ffi.request(
                    self._dll, self._handle, method, target, content_type, body
                )
        finally:
            with self._gate:
                self._inflight -= 1
                if self._inflight == 0:
                    self._idle.notify_all()

    # --- routes ----------------------------------------------------------

    def __call__(self, payload=None, *, parse_float=None):
        return self.run(payload, parse_float=parse_float)

    def run(self, payload=None, *, parse_float=None):
        """POST /run.json -> Result.

        NOTE: calls are uninterruptible — ctypes.CDLL releases the GIL (which
        is the point: a long matmul must not block the interpreter), so a
        KeyboardInterrupt raised during a long mnd_request is delivered only
        when the call returns. Ctrl-C in a REPL and "interrupt kernel" in
        Jupyter both do nothing until then. Use multiprocessing with the
        `spawn` start method for work long enough to want to cancel
        (MANEDPY_PLAN.md hazard 2).
        """
        response = self.request("POST", "/run.json", None, encode_payload(payload))
        return self._as_result(response, parse_float)

    def frame(self, payload=None, *, parse_float=None):
        """POST /frame -> Result (the frame:: tables as JSON records)."""
        response = self.request("POST", "/frame", None, encode_payload(payload))
        return self._as_result(response, parse_float)

    def frame_csv(self, payload=None):
        """POST /frame.csv -> bytes. CSV text, returned undecoded."""
        response = self.request("POST", "/frame.csv", None, encode_payload(payload))
        raise_for_response(response, self.path)
        return response.body

    def run_files(self, **named_bytes):
        """POST /run as multipart -> {output name: bytes}.

        The only way to get real file bytes back: /run.json renders an image
        out:: as a nested int array. Each keyword is an in:: name and its
        value the raw file bytes for that input.

        A single-output script answers with the bare file and no part name,
        so the one declared out:: name is used as the key.
        """
        for name, data in named_bytes.items():
            if not isinstance(data, (bytes, bytearray, memoryview)):
                raise TypeError(
                    "run_files(%s=...) wants raw bytes, got %s"
                    % (name, type(data).__name__)
                )
        boundary = "manedpy" + secrets.token_hex(12)
        body = encode_multipart(boundary, named_bytes)
        response = self.request(
            "POST", "/run", "multipart/form-data; boundary=" + boundary, body
        )
        raise_for_response(response, self.path)
        return self._decode_parts(response)

    def health(self):
        """GET /health -> dict, minus requests_served.

        requests_served counts in-process calls on this handle only. It looks
        like a server metric and is not one, so it is not exposed
        (MANEDPY_PLAN.md Phase 1 note).
        """
        document = dict(self._health_document())
        document.pop("requests_served", None)
        return document

    @property
    def inputs(self):
        """The in:: contract: [{"name", "format", "default"}, ...]."""
        return self._health_document().get("inputs", [])

    @property
    def outputs(self):
        """The response schema: [{"name", "format"}, ...].

        With MND_SYNTHESIZE_OUTPUTS this lists the synthesized names, because
        synthesis happens in script.outputs itself — so .outputs and what
        .run() returns cannot disagree.
        """
        return self._health_document().get("outputs", [])

    @property
    def routes(self):
        return self._health_document().get("routes", [])

    # --- lifetime --------------------------------------------------------

    def close(self):
        """Idempotent. Also what the atexit hook calls (hazard 4)."""
        with self._gate:
            if self._closed:
                return
            # Refuse new calls first, then wait for the live ones: mnd_close
            # on a handle another thread is inside is a use-after-free.
            self._closed = True
            while self._inflight:
                self._idle.wait()
            handle, self._handle = self._handle, None
        _lib.unregister(self)
        if self._owner is not None:
            self._owner._forget(self)
        _ffi.close_script(self._dll, handle)

    @property
    def closed(self):
        return self._closed

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        # Interpreter shutdown tears module globals down to None underneath
        # us; a __del__ that raises there prints an unignorable traceback.
        if _lib is None or _ffi is None:
            return
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self):
        return "<manedpy.Script %s%s%s>" % (
            self.path,
            " routed" if self.routed else "",
            " closed" if self._closed else "",
        )

    # --- internals -------------------------------------------------------

    def _reinit_lock(self):
        """After fork: a Lock held by a thread that did not survive is dead.

        The in-flight count goes with them — only the forking thread exists
        in the child, and it was not inside a call or the fork would have
        happened mid-request, which no reinitialization can rescue.
        """
        self._lock = _NoLock() if self.concurrent else threading.Lock()
        self._gate = threading.Lock()
        self._idle = threading.Condition(self._gate)
        self._inflight = 0

    def _health_document(self):
        if self._health is None:
            response = self.request("GET", "/health", None, b"")
            raise_for_response(response, self.path)
            self._health = json.loads(response.body.decode("utf-8"))
        return self._health

    def _as_result(self, response, parse_float):
        raise_for_response(response, self.path)
        document = json.loads(
            response.body.decode("utf-8"), parse_float=parse_float
        )
        return _result.build(document, response.body, response.status)

    def _decode_parts(self, response):
        content_type = response.content_type or ""
        if content_type.lower().startswith("multipart/"):
            return decode_multipart(content_type, response.body)
        names = [o.get("name") for o in self.outputs if o.get("name")]
        key = names[0] if len(names) == 1 else "body"
        return {key: response.body}


# --- body encoding -------------------------------------------------------


def encode_payload(payload):
    """dict -> the exact request body bytes.

    separators strip the whitespace json.dumps adds by default; allow_nan is
    off deliberately — an integer-only language should reject NaN/inf in
    Python with a clear error rather than emit bare `NaN` and let the
    engine's parser refuse at a byte offset.
    """
    if payload is None:
        payload = {}
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    try:
        return json.dumps(
            payload, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except ValueError as exc:
        raise ValueError(
            "payload is not encodable as maned JSON (%s); maned is an "
            "integer-only language, so NaN and Infinity are refused here "
            "rather than at a byte offset inside the engine" % exc
        ) from exc


def encode_multipart(boundary, named_bytes):
    """Each in:: name becomes one form-data part carrying its raw bytes."""
    marker = ("--" + boundary).encode("ascii")
    chunks = []
    for name, data in named_bytes.items():
        chunks.append(marker + b"\r\n")
        chunks.append(
            b'Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
            % (name.encode("utf-8"), name.encode("utf-8"))
        )
        chunks.append(b"Content-Type: application/octet-stream\r\n\r\n")
        chunks.append(bytes(data))
        chunks.append(b"\r\n")
    chunks.append(marker + b"--\r\n")
    return b"".join(chunks)


def decode_multipart(content_type, body):
    """multipart/form-data -> {part name: bytes}.

    Deliberately not email.parser: the parts are arbitrary binary (PNG,
    parquet) and the stdlib message parsers want text or re-encode it.
    """
    boundary = _boundary_of(content_type)
    if boundary is None:
        raise ManedError("no boundary in Content-Type %r" % content_type)
    marker = b"--" + boundary.encode("ascii")
    parts = {}
    for segment in body.split(marker):
        if segment in (b"", b"--\r\n", b"--", b"\r\n"):
            continue
        segment = segment.lstrip(b"\r\n")
        head, _, data = segment.partition(b"\r\n\r\n")
        if not _:
            continue
        name = _part_name(head)
        if name is None:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        parts[name] = data
    return parts


def _boundary_of(content_type):
    for token in content_type.split(";")[1:]:
        key, _, value = token.strip().partition("=")
        if key.strip().lower() == "boundary":
            return value.strip().strip('"')
    return None


def _part_name(head):
    for line in head.split(b"\r\n"):
        if not line.lower().startswith(b"content-disposition:"):
            continue
        for token in line.split(b";")[1:]:
            key, _, value = token.strip().partition(b"=")
            if key.strip().lower() == b"name":
                return value.strip().strip(b'"').decode("utf-8", "replace")
    return None
