#!/usr/bin/env python3
"""Routing from inside your process: the flow carries @device(vm1) with
host = "local", so this run spawns the local Bark VM — the worker's REAL
compute core — exactly as `maned-run` would.

Requires the maned toolchain installed (it provides `bark-vm` on PATH):
    curl -fsSL https://fabianodicheti.github.io/maned/install.sh | sh

    python examples/routed.py

Expected output:
    r = [[19, 22], [43, 50]]
"""

import os

from manedpy import maned as mnd

here = os.path.dirname(os.path.abspath(__file__))
script = mnd.load(os.path.join(here, "routed.mnd"))
result = script.run({})
print("r =", result.outputs["r"])
