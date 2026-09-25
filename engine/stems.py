"""Multi-stem helpers shared by the master engines (track_v2, noref, clean).

prep.py now separates every song into as many stems as the chosen Demucs model
gives (vocals / drums / bass / other, + guitar / piano with htdemucs_6s) and keeps
no_vocals.flac (= sum of the non-vocal stems) for older callers. This module:

  * instrumental(tag, shaper, carve_mask)  rebuilds the beat stem by stem:
        drums  -> the caller's transient shaper (punch on the kick only)
        bass   -> dry_bass: centred, tail tightened, steady, out of the kick's way
                  (BREKEM_DRY_BASS=0 -> only the low end folded to mono)
        rest   -> optional vocal-keyed dip at 1.8-5 kHz so the vocal sits in front
    falls back to shaper(no_vocals) for old 2-stem caches.
  * vocal_activity(voc, inst)  0..1 mask of where the vocal stem holds a real vocal.
  * gate / bleed  use that mask so the processed vocal is only used where someone
    is singing. Everywhere else (intro, beat breaks, the song's tail) the mix gets
    the untouched separation back, so the separation bleed is never de-noised /
    de-reverbed / compressed into audible artifacts ("interference" at the end).
"""
import os
import json
import numpy as np
import soundfile as sf
import scipy.signal as sig
from scipy.ndimage import maximum_filter1d

SR = 48000
STEMS = os.environ.get("BREKEM_STEMS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stems")
INST_STEMS = ("drums", "bass", "other", "guitar", "piano")


def load(p):
    x, s = sf.read(p, dtype="float64", always_2d=True)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, 1)
    if s != SR:
        g = np.gcd(int(s), SR)
        x = sig.resample_poly(x, SR // g, s // g, axis=0)
    return x


def stem_dir(tag):
    return os.path.join(STEMS, tag)


def info(tag):
    try:
        with open(os.path.join(stem_dir(tag), "stems.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def inst_stems(tag):
    """{name: path} of the separated non-vocal stems present for this song."""
    sd = stem_dir(tag)
    out = {}
    for k in INST_STEMS:
        p = os.path.join(sd, k + ".flac")
        if os.path.exists(p):
            out[k] = p
    return out


# ------------------------------------------------------------------ vocal activity
def _frames_db(x, hop, nfr, win_fr=5):
    mono = x.mean(1)
    fr = mono[:nfr * hop].reshape(nfr, hop)
    p = np.convolve(np.mean(fr ** 2, axis=1), np.ones(win_fr) / win_fr, mode="same")
    return 10 * np.log10(p + 1e-12)


def vocal_activity(voc, inst=None, ratio_knee=(-24.0, -16.0), floor_db=-50.0,
                   hold_s=0.35, rel_s=0.25, atk_s=0.01):
    """0..1 per sample. 1 = the vocal stem holds a real vocal, 0 = only bleed/silence.
    Separation bleed is always far below the beat it leaks from, a real vocal is not:
    so the test is the vocal-to-beat ratio (50 ms windows) with a soft knee between
    ratio_knee[0] and [1] dB, plus an absolute floor (floor_db under the loud vocal)
    for silence. Without the beat it falls back to level only. A hold (both sides)
    keeps word onsets, word ends and short gaps open, and smooth attack/release keeps
    the blend from clicking."""
    n = len(voc)
    hop = int(0.010 * SR)
    nfr = max(1, n // hop)
    vdb = _frames_db(voc, hop, nfr)
    ref = np.percentile(vdb, 95)
    if inst is not None:
        idb = _frames_db(_fit(inst, n), hop, nfr)
        m = np.clip((vdb - idb - ratio_knee[0]) / (ratio_knee[1] - ratio_knee[0]), 0.0, 1.0)
        m *= np.clip((vdb - (ref + floor_db)) / 6.0, 0.0, 1.0)
    else:
        m = np.clip((vdb - (ref - 38.0)) / 10.0, 0.0, 1.0)
    k = max(1, int(hold_s / 0.010))
    m = maximum_filter1d(m, size=2 * k + 1, mode="nearest")
    aA = np.exp(-1.0 / (atk_s / 0.010)); aR = np.exp(-1.0 / (rel_s / 0.010))
    out = np.zeros_like(m); prev = 0.0
    for i, v in enumerate(m):
        a = aA if v > prev else aR
        prev = a * prev + (1 - a) * v
        out[i] = prev
    t = np.arange(nfr) * hop + hop // 2
    return np.clip(np.interp(np.arange(n), t, out), 0.0, 1.0)


def _fit(a, n):
    if len(a) >= n:
        return a[:n]
    return np.concatenate([a, np.zeros((n - len(a),) + a.shape[1:])], axis=0)


def gate(proc, mask, floor_db=-60.0):
    """the processed vocal only where someone sings (bleed gated out between
    phrases and in the tail). Apply reverb AFTER this so real tails survive."""
    fl = 10 ** (floor_db / 20)
    g = fl + (1.0 - fl) * mask
    return _fit(proc, len(mask)) * g[:, None]


def bleed(raw, mask):
    """the untouched vocal stem where nobody sings: added back to the mix so vocal +
    beat rebuild the original there instead of a processed, artifacty version."""
    return _fit(raw, len(mask)) * (1.0 - mask)[:, None]


# ------------------------------------------------------------------ per-stem beat
def mono_low(x, f=120.0):
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    side = sig.sosfiltfilt(sig.butter(2, f / (SR / 2), btype="high", output="sos"), side)
    return np.stack([mid + side, mid - side], 1)


def kick_env(drums):
    """0..1 envelope of the kick (drums below 120 Hz, 10 ms)."""
    k = sig.sosfilt(sig.butter(4, 120 / (SR / 2), output="sos"), drums.mean(1))
    w = int(0.01 * SR)
    e = np.sqrt(np.convolve(k ** 2, np.ones(w) / w, mode="same"))
    return np.clip(e / (np.percentile(e, 99) + 1e-9), 0, 1)


def dry_bass(x, kick=None, tail_db=-8.0, width_hi=0.4):
    """bass/808 centred and dry:
      1. centred - everything under 250 Hz folded to mono, the side above kept at
         width_hi (a bit of harmonic width, never in the sub)
      2. no rumble under 28 Hz
      3. dry - a decay expander: when a note's level falls 8+ dB under its own recent
         peak (the tail, the room, the reverb), it is pulled down by up to tail_db,
         so each note stops cleanly instead of ringing into the next
      4. steady - ~4:1 compression on the loud part so every note hits the same
      5. out of the kick's way - ducks up to 2 dB on each kick hit (if drums given)"""
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    side = sig.sosfiltfilt(sig.butter(2, 250.0 / (SR / 2), btype="high", output="sos"), side) * width_hi
    y = np.stack([mid + side, mid - side], 1)
    y = sig.sosfiltfilt(sig.butter(2, 28.0 / (SR / 2), btype="high", output="sos"), y, axis=0)
    m = np.abs(y).mean(1)
    a5 = np.exp(-1.0 / (0.005 * SR))
    env = np.sqrt(sig.lfilter([1 - a5], [1, -a5], m ** 2) + 1e-12)
    edb = 20 * np.log10(env + 1e-9)
    # recent peak: instant rise, ~0.35 s fall (block-wise to keep it fast)
    hop = int(0.005 * SR); nb = len(edb) // hop
    blk = edb[:nb * hop].reshape(nb, hop).max(1)
    pk = np.empty(nb); cur = -200.0; fall = 0.005 / 0.35 * 20.0
    for i, v in enumerate(blk):
        cur = v if v > cur else cur - fall
        pk[i] = cur
    under = pk - blk                                   # dB under the note's peak
    g = np.clip((under - 8.0) / 12.0, 0.0, 1.0) * tail_db
    floor = np.percentile(blk, 99) - 60.0              # don't expand true silence twice
    g[blk < floor] = tail_db
    g = sig.sosfiltfilt(sig.butter(1, 12.0 / (1.0 / 0.005 / 2), output="sos"), g)
    gain_db = np.interp(np.arange(len(edb)), np.arange(nb) * hop + hop // 2, g)
    thr = np.percentile(edb, 80)
    comp = -np.maximum(edb - thr, 0.0) * (1 - 1 / 4.0)
    ac, rc = np.exp(-1.0 / (0.02 * SR)), np.exp(-1.0 / (0.12 * SR))
    cs = np.zeros_like(comp); prev = 0.0
    for i in range(0, len(comp), hop):                 # attack/release on 5 ms blocks
        v = comp[i]; c = ac if v < prev else rc
        prev = c ** hop * prev + (1 - c ** hop) * v; cs[i:i + hop] = prev
    act = edb > thr - 20                               # makeup: keep the bass as loud as it was
    gain_db = gain_db + cs - (np.median(cs[act]) if np.any(act) else 0.0)
    if kick is not None:
        gain_db = gain_db + _fit(kick[:, None], len(y))[:, 0] * -2.0
    y = y * (10 ** (gain_db / 20.0))[:, None]
    ra = np.sqrt(np.mean(x[act] ** 2)) if np.any(act) else 0.0     # same level on the notes as before
    rb = np.sqrt(np.mean(y[act] ** 2)) if np.any(act) else 0.0
    return y * (ra / rb) if rb > 0 else y


def dry_enabled():
    return os.environ.get("BREKEM_DRY_BASS", "1") != "0"


def carve(x, mask, lo=1800.0, hi=5000.0, depth_db=-2.0):
    """make room for the vocal: dip the vocal-presence band of the beat by up to
    depth_db while the vocal is active (mask 1), untouched when it is not."""
    if mask is None:
        return x
    band = sig.sosfiltfilt(sig.butter(2, [lo / (SR / 2), hi / (SR / 2)], btype="band", output="sos"), x, axis=0)
    g = 10 ** (depth_db * _fit(mask, len(x)) / 20.0)
    return x + band * (g - 1.0)[:, None]


def instrumental(tag, shaper, carve_mask=None, log=print):
    """rebuild the beat from its separated stems (see module doc)."""
    stems = inst_stems(tag)
    if not stems or "drums" not in stems:
        return shaper(load(os.path.join(stem_dir(tag), "no_vocals.flac")))
    parts = {k: load(p) for k, p in stems.items()}
    n = min(len(v) for v in parts.values())
    parts = {k: v[:n] for k, v in parts.items()}
    drums = parts.pop("drums")
    out = shaper(drums)
    if "bass" in parts:
        b = parts.pop("bass")
        out = out + (dry_bass(b, kick_env(drums)) if dry_enabled() else mono_low(b))
    for v in parts.values():
        out = out + carve(v, carve_mask)
    log(f"beat rebuilt from {len(stems)} stems: {', '.join(stems)}")
    return out


# ------------------------------------------------------------------ guard
BANDS = (("sub/bass", 120.0), ("low-mid", 500.0), ("mid", 2000.0), ("high-mid", 6000.0), ("high", None))


def split_bands(x):
    """5 bands that add back up to x EXACTLY (zero-phase low-passes, telescoped)."""
    out, prev = [], np.zeros_like(x)
    for _, f in BANDS:
        lp = x if f is None else sig.sosfiltfilt(sig.butter(4, f / (SR / 2), output="sos"), x, axis=0)
        out.append(lp - prev); prev = lp
    return out


def _band_env_db(b, ms=10.0):
    k = max(1, int(ms / 1000 * SR))
    e = np.sqrt(np.convolve(np.mean(b ** 2, axis=1), np.ones(k) / k, mode="same") + 1e-12)
    return 20 * np.log10(e + 1e-9)


def guard_ref(ref):
    """analyse the original once (band shares + 10 ms peak ceilings), reuse for many guards."""
    br = split_bands(ref)
    tr = sum(np.mean(b ** 2) for b in br) + 1e-20
    return dict(rms=float(np.sqrt(np.mean(ref ** 2))), n=len(ref),
                share=[np.mean(b ** 2) / tr for b in br],
                ceil=[float(np.percentile(_band_env_db(b), 99.5)) for b in br])


def guard(y, ref, tone_tol_db=2.0, peak_tol_db=1.5, log=None):
    """keep every band of y inside the song's own parameters (ref = the original, or
    guard_ref(original)):
      tone  - each band's share of the total may move at most tone_tol_db from ref's;
              if a style pushed it further, a static gain brings it back to the edge
      peaks - each band's 10 ms peaks may exceed ref's (at matched loudness) by at
              most peak_tol_db; overs are pulled down by a smooth per-band limiter,
              so one band (an 808 boom, an 'S', a hi-hat) can't slam the final limiter
              and distort everything else."""
    R = ref if isinstance(ref, dict) else guard_ref(ref)
    ry = float(np.sqrt(np.mean(y ** 2)))
    if ry <= 0 or R["rms"] <= 0:
        return y
    lift = 20 * np.log10(ry / R["rms"])                 # compare at matched loudness
    by = split_bands(y)
    ty = sum(np.mean(b ** 2) for b in by) + 1e-20
    out, notes = [], []
    for (nm, _), b, sh, cl in zip(BANDS, by, R["share"], R["ceil"]):
        d = 10 * np.log10((np.mean(b ** 2) / ty + 1e-20) / (sh + 1e-20))
        g = 0.0
        if abs(d) > tone_tol_db:
            g = -(abs(d) - tone_tol_db) * np.sign(d)
            b = b * 10 ** (g / 20)
        over = np.maximum(_band_env_db(b) - (cl + lift + peak_tol_db), 0.0)
        red = 0.0
        if np.any(over > 0):
            # look-around hold (starts before the peak) + ~25 Hz zero-phase smoothing,
            # never less than the over itself -> smooth, and the ceiling still holds
            gr = maximum_filter1d(over, size=int(0.012 * SR))
            gr = np.maximum(sig.sosfiltfilt(sig.butter(2, 25.0 / (SR / 2), output="sos"), gr), over)
            b = b * (10 ** (-gr / 20))[:, None]; red = float(gr.max())
        if g or red > 0.05:
            notes.append(f"{nm} {g:+.1f} dB" + (f", peaks -{red:.1f}" if red > 0.05 else ""))
        out.append(b)
    if log:
        log("guard: " + ("; ".join(notes) if notes else "all bands inside the song's range"))
    return sum(out)


def guard_enabled():
    return os.environ.get("BREKEM_GUARD", "1") != "0"
