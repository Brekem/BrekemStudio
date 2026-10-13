"""Harmonic exciter for the master (BREKEM_EXCITER=1, the "Exciter" [X] in Extras).

An EQ can only turn up what is already there (and the hiss with it). An exciter
CREATES new overtones from the music itself, the way the Aphex Aural Exciter and
Waves MaxxBass do, so the master sounds brighter, more present and fuller at the
same loudness:

  highs  the band above 3 kHz is driven through a soft saturator (odd + a little
         even harmonics). Only the NEW harmonics are kept (the clean signal is
         subtracted) and only above 5 kHz (low intermodulation removed), then mixed
         back low under the music: sparkle and air on hats, guitars, vocal "air",
         without an EQ lift. Sibilance-aware: where an "S" spikes, the exciter
         backs off, so it never adds harshness.
  bass   the sub (30-110 Hz, centre only) is rectified + saturated and only its
         2nd / 3rd harmonics (70-200 Hz, never up into the mud) are kept and mixed under the bass:
         the ear hears the low note from its harmonics, so the bass comes through
         on phones, laptops and earbuds that can't play the sub. Mono, so it stays
         centred and dry.

Both layers follow the music's own envelope (no harmonics where there is no
music, no noise lifted in the gaps). Applied to MASTER / INSTRUMENTAL / styles
before the band guard and the final limiter, so the guard still holds every
band inside the song's range and the loudness target is unchanged.
"""
import os
import numpy as np
import scipy.signal as sig
from scipy.ndimage import uniform_filter1d

SR = 48000
HI_RISE_DB = 1.5   # the new top harmonics lift the >5 kHz band by this much (amount=1)
LO_RISE_DB = 1.5   # the bass harmonics lift the 110-200 Hz band by this much (amount=1)
HI_CAP_DB = -6.0   # ...but never louder than this vs the >3 kHz band they come from
LO_CAP_DB = -8.0   # ...or than this vs the sub they come from (no sub -> no bass layer)
LO_MIN_DB = -15.0  # a clean sub (an 808 with no overtones) still gets its harmonics at least this loud


def enabled():
    return os.environ.get("BREKEM_EXCITER", "0") == "1"


def _sos(order, f, btype):
    return sig.butter(order, np.atleast_1d(f) / (SR / 2), btype=btype, output="sos")


def _env(x, ms):
    """smooth RMS envelope of a 1-D signal."""
    m = uniform_filter1d(x * x, size=max(1, int(ms / 1000 * SR)), mode="nearest")
    return np.sqrt(np.maximum(m, 0.0) + 1e-20)     # running sums can dip below 0 by rounding


def _rms(x):
    return float(np.sqrt(np.mean(x * x)) + 1e-20)


def _harmonics(b, env, shape):
    """new overtones of b only: normalise by its envelope (steady harmonic density at
    any level), saturate, subtract the linear part, restore the envelope."""
    d = b / (env + 1e-4 * _rms(b))
    s = shape(d)
    g = float(np.dot(s, d) / (np.dot(d, d) + 1e-20))      # best linear fit -> remove the clean signal
    return (s - g * d) * env


def _hi_shape(d):
    return np.tanh(1.6 * d) + 0.12 * np.tanh(d) ** 2       # odd + a touch of even (warm, not fizzy)


def _lo_shape(d):
    return np.tanh(1.4 * d) + 0.5 * np.abs(np.tanh(d))     # full-wave adds the octave (2nd) the ear needs


def _level(layer, band, layer_in_band, rise_db, source, cap_db, min_db=None):
    """gain the layer so `band` (the original, measured in the target band) rises by exactly
    rise_db once the layer is added (its correlation with the music included), capped vs its source."""
    pn = float(np.sum(band * band)); pl = float(np.sum(layer_in_band * layer_in_band)) + 1e-30
    c = float(np.sum(band * layer_in_band))
    pt = pn * 10 ** (max(rise_db, 0.0) / 10)
    g = (-c + np.sqrt(max(c * c + pl * (pt - pn), 0.0))) / pl
    if min_db is not None:
        g = max(g, _rms(source) * 10 ** (min_db / 20) / _rms(layer))
    g = min(g, _rms(source) * 10 ** (cap_db / 20) / _rms(layer))
    return layer * g


def _presence(x):
    """0..1 from the FULL mix level: 1 where the song plays (even a soft verse), 0 in silence /
    noise gaps (50+ dB under the song's loud parts), so the exciter never brings up hiss
    between phrases or in the tail."""
    db = 20 * np.log10(_env(x.mean(1), 50) + 1e-12)
    ref = float(np.percentile(db, 95))
    w = np.clip((db - (ref - 50.0)) / 15.0, 0.0, 1.0)
    return uniform_filter1d(w, size=int(0.020 * SR), mode="nearest")


def _sibilance_gain(mid):
    """1 normally, down to 0.25 where a sibilant ("S", "T", "CH") spikes over its surroundings."""
    s = sig.sosfiltfilt(_sos(4, [5000.0, 10000.0], "band"), mid)
    over = 20 * np.log10(_env(s, 5) / _env(s, 250))
    g = np.clip(1.0 - (over - 3.0) / 9.0, 0.25, 1.0)
    return uniform_filter1d(g, size=int(0.010 * SR), mode="nearest")


def excite(x, amount=1.0, log=None):
    """x: (n, 2) float at 48 kHz -> excited copy (same shape)."""
    if x.ndim != 2 or x.shape[1] != 2 or len(x) < SR // 2:
        return x
    amt = max(0.0, float(amount))
    # ---- highs
    pres = _presence(x)
    hp = sig.sosfiltfilt(_sos(4, 3000.0, "high"), x, axis=0)
    hi = np.zeros_like(x)
    for c in range(2):
        hi[:, c] = _harmonics(hp[:, c], _env(hp[:, c], 50), _hi_shape) * pres
    hi = sig.sosfiltfilt(_sos(4, 5000.0, "high"), hi, axis=0)          # keep only the new top, no low IM
    sib = _sibilance_gain(x.mean(1))
    hi *= sib[:, None]
    top = sig.sosfiltfilt(_sos(4, 5000.0, "high"), x, axis=0)
    hi = _level(hi, top, hi, HI_RISE_DB * amt, hp, HI_CAP_DB)
    # ---- bass (centre only)
    sub = sig.sosfiltfilt(_sos(4, [30.0, 110.0], "band"), x.mean(1))
    lo = _harmonics(sub, _env(sub, 30), _lo_shape) * pres
    lo = sig.sosfiltfilt(_sos(4, [70.0, 200.0], "band"), lo)
    near = sig.sosfiltfilt(_sos(4, [70.0, 200.0], "band"), x.mean(1))
    if np.dot(lo, near) < 0:                     # add to the bass's own overtones, never cancel them
        lo = -lo
    meas = _sos(4, [110.0, 200.0], "band")
    lo = _level(lo, sig.sosfiltfilt(meas, x.mean(1)), sig.sosfiltfilt(meas, lo), LO_RISE_DB * amt, sub, LO_CAP_DB,
               LO_MIN_DB + 20 * np.log10(max(amt, 1e-3)))
    y = x + hi + lo[:, None]
    if log:
        log(f"exciter: high harmonics {20 * np.log10(_rms(hi) / _rms(x)):+.1f} dB re mix "
            f"(backed off on {100 * float(np.mean(sib < 0.9)):.0f}% sibilants), "
            f"bass harmonics {20 * np.log10(_rms(lo) / _rms(x)):+.1f} dB re mix")
    return y
