"""Beauty maximizer for the master (BREKEM_BEAUTY=<amount 0..1>, the "Beauty maximizer" [X] in Extras).

A plain maximizer turns everything up together, the harsh with the sweet. This one decides,
moment by moment and frequency by frequency, what sounds good and what doesn't, so the
loudness the limiter adds goes to the good part:

  1 TAME     harsh resonances (1.5-10 kHz) and sibilant bursts are pulled down only where and
             while they stick out. "Harsh" = a bin above its 1/3-octave neighbourhood that is
             ALSO a chronic peak of this song (a room ring, a cheap mic, a fizzy synth):
             a sung note moves, a resonance stays, so the melody is never cut.
  2 RECOVER  tonal peaks (a note, a harmonic of the voice or a chord) that HOLD for ~100 ms and
             only just clear what surrounds them (3-20 dB) - the ones at risk of being masked
             by noise, hats or fizz - are lifted. Random peaks of noise don't hold, so noise
             stays put; what already stands out clearly is left alone. It is a contrast, not
             an EQ: each octave keeps its energy moment by moment (the tones in it rise, what
             is between them steps back), so the song's tone and the reference match hold.
  3 DENSITY  the body between the hits rises a little (transients excluded), so the final
             limiter needs less gain and crushes the hits less at the same loudness.

Gains are read from the mid and applied to L and R alike (the stereo image does not move),
smoothed over time and frequency (no "musical noise"), and nothing is lifted in silence.
Applied to MASTER / INSTRUMENTAL / styles before the exciter, the band guard and the final
limiter, so the guard still holds every band inside the song's range and the loudness
target is unchanged.
"""
import os
import numpy as np
import scipy.signal as sig
from scipy.ndimage import median_filter, maximum_filter1d, uniform_filter, uniform_filter1d

SR = 48000
NFFT = 2048           # 43 ms: fine enough in frequency for resonances, short enough for drums
HOP = 512
TAME_MAX_DB = 6.0     # deepest cut on a harsh bin (amount = 1)
RECOVER_MAX_DB = 4.0  # biggest lift of the masked harmonic layer (amount = 1)
DENSITY_MAX_DB = 2.0  # biggest lift of the body between hits (amount = 1)
HARSH_LO, HARSH_HI = 1500.0, 10000.0
TONAL_LO, TONAL_HI = 150.0, 8000.0


def amount():
    try:
        return float(np.clip(float(os.environ.get("BREKEM_BEAUTY", "0")), 0.0, 1.0))
    except ValueError:
        return 0.0


def enabled():
    return amount() > 0.0


def _db(x):
    return 20.0 * np.log10(np.maximum(x, 1e-9))


def _neighbourhood(v, f, octaves=1 / 3):
    """each bin's mean of v (frames x bins) over the `octaves`-wide band around it, per frame."""
    k = np.arange(len(f))
    half = 2 ** (octaves / 2)
    lo = np.clip(np.floor(k / half).astype(int), 0, len(f) - 1)
    hi = np.clip(np.ceil(k * half).astype(int) + 1, 1, len(f))
    hi = np.maximum(hi, lo + 3).clip(max=len(f))
    cs = np.concatenate([np.zeros((v.shape[0], 1), v.dtype), np.cumsum(v, axis=1)], axis=1)
    return (cs[:, hi] - cs[:, lo]) / (hi - lo)


def _presence(mag_db_frames):
    """0..1 per frame: 1 where the song plays, 0 in silence / noise gaps (50+ dB under the loud parts)."""
    ref = float(np.percentile(mag_db_frames, 95))
    w = np.clip((mag_db_frames - (ref - 50.0)) / 15.0, 0.0, 1.0)
    return uniform_filter1d(w, size=5, mode="nearest")


def _gains(mid, amt):
    """-> (gain per frame x bin (linear), stats) from the mid channel."""
    f, _, Z = sig.stft(mid.astype(np.float32), SR, nperseg=NFFT, noverlap=NFFT - HOP)
    M = np.abs(Z).T                                   # frames x bins
    mdb = _db(M)
    nb = _neighbourhood(mdb, f)                       # 1/3-octave level, dB
    excess = mdb - nb                                 # + = sticks out of its neighbourhood
    frame_db = 10 * np.log10(np.mean(M ** 2, axis=1) + 1e-18)
    pres = _presence(frame_db)

    # ---- 1 TAME: short-term peak AND chronic resonance of this song (or a sibilant burst)
    live = pres > 0.5
    chronic = np.mean(excess[live], axis=0) if live.any() else np.zeros(len(f))
    chronic_w = np.clip((chronic - 1.0) / 3.0, 0.0, 1.0)
    zone = ((f >= HARSH_LO) & (f <= HARSH_HI)).astype(np.float32)
    sib_band = (f >= 5000) & (f <= 10000)
    sib = 10 * np.log10(np.mean(M[:, sib_band] ** 2, axis=1) + 1e-18)
    sib_over = sib - uniform_filter1d(sib, size=int(0.25 * SR / HOP), mode="nearest")
    sib_w = np.clip((sib_over - 4.0) / 6.0, 0.0, 1.0)       # 0 normally, 1 on an "S" spike
    harsh_w = np.maximum(chronic_w[None, :], sib_w[:, None] * sib_band[None, :])
    tame_db = -np.minimum(np.maximum(excess - 3.0, 0.0) * 0.6, TAME_MAX_DB) * harsh_w * zone * amt

    # ---- 2 RECOVER: tonal peaks (a note, a harmonic) that barely clear what surrounds them
    H = median_filter(M, size=(17, 1), mode="nearest")      # steady across time
    P = median_filter(M, size=(1, 17), mode="nearest")      # the level around it in frequency
    Mh = H ** 2 / (H ** 2 + P ** 2 + 1e-18)                 # steady (not a hit)...
    # ...and a peak over its surroundings that HOLDS for ~100 ms: a note does, a random
    # peak of noise does not
    prom = median_filter(mdb - _db(P), size=(9, 1), mode="nearest")
    # 3-20 dB over the surroundings: a tone at risk of being masked. Under that it is noise,
    # over that it is already clearly heard and is left alone (no over-bright lead).
    peak = np.clip((prom - 2.5) / 2.5, 0.0, 1.0) * np.clip((20.0 - prom) / 6.0, 0.0, 1.0)
    audible = np.clip((_db(H) - (frame_db[:, None] - 45.0)) / 10.0, 0.0, 1.0)   # real music, not floor
    tonal = ((f >= TONAL_LO) & (f <= TONAL_HI)).astype(np.float32)
    rec = (10 ** (RECOVER_MAX_DB * amt / 20) - 1.0) * np.sqrt(Mh) * peak * audible * tonal * pres[:, None]

    # smooth over ~3 frames (no flutter, no "musical noise"); the lift spreads to the bins on
    # either side by MAX (the whole note's lobe rises), never averaged away from its peak
    tame_db = uniform_filter(tame_db, size=(3, 3), mode="nearest")
    rec = uniform_filter1d(maximum_filter1d(rec, size=3, axis=1), size=3, axis=0, mode="nearest")
    # the lift is a CONTRAST, not an EQ: in each moment every octave keeps its energy - the tones
    # in it rise, what is between them steps back. The tone of the song (and the reference
    # match / band guard) is untouched; only the harsh cuts above change the level.
    p0 = M.astype(np.float64) ** 2
    Gr = 1.0 + rec
    keep = np.sqrt(_neighbourhood(p0, f, 1.0) / (_neighbourhood(p0 * Gr ** 2, f, 1.0) + 1e-30))
    Gr = Gr * np.where(p0.sum(axis=1, keepdims=True) > 0, keep, 1.0)
    G = (10 ** (tame_db / 20)) * Gr
    st = dict(tame_mean=float(np.mean(tame_db[live][:, zone > 0])) if live.any() else 0.0,
              tame_deep=float(np.mean(tame_db < -1.0)) * 100,
              rec_mean=float(np.mean(_db(Gr)[live][:, tonal > 0][(peak[live][:, tonal > 0]) > 0.5]))
              if live.any() and (peak[live][:, tonal > 0] > 0.5).any() else 0.0)
    return G.T.astype(np.float32), st


def _apply(x, G):
    y = np.empty_like(x)
    for c in range(x.shape[1]):
        _, _, Z = sig.stft(x[:, c].astype(np.float32), SR, nperseg=NFFT, noverlap=NFFT - HOP)
        _, yc = sig.istft(Z * G[:, :Z.shape[1]], SR, nperseg=NFFT, noverlap=NFFT - HOP)
        y[:, c] = yc[:len(x)] if len(yc) >= len(x) else np.pad(yc, (0, len(x) - len(yc)))
    return y


def _density(x, amt):
    """lift the body between hits by up to DENSITY_MAX_DB; transients and silence untouched."""
    m = x.mean(1).astype(np.float64)
    # running sums can dip below 0 by rounding (exactly 0 in silence) -> clamp before the sqrt
    fast = np.sqrt(np.maximum(uniform_filter1d(m * m, int(0.005 * SR), mode="nearest"), 0.0) + 1e-20)
    slow = np.sqrt(np.maximum(uniform_filter1d(m * m, int(0.080 * SR), mode="nearest"), 0.0) + 1e-20)
    sdb = _db(slow)
    ref = float(np.percentile(sdb, 95))
    body = np.clip((sdb - (ref - 24.0)) / 6.0, 0.0, 1.0) * np.clip((ref - 3.0 - sdb) / 6.0, 0.0, 1.0)
    hit = np.clip((_db(fast / slow) - 2.0) / 4.0, 0.0, 1.0)       # fast env well over slow = a transient
    g_db = DENSITY_MAX_DB * amt * body * (1.0 - hit)
    g_db = uniform_filter1d(g_db, int(0.030 * SR), mode="nearest")  # glide, no pumping
    return x * (10 ** (g_db / 20))[:, None], float(np.mean(g_db[body > 0.5])) if (body > 0.5).any() else 0.0


def beautify(x, amt=None, log=None):
    """x: (n, 2) float at 48 kHz -> beautified copy (same shape)."""
    if x.ndim != 2 or x.shape[1] != 2 or len(x) < SR:
        return x
    amt = amount() if amt is None else float(np.clip(amt, 0.0, 1.0))
    if amt <= 0:
        return x
    G, st = _gains(x.mean(1), amt)
    y = _apply(x, G)
    y, dens = _density(y, amt)
    if not np.isfinite(y).all():          # never hand a broken file to the rest of the chain
        if log:
            log("beauty: skipped (numeric problem) - song left as it was")
        return x
    if log:
        log(f"beauty {amt * 100:.0f}%: harsh -{abs(st['tame_mean']):.1f} dB avg (cut >1 dB on "
            f"{st['tame_deep']:.1f}% of the spectrum), masked tones +{st['rec_mean']:.1f} dB avg, "
            f"body between hits +{dens:.1f} dB")
    return y
