"""Matchering of one premaster against one reference (track_v2 runs one per reference,
all at the same time, so every CPU core works instead of one reference after another).
Usage:  mg_one.py "<premaster.wav>" "<reference>" "<out.wav>"
Exit 0 and <out.wav> written on success."""
import sys, warnings
warnings.filterwarnings("ignore")
import matchering as mg
try:
    mg.log(info_handler=lambda *a, **k: None, warning_handler=lambda *a, **k: None)
except Exception:
    pass

target, ref, out = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    mg.process(target=target, reference=ref, results=[mg.pcm24(out)])
except Exception as e:
    print(f"FAIL: {e}", flush=True)
    sys.exit(1)
