"""Shared fixtures: the library, the conformance corpus, maned-serve.

The library is located exactly the way manedpy locates it — $MANEDPY_LIB —
so the tests exercise the real discovery path. In a source checkout the
bundled manedpy/_lib/ is empty, so $MANEDPY_LIB must point at a libmaned_c
from a maned-capi-* tarball; a sibling capi-freeze/ checkout is used as a
convenience default so `pytest` works with no environment at all.
"""

import json
import os
import socket
import subprocess
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE = os.path.dirname(os.path.dirname(_HERE))

_DEFAULT_LIBS = (
    os.path.join(_WORKSPACE, "capi-freeze", "lib", "libmaned_c.dylib"),
    os.path.join(_WORKSPACE, "capi-freeze", "lib", "libmaned_c.so"),
)


def _install_default_lib():
    if os.environ.get("MANEDPY_LIB"):
        return
    for candidate in _DEFAULT_LIBS:
        if os.path.exists(candidate):
            os.environ["MANEDPY_LIB"] = candidate
            return


_install_default_lib()


@pytest.fixture(scope="session")
def lib_path():
    path = os.environ.get("MANEDPY_LIB")
    if not path or not os.path.exists(path):
        pytest.skip("set $MANEDPY_LIB to a libmaned_c from a maned-capi-* tarball")
    return path


@pytest.fixture(scope="session")
def capi_dir(lib_path):
    """The unpacked maned-capi-* tree: <capi>/lib/libmaned_c.*."""
    return os.path.dirname(os.path.dirname(lib_path))


@pytest.fixture(scope="session")
def conformance_dir(capi_dir):
    path = os.path.join(capi_dir, "conformance")
    if not os.path.isdir(path):
        pytest.skip("no conformance/ corpus beside %s" % capi_dir)
    return path


@pytest.fixture(scope="session")
def maned_serve(capi_dir):
    """The maned-serve binary, for the REST-parity gate."""
    override = os.environ.get("MANED_SERVE")
    candidates = [override] if override else []
    candidates.append(os.path.join(os.path.dirname(capi_dir), "maned-serve"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    pytest.skip("no maned-serve binary; set $MANED_SERVE for the REST-parity gate")


def load_cases(conformance_dir):
    """Every <case>.mnd + .request.json + .expect.json triple, sorted."""
    cases = []
    for entry in sorted(os.listdir(conformance_dir)):
        if not entry.endswith(".request.json"):
            continue
        name = entry[: -len(".request.json")]
        script = os.path.join(conformance_dir, name + ".mnd")
        expect = os.path.join(conformance_dir, name + ".expect.json")
        if not (os.path.exists(script) and os.path.exists(expect)):
            continue
        with open(os.path.join(conformance_dir, entry), encoding="utf-8") as fh:
            request = json.load(fh)
        with open(expect, encoding="utf-8") as fh:
            expected = json.load(fh)
        cases.append((name, script, request, expected))
    return cases


def flags_of(request):
    """The request's optional flag names -> maned.load keyword arguments."""
    return {name: True for name in request.get("flags", [])}


def free_port():
    """A port nothing is listening on right now.

    maned-serve does not implement --port 0 (it binds the number it is
    given), so the port has to be chosen here. Inherently racy; the retry in
    serve_process() covers the loser of that race.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ServeProcess:
    """A maned-serve subprocess, ready to accept when __enter__ returns."""

    def __init__(self, binary, script, max_requests):
        self.binary = binary
        self.script = script
        self.max_requests = max_requests
        self.port = None
        self.process = None

    def __enter__(self):
        last = None
        for _ in range(5):
            self.port = free_port()
            self.process = subprocess.Popen(
                [
                    self.binary,
                    self.script,
                    "--port",
                    str(self.port),
                    "--max-requests",
                    str(self.max_requests),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if self._wait_ready():
                return self
            last = self._drain()
            self._kill()
        raise RuntimeError("maned-serve never came up: %s" % last)

    def __exit__(self, *exc):
        self._kill()
        return False

    def _wait_ready(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                return False
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.2):
                    return True
            except OSError:
                time.sleep(0.02)
        return False

    def _drain(self):
        try:
            out, _ = self.process.communicate(timeout=1)
            return (out or b"").decode("utf-8", "replace")
        except Exception:
            return ""

    def _kill(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        self.process = None
