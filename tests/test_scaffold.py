"""Scaffold sanity: the package imports and every entry point refuses loudly."""

import pytest

from manedpy import maned as mnd
from manedpy.errors import ManedScriptNotFound


def test_facade_shape():
    assert hasattr(mnd, "load")
    assert hasattr(mnd, "io")
    assert hasattr(mnd, "set_kernel_threads")
    assert mnd.search_path == []


def test_everything_refuses():
    with pytest.raises(NotImplementedError):
        mnd.load("scoring.mnd")
    with pytest.raises(ManedScriptNotFound):
        mnd.io.scoring
    with pytest.raises(AttributeError):
        mnd.io._ipython_canary_method_should_not_exist_
