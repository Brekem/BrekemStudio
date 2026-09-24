"""Multi-stem helpers shared by the master engines (track_v2, noref, clean).

prep.py now separates every song into as many stems as the chosen Demucs model
gives (vocals / drums / bass / other, + guitar / piano with htdemucs_6s) and keeps
no_vocals.flac (= sum of the non-vocal stems) for older callers. This module:

  * instrumental(tag, shaper, carve_mask)  rebuilds the beat stem by stem:
        drums  -> the caller's transient shaper (punch on the kick only)
        bass   -> low end folded to mono (tight, mono-safe 808)
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
    out = shaper(parts.pop("drums"))
    if "bass" in parts:
        out = out + mono_low(parts.pop("bass"))
    for v in parts.values():
        out = out + carve(v, carve_mask)
    log(f"beat rebuilt from {len(stems)} stems: {', '.join(stems)}")
    return out
