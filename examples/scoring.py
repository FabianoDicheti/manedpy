#!/usr/bin/env python3
"""The quickstart example: run examples/scoring.mnd in-process.

    pip install manedpy
    python examples/scoring.py

Expected output:
    y = [[2, 4], [0, 2]]
    engine 0.4.0
"""

import os

from manedpy import maned as mnd

here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)  # the scripts' own csv() sources resolve against the CWD
script = mnd.load(os.path.join(here, "scoring.mnd"))
result = script.run({"x": [[2, 0], [0, 2]]})
print("y =", result.outputs["y"])
print("engine", mnd.lib_version)
