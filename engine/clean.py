"""AI clean pass on a separated song: denoise/dereverb (DeepFilterNet) + de-breath
+ de-plosive on the vocal, then rebuild a clean mix.
Usage:  clean.py "<TAG>"   (stems must already exist at %BREKEM_STEMS%/<TAG>/)
Writes into that stems dir:  vocals_clean.flac   mix_clean.wav
Prints: DONE clean
"""
import os, sys, numpy as np, soundfile as sf
SP = os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
from acap_pro import (SR, load, rms, deepfilter, debreath_at, deplosive_gated,
                      dereverb, eq_sub, vbus, glue, STEMS)
import stems as ST

TAG = sys.argv[1]
sd = os.path.join(STEMS, TAG)
vc = os.path.join(sd, "vocals.flac")
ic = os.path.join(sd, "no_vocals.flac")
if not (os.path.exists(vc) and os.path.exists(ic)):
    print("NO STEMS -> abort"); sys.exit(1)

voc = load(vc); n = len(voc); r0 = rms(voc)
raw = voc.copy()
act = ST.vocal_activity(raw, load(ic))                # where the vocal stem really holds a vocal
voc = deepfilter(voc, n)                      # noise / static / room
voc, nb = debreath_at(voc, n, at_db=-9.0)     # breaths
voc, npl = deplosive_gated(voc, n)            # plosives
voc = dereverb(voc)                           # tail / reverb
voc = eq_sub(voc)                             # subtractive EQ (HPF + nasal/harsh dips)
voc = vbus(voc)                               # vocal bus: de-ess + comp + presence/air
rr = rms(voc); voc = voc * (r0 / rr) if rr > 0 else voc
voc = ST.gate(voc, act)                       # bleed out of the acapella between phrases / in the tail
print(f"clean: breath={nb} plosives={npl}", flush=True)

sf.write(os.path.join(sd, "vocals_clean.flac"),
         voc.astype(np.float32), SR, subtype="PCM_24")

inst = load(ic)
m = min(len(voc), len(inst))
mix = glue(voc[:m] + ST.bleed(raw, act)[:m] + inst[:m])   # untouched stem where nobody sings
pk = np.max(np.abs(mix))
if pk > 0.99:
    mix = mix * (0.99 / pk)
sf.write(os.path.join(sd, "mix_clean.wav"),
         mix.astype(np.float32), SR, subtype="PCM_24")
print("DONE clean", flush=True)
