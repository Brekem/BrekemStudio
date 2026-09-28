"""Tuned version of a whole song (Styles & Tune tab, pitch correction ticked).
Usage:  retune.py "<TAG>" "<outdir>"   (stems must exist at %BREKEM_STEMS%/<TAG>/)
Writes: <outdir>/TUNED MIX.wav   the song with the vocal retuned, nothing else changed
        <outdir>/ACAPELLA TUNED.wav   the retuned vocal alone (bleed gated out)
Prints: DONE retune
"""
import os, sys, numpy as np, soundfile as sf
sys.path.insert(0, os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__)))
import stems as ST
import tune as TU

TAG, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
sd = ST.stem_dir(TAG)
raw = ST.load(os.path.join(sd, "vocals.flac"))
beat = ST._fit(ST.load(os.path.join(sd, "no_vocals.flac")), len(raw))
act = ST.vocal_activity(raw, beat)
tuned = TU.tuned_vocal(sd, raw, beat, act, log=lambda m: print(m, flush=True))
for name, y in (("TUNED MIX", tuned + beat), ("ACAPELLA TUNED", ST.gate(tuned, act))):
    pk = float(np.max(np.abs(y)))
    if pk > 0.999:
        y = y * (0.999 / pk)
    sf.write(os.path.join(OUT, name + ".wav"), y.astype(np.float32), ST.SR, subtype="PCM_24")
    print(f"  {name}.wav", flush=True)
print("DONE retune", flush=True)
