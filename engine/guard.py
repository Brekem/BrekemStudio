"""Band guard for a finished file (Distribute tabs).
Usage:  guard.py "<in>" "<out.wav>"
Keeps every band's 10 ms peaks inside the file's own range (see stems.guard), so a
single band can't slam the final limiter. The tone is left as it is (ref = itself).
"""
import os, sys, numpy as np, soundfile as sf
sys.path.insert(0, os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__)))
import stems as ST

x = ST.load(sys.argv[1])
y = ST.guard(x, x, log=lambda m: print(m, flush=True))
sf.write(sys.argv[2], y.astype(np.float32), ST.SR, subtype="FLOAT")
print("DONE guard", flush=True)
