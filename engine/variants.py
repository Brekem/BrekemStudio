"""Master VARIANTS: the same song mastered in several styles, to pick by ear.
Usage:  variants.py "<TAG>" "<outdir>" [ids]   (stems must exist at %BREKEM_STEMS%/<TAG>/)
        ids = comma list of: cd,clarity,espacial,punch,warm,club,streaming,signature (default all)
Writes: <outdir>/<NN STYLE>.wav + .mp3, _VARIANTS.txt, COMPARE.html (A/B player)

Every style starts from the separated stems (vocal / drums / bass / rest), so a
style can do what one EQ on the finished mix can't: push the drums without the
vocal, widen the music without the vocal or the bass, add space to the vocal only.

  01 CD MASTER        balanced, like a classic CD master (LANDR 'Balanced')
  02 CLARITY          vocal +1 dB, less mud, more presence and air ('Open')
  03 ESPACIAL         wide music, deeper vocal plate, mono-safe low end
  04 PUNCH            drums forward with extra attack, tight bass, loud
  05 WARM             tape saturation, low-mid body, softer top ('Warm')
  06 CLUB             big low end, loudest (-7.5 LUFS)
  07 STREAMING -14    platform loudness, full dynamics, gentle limiting
  08 BREKEM SIGNATURE the house style: clarity + punch + width, plus two layers
                      made from the song itself: a HARMONIC FILL (a soft pad that
                      follows the song's own chords, only where there's harmony,
                      tucked under the vocal) and a SHIMMER (octave-up reverb of
                      the music) that open and fill the space.
Prints: DONE variants
"""
import os, sys, json, numpy as np, soundfile as sf, scipy.signal as sig
SP = os.environ.get("BREKEM_HOME") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
import stems as ST
from acap_pro import (SR, load, rms, deepfilter, debreath_at, deplosive_gated, dereverb, eq_sub,
                      vbus, glue, polish, bq_shelf, bq_peak, plate, loud_to, ebur, bands_arr,
                      run, WORK, STEMS)
from pedalboard import Pedalboard, Reverb, PitchShift, HighpassFilter, LowpassFilter

TAG = sys.argv[1]
OUT = sys.argv[2]
PICK = [s for s in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if s]
os.makedirs(OUT, exist_ok=True)
SD = os.path.join(STEMS, TAG)


def L(m): print(m, flush=True)


def w(p, a):
    sf.write(p, np.asarray(a, np.float32), SR, subtype="FLOAT"); return p


# ------------------------------------------------------------------ building blocks
def transient(x, boost_db, band_hi=None):
    """attack boost (fast vs slow envelope). band_hi=None -> full band."""
    src = x if band_hi is None else sig.sosfilt(sig.butter(3, band_hi / (SR / 2), btype="low", output="sos"), x, axis=0)
    m = np.abs(src).mean(1)
    fa = np.exp(-1.0 / (0.003 * SR)); sa = np.exp(-1.0 / (0.060 * SR))
    ef = np.sqrt(sig.lfilter([1 - fa], [1, -fa], m ** 2) + 1e-12)
    es = np.sqrt(sig.lfilter([1 - sa], [1, -sa], m ** 2) + 1e-12)
    d = 20 * np.log10(ef + 1e-9) - 20 * np.log10(es + 1e-9)
    g = 1.0 + np.clip(d, 0, 8.0) / 8.0 * (10 ** (boost_db / 20) - 1.0)
    a = np.exp(-1.0 / (0.004 * SR)); g = sig.lfilter([1 - a], [1, -a], g)
    return x + src * (g[:, None] - 1.0)


def tape(x, wet):
    if wet <= 0: return x
    d = x * 0.9
    y = (1 - wet) * x + wet * np.tanh(d + 0.1 * d * d) / np.tanh(1.1)
    return y * (rms(x) / rms(y))


def widen(x, amount, above=300.0):
    if abs(amount - 1.0) < 1e-3: return x
    mid = (x[:, 0] + x[:, 1]) * 0.5; side = (x[:, 0] - x[:, 1]) * 0.5
    hi = sig.sosfiltfilt(sig.butter(2, above / (SR / 2), btype="high", output="sos"), side)
    side = side + hi * (amount - 1.0)
    return np.stack([mid + side, mid - side], 1)


def duck(x, key, depth_db):
    """lower x by up to depth_db while key (0..1) is up."""
    return x * (10 ** (depth_db * key / 20.0))[:, None]


def music_env(x, win=0.4):
    """0..1 slow loudness envelope of the song (so added layers swell and fade with it)."""
    m = x.mean(1); k = int(win * SR)
    e = np.sqrt(np.convolve(m ** 2, np.ones(k) / k, mode="same") + 1e-12)
    edb = 20 * np.log10(e + 1e-9); ref = np.percentile(edb, 90)
    return np.clip((edb - (ref - 30.0)) / 30.0, 0.0, 1.0) ** 1.5


# ------------------------------------------------------------------ AI-ish layers from the song
def harmonic_fill(harm, n, vact):
    """a soft pad that plays the song's OWN chords: chroma of the harmonic stems every
    0.25 s -> the 3 strongest pitch classes (only when the frame really is tonal) ->
    detuned sine voices in two octaves, panned wide, big reverb. It swells with the
    music, fades where there's no harmony (drum breaks) and sits lower under the vocal."""
    import librosa
    y = sig.resample_poly(harm.mean(1), 1, 2)                     # 24 kHz is plenty for chroma
    hop = 6000                                                     # 0.25 s
    C = librosa.feature.chroma_stft(y=y, sr=SR // 2, n_fft=8192, hop_length=hop)
    C = sig.medfilt(C, (1, 5))                                     # no chord flicker
    tonal = np.clip((C.max(0) / (C.mean(0) + 1e-9) - 1.6) / 1.0, 0, 1)
    nfr = C.shape[1]
    t = np.arange(n) / SR
    tf = np.arange(nfr) * hop / (SR // 2)
    pad = np.zeros((n, 2))
    base = 130.8128 * 2 ** (np.arange(12) / 12.0)                  # C3..B3
    for pc in range(12):
        wgt = np.zeros(nfr)
        for i in range(nfr):
            top = np.argsort(C[:, i])[-3:]
            if pc in top:
                wgt[i] = C[pc, i] * tonal[i]
        if wgt.max() < 1e-3:
            continue
        a = np.interp(t, tf, wgt)
        a = sig.sosfiltfilt(sig.butter(2, 3.0 / (SR / 2), output="sos"), a)   # 3 Hz: smooth chord changes
        for octv, lvl in ((1.0, 1.0), (2.0, 0.45)):
            f = base[pc] * octv
            l = np.sin(2 * np.pi * f * 2 ** (-7 / 1200) * t)          # detune -7 / +7 cents, L / R
            r = np.sin(2 * np.pi * f * 2 ** (+7 / 1200) * t + 1.3)
            pad[:, 0] += a * lvl * l; pad[:, 1] += a * lvl * r
    if not np.any(pad):
        return pad
    pad = Pedalboard([HighpassFilter(160), LowpassFilter(3200),
                      Reverb(room_size=0.85, damping=0.5, wet_level=0.6, dry_level=0.5, width=1.0)]
                     )(pad.T.astype(np.float32), SR).T.astype(np.float64)[:n]
    return duck(pad, vact, -6.0)


def shimmer(music, vact):
    """octave-up, long reverb of the music only (no vocal, no drums): opens the top and
    fills the gaps. Ducked under the vocal."""
    y = Pedalboard([HighpassFilter(400), PitchShift(semitones=12),
                    Reverb(room_size=0.9, damping=0.35, wet_level=1.0, dry_level=0.0, width=1.0),
                    HighpassFilter(1800), LowpassFilter(12000)]
                   )(music.T.astype(np.float32), SR).T.astype(np.float64)[:len(music)]
    return duck(y, vact, -8.0)


def set_rel(layer, ref, db):
    """scale layer so its RMS sits db under ref's RMS."""
    r = rms(layer)
    return layer * (rms(ref) * 10 ** (db / 20) / r) if r > 0 else layer


# ------------------------------------------------------------------ stems
if not (os.path.exists(os.path.join(SD, "vocals.flac")) and os.path.exists(os.path.join(SD, "no_vocals.flac"))):
    L("NO STEMS -> abort"); sys.exit(1)
raw = load(os.path.join(SD, "vocals.flac")); n = len(raw); r0 = rms(raw)
nov = ST._fit(load(os.path.join(SD, "no_vocals.flac")), n)
vact = ST.vocal_activity(raw, nov)
cache = os.path.join(SD, "vocals_proc.wav")
if os.path.exists(cache):
    vox = ST._fit(load(cache), n); L("vocal: cached clean chain")
else:
    vox = deepfilter(raw, n)
    vox, _ = debreath_at(vox, n, at_db=-9.0)
    vox, _ = deplosive_gated(vox, n)
    vox = vbus(eq_sub(dereverb(vox)))
    sf.write(cache, vox.astype(np.float32), SR, subtype="FLOAT")
    L("vocal: clean chain done")
vox = ST.gate(vox * (r0 / rms(vox)) * 10 ** (1.0 / 20), vact)
bleed = ST.bleed(raw, vact)
parts = {k: ST._fit(load(p), n) for k, p in ST.inst_stems(TAG).items()}
if "drums" in parts:
    drums = parts.pop("drums"); bass = parts.pop("bass", np.zeros((n, 2)))
    rest = sum(parts.values()) if parts else np.zeros((n, 2))
else:                                                            # old 2-stem cache
    drums = np.zeros((n, 2)); bass = np.zeros((n, 2)); rest = nov
L(f"stems: vocal + {', '.join(ST.inst_stems(TAG)) or 'no_vocals'}")

# ------------------------------------------------------------------ styles
D = lambda db: 10 ** (db / 20.0)
BASE = dict(vox=0.0, drums=0.0, bass=0.0, rest=0.0, punch=3.0, kick_duck=0.0, carve=-2.0,
            low=1.0, mud=0.0, pres=0.0, air=0.5, width=1.05, verb=0.6, tape=0.0,
            lufs=-9.5, drive=0.88, fill=None, shim=None)
STYLES = [
    ("01 CD MASTER",        dict()),
    ("02 CLARITY",          dict(vox=1.0, carve=-3.0, mud=-2.0, pres=1.5, air=2.0, lufs=-10.0)),
    ("03 ESPACIAL",         dict(width=1.35, verb=0.8, air=1.0, rest=0.5, lufs=-10.0)),
    ("04 PUNCH",            dict(drums=1.5, punch=5.0, kick_duck=-2.5, low=1.5, lufs=-8.5, drive=0.86)),
    ("05 WARM",             dict(tape=0.30, low=1.5, mud=1.0, pres=-0.5, air=-1.5, width=1.0)),
    ("06 CLUB",             dict(bass=1.5, drums=0.5, low=2.5, punch=4.0, lufs=-7.5, drive=0.84)),
    ("07 STREAMING -14",    dict(lufs=-14.0, drive=0.95, punch=2.5)),
    ("08 BREKEM SIGNATURE", dict(vox=0.8, drums=0.8, punch=4.0, kick_duck=-1.5, carve=-3.0, mud=-1.5,
                                 pres=1.0, air=1.5, width=1.2, low=1.5, lufs=-9.0, fill=-21.0, shim=-24.0)),
]

IDS = ["cd", "clarity", "espacial", "punch", "warm", "club", "streaming", "signature"]
if PICK:
    STYLES = [st for i, st in zip(IDS, STYLES) if i in PICK]
if not STYLES:
    L("no style picked -> nothing to do"); L("DONE variants"); sys.exit(0)

layers = {}
def get_layer(name):
    if name not in layers:
        if name == "fill":
            L("  harmonic fill: reading the song's chords...")
            layers[name] = harmonic_fill(rest + bass, n, vact)
        else:
            L("  shimmer: octave-up space from the music...")
            layers[name] = shimmer(rest, vact)
    return layers[name]

rows = []
GREF = ST.guard_ref(raw + nov) if ST.guard_enabled() else None   # the original song's band ranges
kick = ST.kick_env(drums) if np.any(drums) else None
bass_base = ST.dry_bass(bass, kick) if ST.dry_enabled() else ST.mono_low(bass)
for name, over in STYLES:
    p = dict(BASE, **over)
    L(f"=== {name}")
    dr = transient(drums, p["punch"]) * D(p["drums"])
    bs = bass_base * D(p["bass"])
    if p["kick_duck"] and kick is not None:
        bs = duck(bs, kick, p["kick_duck"])                      # bass steps aside for the kick
    rs = widen(ST.carve(rest, vact, depth_db=p["carve"]), p["width"]) * D(p["rest"])
    vx = vox * D(p["vox"])
    vx = p["verb"] * plate(vx) + (1 - p["verb"]) * vx
    mix = vx + bleed + dr + bs + rs
    if p["fill"] is not None:
        mix = mix + set_rel(get_layer("fill"), mix, p["fill"]) * music_env(rest + bass)[:, None]
    if p["shim"] is not None:
        mix = mix + set_rel(get_layer("shim"), mix, p["shim"]) * music_env(rest)[:, None]
    mix = glue(mix)
    mix = polish(mix)
    if p["mud"]: mix = bq_peak(mix, 300.0, p["mud"], 0.9)
    if p["low"]: mix = bq_shelf(mix, 75.0, p["low"], False)
    if p["pres"]: mix = bq_peak(mix, 3500.0, p["pres"], 0.7)
    if p["air"]: mix = bq_shelf(mix, 11000.0, p["air"], True)
    mix = tape(mix, p["tape"])
    if GREF is not None:                    # style keeps its colour (+-4 dB per band), never leaves the song's range
        mix = ST.guard(mix, GREF, tone_tol_db=4.0, log=lambda m: L("  " + m))
    pk = np.max(np.abs(mix)); mix = mix * (0.995 / pk) if pk > 0.995 else mix
    wav = os.path.join(OUT, name + ".wav")
    tmp = w(os.path.join(WORK, "vr_in.wav"), mix)
    loud_to(tmp, wav, Itgt=p["lufs"], tp_lin=0.871, drive=p["drive"])
    run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "libmp3lame", "-b:a", "320k",
         "-id3v2_version", "3", os.path.join(OUT, name + ".mp3")])
    I, Lr, T = ebur(wav); lo, pr, air, corr = bands_arr(load(wav))
    rows.append((name, I, Lr, T, lo, pr, air, corr))
    L(f"  I={I:6.1f} LUFS  LRA={Lr:4.1f}  TP={T:5.1f}  low{lo:+.1f} pres{pr:+.1f} air{air:+.1f} corr{corr:+.2f}")
try: os.remove(os.path.join(WORK, "vr_in.wav"))
except Exception: pass

with open(os.path.join(OUT, "_VARIANTS.txt"), "w", encoding="utf-8") as f:
    f.write(f"{TAG}\n\n{'style':22} {'LUFS':>6} {'LRA':>5} {'TP':>6} {'low':>6} {'pres':>6} {'air':>6} {'corr':>5}\n")
    for r in rows:
        f.write(f"{r[0]:22} {r[1]:6.1f} {r[2]:5.1f} {r[3]:6.1f} {r[4]:+6.1f} {r[5]:+6.1f} {r[6]:+6.1f} {r[7]:+5.2f}\n")
    f.write("\nLUFS = loudness, LRA = dynamics (higher = more alive), TP = true peak,\n"
            "low/pres/air = dB vs 200-2k, corr = stereo (1.0 = mono, lower = wider).\n")

# A/B player: one timeline, switch style without losing the position
items = "".join(f'<button data-i="{i}">{r[0][3:]}<small>{r[1]:.1f} LUFS</small></button>' for i, r in enumerate(rows))
srcs = json.dumps([r[0] + ".mp3" for r in rows])
html = f"""<!doctype html><html><head><meta charset="utf-8"><title>BREKEM · {TAG}</title>
<style>body{{font-family:Segoe UI,sans-serif;background:#0f1113;color:#d7dde3;max-width:760px;margin:30px auto;padding:0 16px}}
h1{{font-size:20px}}button{{display:block;width:100%;text-align:left;margin:6px 0;padding:12px;border:1px solid #333;
background:#171a1d;color:#d7dde3;border-radius:8px;font-size:15px;cursor:pointer}}button small{{float:right;color:#7b8794}}
button.on{{border-color:#e0b04a;background:#221d10}}audio{{width:100%;margin:14px 0}}p{{color:#7b8794;font-size:13px}}</style></head>
<body><h1>BREKEM STUDIO — {TAG}</h1><p>Click a style while it plays: it switches at the same second, so you
compare the masters on the same part of the song. Keys 1-{len(rows)} work too.</p>
<audio id="a" controls></audio>{items}
<script>const S={srcs};const a=document.getElementById('a');const B=[...document.querySelectorAll('button')];
function pick(i){{const t=a.currentTime,p=!a.paused;a.src=S[i];a.addEventListener('loadedmetadata',()=>{{a.currentTime=t;if(p)a.play();}},{{once:true}});
B.forEach((b,j)=>b.classList.toggle('on',j==i));}}
B.forEach((b,i)=>b.onclick=()=>pick(i));document.onkeydown=e=>{{const i=+e.key-1;if(i>=0&&i<S.length)pick(i);}};pick(0);</script>
</body></html>"""
with open(os.path.join(OUT, "COMPARE.html"), "w", encoding="utf-8") as f:
    f.write(html)
L(f"=> {len(rows)} styles in {OUT}  (open COMPARE.html to A/B them)")
L("DONE variants")
