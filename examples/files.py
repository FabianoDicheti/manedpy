#!/usr/bin/env python3
"""File routes: send file BYTES in, get output file bytes back — the
in-process twin of `curl -F data=@data.csv http://.../run`.

    python examples/files.py

The script's `in::data = csv("data.csv")` is a file-sourced input, so a
multipart request can override it BY NAME; the reply carries every `out::`
as bytes, keyed by output name.

Expected output:
    outputs: ['g']
    8.75,3.50
    3.50,5.00
"""

import os

from manedpy import maned as mnd

here = os.path.dirname(os.path.abspath(__file__))
os.chdir(here)  # the scripts' own csv() sources resolve against the CWD
script = mnd.load(os.path.join(here, "pipeline.mnd"))

with open(os.path.join(here, "data.csv"), "rb") as f:
    csv_bytes = f.read()

out = script.run_files(data=csv_bytes)
print("outputs:", list(out))
print(out["g"].decode().strip())
