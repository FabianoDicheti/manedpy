"""The ManedError hierarchy (MANEDPY_PLAN.md §4).

All carry .status, .body, .script. error_response bodies are plain text, not
JSON — branch on status before decoding.
"""


class ManedError(Exception):
    def __init__(self, message, *, status=None, body=None, script=None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.script = script


class ManedLoadError(ManedError):
    """mnd_open returned NULL."""


class ManedScriptNotFound(ManedError, FileNotFoundError):
    """mnd.io miss — the message names every directory searched."""


class ManedInputError(ManedError, ValueError):
    """400, 413, 431."""


class ManedRouteError(ManedError):
    """404, 405."""


class ManedRuntimeError(ManedError, RuntimeError):
    """500."""


class ManedUnsupportedError(ManedError):
    """501."""


class ManedInternalError(ManedError):
    """status == 0 — an escaped C++ exception."""


#: Exact statuses the engine's error_response emits, per MANEDPY_PLAN.md §4.
#: 413 and 431 are wire limits that in-process requests cannot hit, but they
#: stay mapped: the ABI's promise is that a response is what maned-serve
#: would have answered, and a future route may well raise them.
_BY_STATUS = {
    0: ManedInternalError,
    400: ManedInputError,
    404: ManedRouteError,
    405: ManedRouteError,
    413: ManedInputError,
    431: ManedInputError,
    500: ManedRuntimeError,
    501: ManedUnsupportedError,
}


def error_for_status(status):
    """The exception class for a non-2xx status.

    Unmapped 4xx/5xx fall back by class rather than to a bare ManedError, so
    a route added after this table was written still raises something a
    caller can catch meaningfully.
    """
    cls = _BY_STATUS.get(status)
    if cls is not None:
        return cls
    if 400 <= status < 500:
        return ManedRouteError
    if status >= 500:
        return ManedRuntimeError
    return ManedError


def raise_for_response(response, script_path):
    """Turn a non-2xx Response into the mapped exception, and raise it.

    The body is plain text on every error path (src/serve/server.cpp's
    error_response), so it is decoded as text and never as JSON — that is why
    callers must branch on status BEFORE decoding.
    """
    status = response.status
    if 200 <= status < 300:
        return
    text = response.body.decode("utf-8", "replace").rstrip("\n")
    cls = error_for_status(status)
    if status == 0:
        message = "%s: internal error in the maned engine: %s" % (script_path, text)
    else:
        message = "%s: HTTP %d: %s" % (script_path, status, text)
    raise cls(message, status=status, body=response.body, script=script_path)
