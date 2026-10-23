"""Finishing pass for a finished file (Distribute tabs), before the final limiter.
Usage:  guard.py "<in>" "<out.wav>" [MASTER|INSTRUMENTAL|ACAPELLA]
  exciter (BREKEM_EXCITER=1, MASTER / INSTRUMENTAL only): new harmonics, see exciter.py
  guard   (BREKEM_GUARD=1): every band's 10 ms peaks stay inside the file's own range
          (see stems.guard), so a single band can't slam the final limiter. The tone is
          left as it is (ref = the file itself).
"""
import os, sys, numpy as np, soundfile as sf
sys.path.insert(0, os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__)))
import stems as ST
import exciter as EX

say = lambda m: print(m, flush=True)
kind = sys.argv[3] if len(sys.argv) > 3 else "MASTER"
x = ST.load(sys.argv[1])
y = x
if EX.enabled() and kind != "ACAPELLA":
    y = EX.excite(y, log=say)
if ST.guard_enabled():
    y = ST.guard(y, x, log=say)
sf.write(sys.argv[2], y.astype(np.float32), ST.SR, subtype="FLOAT")
print("DONE guard", flush=True)
