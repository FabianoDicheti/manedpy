#!/usr/bin/env python3
"""Exact decimals: quantized integers in, decoded decimals out.

    python examples/decimals.py

`quantres=2` makes the integer 1999 mean 19.99. Integer division
truncates — deliberately and identically on every machine — so 55.48/3
lands on 18.49 exactly, with nothing float-shaped in between.

Expected output:
    total = [55.48]
    mean  = [18.49]
"""

import os

from manedpy import maned as mnd

here = os.path.dirname(os.path.abspath(__file__))
script = mnd.load(os.path.join(here, "decimal.mnd"))
result = script.run({})
print("total =", result.outputs["total"])
print("mean  =", result.outputs["mean"])
