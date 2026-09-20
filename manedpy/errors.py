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
