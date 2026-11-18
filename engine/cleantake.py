"""Clean voice: leave only the voice (BREKEM_CLEANVOX=1, the "Clean voice" [X] in Extras;
the "Clean take" button on the Record tab runs it on one take so you can hear it first).
Usage:  python cleantake.py <take.wav> <out.wav> [<beat file>]
        python cleantake.py --combine <out.wav> <beat file | ""> both|newest <take> <take> [...]
          (several takes of one song -> one vocal, see combine())

  1 BLEED   the beat leaking from the headphones into the mic is subtracted. A take is on the
            beat's timeline (Record shifted it by the measured round trip), so the leak is the
            beat through a short acoustic path (earcup -> mic). That path is learnt where nobody
            sings (least squares, per frequency) and the beat sent through it is taken out
            everywhere - only if it really lowers the gaps.
  2 HUM     mains hum (50 or 60 Hz and its harmonics) notched out, only the lines found.
  3 CLICKS  mouth clicks (lip smacks, saliva: 0.5-3 ms spikes far over their surroundings)
            pulled down in the highs; consonants last longer and are left alone.
  4 GATE    silence where nobody sings (room, PC, street, what is left of the leak). The
            threshold follows the take's own noise floor; a hold keeps word starts, word ends
            and short gaps, soft attack / release never click. Breaths right next to a phrase
            stay (the vocal chain lowers them later); lone ones in the gaps go.

clean_voice(full=True) does all four (a recorded vocal: Record, Mix from stems). A vocal
separated from a song (Master, Batch, Distribute, Styles) already has its own bleed-aware
gate that rebuilds the original between phrases, so there full=False: hum + clicks only.
"""
import os
import sys
import subprocess
import tempfile
import numpy as np
import soundfile as sf
import scipy.signal as sig
from scipy.ndimage import maximum_filter1d, uniform_filter1d

HOP_S = 0.010
BELOW_DB = 28.0        # the gate opens fully this far under the loud parts of the voice...
KNEE_DB = 8.0          # ...and fades out over this much more (a soft word is ducked, never chopped)
PRE_S, POST_S = 0.08, 0.20   # held open this long before a word starts / after it ends
GATE_FLOOR_DB = -80.0  # what is left in the gaps
CLICK_DB = 12.0        # a click: 1 ms level this far over its 20 ms neighbourhood...
CLICK_MAX_MS = 3.0     # ...and gone again within this


def enabled():
    return os.environ.get("BREKEM_CLEANVOX", "0") == "1"


def _env_db(x, ms, sr):
    k = max(1, int(ms / 1000 * sr))
    return 10 * np.log10(np.maximum(uniform_filter1d(x * x, k, mode="nearest"), 0.0) + 1e-20)


def _frames_db(x, sr):
    hop = int(HOP_S * sr)
    n = max(1, len(x) // hop)
    return 10 * np.log10(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20), hop


def _voice_frames(m, sr):
    """-> (frames dB, hop, voice 0..1 per frame, recorded frames). voice > 0.5 = someone sings."""
    db, hop = _frames_db(m, sr)
    rec = db > -110.0                                   # the zero padding before a punch-in is not "noise"
    if not rec.any():
        return db, hop, np.zeros(len(db)), rec
    loud = float(np.percentile(db[rec], 95))
    floor = float(np.percentile(db[rec], 10))
    thr = max(loud - BELOW_DB, floor + 12.0)            # adaptive: a noisy room raises the bar
    v = np.clip((db - (thr - KNEE_DB)) / KNEE_DB, 0.0, 1.0)
    pre, post = int(PRE_S / HOP_S), int(POST_S / HOP_S)
    v = maximum_filter1d(v, size=pre + post + 1, origin=(pre - post) // 2, mode="nearest")
    return db, hop, v * rec, rec


def _samples(frames, hop, n):
    s = np.repeat(frames, hop)[:n]
    return np.pad(s, (0, n - len(s)))


def load_beat(path, sr, n):
    """any audio -> mono float at sr, n samples (ffmpeg decodes mp3 / m4a too)."""
    tmp = os.path.join(os.environ.get("BREKEM_WORK") or tempfile.gettempdir(), "cleantake_beat.wav")
    subprocess.run([os.environ.get("BREKEM_FFMPEG") or "ffmpeg", "-v", "error", "-y", "-i", path,
                    "-ar", str(sr), "-ac", "1", "-c:a", "pcm_f32le", tmp],
                   capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not os.path.exists(tmp):
        return None
    b, _ = sf.read(tmp, dtype="float64")
    os.remove(tmp)
    return np.pad(b, (0, max(0, n - len(b))))[:n]


def debleed(x, beat, sr, gaps):
    """subtract the beat as heard through the headphones -> mic path, learnt in the gaps.
    -> (x, gaps lowered by dB) ; dB None = too few gaps to learn from."""
    nper = 4096                                         # 85 ms: room for the acoustic path + slack
    gs = _samples(gaps, int(HOP_S * sr), len(x)).astype(np.float64)
    if gs.sum() < 2 * sr:
        return x, None
    xg, bg = x * gs, beat * gs                          # gaps only: the voice never biases the path
    _, Sbb = sig.welch(bg, sr, nperseg=nper)
    _, Sxb = sig.csd(bg, xg, sr, nperseg=nper)
    H = Sxb / (Sbb + 1e-12 * np.max(Sbb) + 1e-30)
    h = np.roll(np.fft.irfft(H, n=nper), nper // 2) * np.hanning(nper)   # lags +-42 ms, smooth ends
    leak = sig.fftconvolve(beat, h, mode="full")[nper // 2:nper // 2 + len(x)]
    gain = 10 * np.log10(np.mean(xg ** 2) / (np.mean(((x - leak) * gs) ** 2) + 1e-30) + 1e-30)
    return (x - leak, gain) if gain >= 1.0 else (x, gain)


def hum_lines(m, sr, gaps):
    """the mains-hum lines found (50 or 60 Hz family), read from the gaps when there are some."""
    gs = _samples(gaps, int(HOP_S * sr), len(m))
    seg = m[gs.nonzero()[0]] if gs.sum() >= sr else m
    f, P = sig.welch(seg, sr, nperseg=16384)
    Pd = 10 * np.log10(P + 1e-30)

    def prom(hz):
        k = int(np.argmin(np.abs(f - hz)))
        return Pd[k] - np.median(Pd[max(0, k - 30):k + 30])

    base = max((50.0, 60.0), key=lambda b: max(prom(b * k) for k in (1, 2, 3)))
    return base, [base * k for k in range(1, 9) if base * k < 1000 and prom(base * k) > 6.0]


def dehum(x, sr, lines):
    for hz in lines:
        b, a = sig.iirnotch(hz, 35.0, sr)
        x = sig.filtfilt(b, a, x)
    return x


def declick(x, sr):
    hp = sig.sosfiltfilt(sig.butter(2, 2000.0, btype="high", fs=sr, output="sos"), x)
    e1, e5, e20 = _env_db(hp, 1, sr), _env_db(hp, 5, sr), _env_db(hp, 20, sr)
    spike = (e1 - e20 > CLICK_DB) & (e5 - e20 < CLICK_DB - 4)   # sharp AND short: not a "t" / "k"
    spike = maximum_filter1d(spike.astype(np.uint8), size=int(CLICK_MAX_MS / 1000 * sr)) > 0
    n = int(np.sum(np.diff(spike.astype(np.int8)) == 1))
    if n == 0:
        return x, 0
    cut = np.clip(e1 - e20 - 3.0, 0.0, 30.0) * spike             # down to the neighbourhood level
    g = 10 ** (-uniform_filter1d(cut, int(0.001 * sr), mode="nearest") / 20)
    return x - hp * (1.0 - g), n


def gate_gain(sing, hop, n):
    a_att, a_rel = np.exp(-1.0 / (0.010 / HOP_S)), np.exp(-1.0 / (0.150 / HOP_S))
    out = np.empty(len(sing))
    prev = 0.0
    for i, v in enumerate(sing.astype(np.float64)):
        a = a_att if v > prev else a_rel
        prev = a * prev + (1 - a) * v
        out[i] = prev
    fl = 10 ** (GATE_FLOOR_DB / 20)
    t = np.arange(len(sing)) * hop + hop // 2
    return fl + (1 - fl) * np.interp(np.arange(n), t, out)


def clean_voice(x, sr, beat=None, full=True, log=None):
    """x: (n,) or (n, ch) vocal -> cleaned copy, same shape. beat: mono, same timeline (or None)."""
    say = log or (lambda m: None)
    two = x.ndim == 2
    X = (x if two else x[:, None]).astype(np.float64).copy()
    n = len(X)
    db, hop, sing, rec = _voice_frames(X.mean(1), sr)
    gaps = rec & (sing == 0)                          # gate fully closed: nobody sings
    g0 = float(np.median(db[gaps])) if gaps.any() else -120.0
    if full:
        say(f"clean voice: sung {100 * np.mean(sing[rec] > 0.5) if rec.any() else 0:.0f}% of "
            f"{np.sum(rec) * HOP_S:.0f} s, gaps at {g0:.0f} dBFS")
        if beat is not None:
            b = np.pad(beat, (0, max(0, n - len(beat))))[:n]
            gains = []
            for c in range(X.shape[1]):
                X[:, c], gc = debleed(X[:, c], b, sr, gaps)
                gains.append(gc)
            gc = gains[0]
            say("  bleed: " + ("not enough gaps to learn the leak" if gc is None else
                               f"beat leak removed, gaps -{gc:.1f} dB" if gc >= 1.0 else
                               f"no real leak from the headphones ({gc:+.1f} dB), left as it was"))
    base, lines = hum_lines(X.mean(1), sr, gaps)
    nclick = 0
    for c in range(X.shape[1]):
        X[:, c] = dehum(X[:, c], sr, lines)
        X[:, c], k = declick(X[:, c], sr)
        nclick = max(nclick, k)
    say(f"  hum: {len(lines)} {base:.0f} Hz line(s) notched ({', '.join(f'{h:.0f}' for h in lines)})" if lines
        else "  hum: none found")
    say(f"  clicks: {nclick} mouth click(s) pulled down")
    if full:
        db2, hop, sing, rec = _voice_frames(X.mean(1), sr)   # re-read: the leak / hum may have hidden quiet words
        X *= gate_gain(sing, hop, n)[:, None]
        gaps = rec & (sing == 0)
        g1 = float(np.median(_frames_db(X.mean(1), sr)[0][gaps])) if gaps.any() else -120.0
        say(f"  gate: {100 * np.mean(gaps[rec]) if rec.any() else 0:.0f}% silenced, gaps {g0:.0f} -> {g1:.0f} dBFS")
    if not np.isfinite(X).all():
        say("  clean voice: skipped (numeric problem), vocal left as it was")
        return x
    return X if two else X[:, 0]


def _segments(active, hop, sr, join_s=1.0, min_s=0.5):
    """frames where active -> [(start s, end s)], joining gaps under join_s, dropping bits under min_s."""
    out = []
    idx = np.flatnonzero(active)
    if not len(idx):
        return out
    fs = hop / sr
    a = b = idx[0]
    for k in idx[1:]:
        if (k - b) * fs > join_s:
            out.append((a * fs, (b + 1) * fs))
            a = k
        b = k
    out.append((a * fs, (b + 1) * fs))
    return [(s, e) for s, e in out if e - s >= min_s]


def _mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def combine(paths, beat_path=None, overlap="both", log=None):
    """takes recorded over the same beat, each holding only the parts sung in it (chorus in one,
    verses in another, or each artist in his own) -> one vocal: every take cleaned (so where it
    was not sung it is silent), brought to the same singing level, then summed.
    overlap: where two takes both sing - "both" keeps both (a feat, a double), "newest" keeps
    only the later take there (a part sung again because the first one was not right).
    -> (vocal mono, sr)."""
    say = log or (lambda m: None)
    voc, sr, beat = [], None, None
    for p in paths:
        x, s = sf.read(p, dtype="float64")
        x = x.mean(1) if x.ndim > 1 else x
        if sr is None:
            sr = s
            if beat_path and os.path.exists(beat_path):
                beat = load_beat(beat_path, sr, len(x))
        elif s != sr:                                   # recorded on another device: to the first rate
            g = np.gcd(int(s), int(sr))
            x = sig.resample_poly(x, sr // g, s // g)
        say(f"--- {os.path.basename(p)}")
        voc.append(clean_voice(x, sr, beat=beat, full=True, log=say))
    n = max(len(v) for v in voc)
    voc = [np.pad(v, (0, n - len(v))) for v in voc]

    # where each take sings, and how loud it sings there
    masks, levels = [], []
    for v in voc:
        db, hop, sing, rec = _voice_frames(v, sr)
        on = sing > 0.5
        masks.append(sing)
        levels.append(10 * np.log10(np.mean(10 ** (db[on] / 10))) if on.any() else None)
    known = [l for l in levels if l is not None]
    target = float(np.median(known)) if known else 0.0
    out = np.zeros(n)
    for i, (p, v, l) in enumerate(zip(paths, voc, levels)):
        if l is None:
            say(f"{os.path.basename(p)}: no singing found - left out")
            continue
        g = float(np.clip(target - l, -9.0, 9.0))
        w = 10 ** (g / 20)
        if overlap == "newest":                         # later takes win where they sing
            for j in range(i + 1, len(voc)):
                if levels[j] is not None:
                    w = w * (1.0 - np.clip(gate_gain(masks[j], hop, n), 0.0, 1.0))
        out += v * w
        parts = ", ".join(f"{_mmss(a)}-{_mmss(b)}" for a, b in _segments(masks[i] > 0.5, hop, sr, join_s=3.0))
        say(f"{os.path.basename(p)}: {g:+.1f} dB to sit level with the others, sings {parts or '-'}")
    both = np.sum([m > 0.5 for m, l in zip(masks, levels) if l is not None], axis=0) >= 2
    ov = _segments(both, hop, sr, join_s=3.0, min_s=0.5) if np.ndim(both) else []
    if ov:
        say(("two takes sing together at " if overlap == "both" else "sung twice, newest take kept at ")
            + ", ".join(f"{_mmss(a)}-{_mmss(b)}" for a, b in ov))
    pk = float(np.max(np.abs(out))) if n else 0.0
    if pk > 0.99:                                       # stacked voices past full scale: down evenly
        out *= 0.99 / pk
        say(f"stacked voices peaked at {20 * np.log10(pk):+.1f} dBFS - lowered as a whole")
    return out, sr


def main():
    if sys.argv[1] == "--combine":                      # cleantake.py --combine out.wav beat both|newest take...
        dst, beat_path, overlap, takes = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]
        y, sr = combine(takes, beat_path or None, overlap, log=lambda m: print(m, flush=True))
        sf.write(dst, np.clip(y, -1.0, 1.0).astype(np.float32), sr, subtype="PCM_24")
        print("DONE combine", flush=True)
        return
    src, dst = sys.argv[1], sys.argv[2]
    beat_path = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    x, sr = sf.read(src, dtype="float64")
    beat = None
    if beat_path and os.path.exists(beat_path):
        beat = load_beat(beat_path, sr, len(x))
    elif beat_path:
        print(f"beat not found: {beat_path} - bleed step skipped", flush=True)
    y = clean_voice(x, sr, beat=beat, full=True, log=lambda m: print(m, flush=True))
    sf.write(dst, np.clip(y, -1.0, 1.0).astype(np.float32), sr, subtype="PCM_24")
    print("DONE cleantake", flush=True)


if __name__ == "__main__":
    main()
