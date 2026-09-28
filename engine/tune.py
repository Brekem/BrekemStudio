"""Natural pitch correction (no robot): every sung note is moved as a whole to the
nearest note of the song's key, so its centre lands in tune while the singer's own
vibrato, slides, bends and scoops inside the note are kept exactly as sung.

  key     read from the beat (chroma of the instrumental vs. Krumhansl-Schmuckler
          major/minor profiles); unsure -> chromatic (nearest semitone)
  notes   pitch every 10 ms (Praat); a note = a voiced run, split where the
          sung pitch moves to another note (median jump > 0.7 semitone)
  shift   one shift per note (target - note median), eased in and out over
          ~40 ms so note-to-note moves stay natural; notes already within
          8 cents, and pieces under 120 ms (slides, scoops), are left alone
  engine  Praat PSOLA (Manipulation -> overlap-add): pitch moves, the voice's
          formants (its timbre) do not - no chipmunk, no metallic auto-tune

Only the mid (centre) of the vocal is retuned; its side (room, stereo) is kept.
Frames outside `active` (the vocal-activity mask) are never touched, so bleed from
the beat in the vocal stem is not retuned.
"""
import os
import numpy as np
import soundfile as sf
import scipy.signal as sig

SR = 48000
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_SCALE = {"major": (0, 2, 4, 5, 7, 9, 11),
          "minor": (0, 2, 3, 5, 7, 8, 10, 11)}      # natural minor + the raised 7th singers use


def enabled():
    return os.environ.get("BREKEM_TUNE", "0") == "1"


def proc_cache():
    """file name of the cached clean vocal chain (tuned and untuned are kept apart)."""
    return "vocals_proc_tuned.wav" if enabled() else "vocals_proc.wav"


def detect_key(beat):
    """-> (pitch classes allowed, label, confidence 0..1). Chromatic when unsure."""
    import librosa
    y = sig.resample_poly(beat.mean(1), 1, 2)
    C = librosa.feature.chroma_stft(y=y, sr=SR // 2, n_fft=8192, hop_length=4096).mean(1)
    best = (-2.0, None, None)
    for mode, prof in (("major", _MAJOR), ("minor", _MINOR)):
        for t in range(12):
            r = float(np.corrcoef(C, np.roll(prof, t))[0, 1])
            if r > best[0]:
                best = (r, t, mode)
    r, t, mode = best
    if r < 0.55 or t is None:
        return tuple(range(12)), f"chromatic (key unclear, r={r:.2f})", max(r, 0.0)
    return tuple((t + i) % 12 for i in _SCALE[mode]), f"{_NAMES[t]} {mode}", r


def _nearest(midi, pcs):
    base = np.floor(midi / 12.0) * 12.0
    cand = np.array([base + p + o for p in pcs for o in (-12, 0, 12)])
    return float(cand[np.argmin(np.abs(cand - midi))])


def _notes(midi, voiced, min_len=6, jump=0.7):
    """split voiced frames into notes -> list of (start, end) frame indices."""
    out, i, n = [], 0, len(midi)
    while i < n:
        if not voiced[i]:
            i += 1; continue
        j = i
        while j < n and voiced[j]:
            j += 1
        s = i
        for k in range(i + 1, j):                       # a new note when the sung pitch moves on
            ref = np.median(midi[max(s, k - 8):k])
            nxt = np.median(midi[k:min(j, k + 5)])
            if abs(nxt - ref) > jump and k - s >= min_len:
                out.append((s, k)); s = k
        if j - s >= min_len:
            out.append((s, j))
        i = j
    return out


def tune(voice, pcs, active=None, strength=1.0, ease_ms=40.0, min_cents=8.0, log=None):
    """voice: (n, 2) float at 48 kHz. Returns the retuned voice, same shape."""
    import parselmouth
    from parselmouth.praat import call
    n = len(voice)
    mid = voice.mean(1)
    side = voice - mid[:, None]
    snd = parselmouth.Sound(mid.astype(np.float64), sampling_frequency=SR)
    pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=70.0, pitch_ceiling=1000.0)
    f0 = pitch.selected_array["frequency"]
    t = pitch.xs()
    voiced = f0 > 0
    if active is not None:
        voiced &= np.interp(t * SR, np.arange(n), active) > 0.5
    if voiced.sum() < 10:
        if log: log("tune: no sung notes found - voice left as is")
        return voice
    midi = np.zeros_like(f0)
    midi[voiced] = 69.0 + 12.0 * np.log2(f0[voiced] / 440.0)
    shift = np.zeros_like(f0)
    moved = []
    for a, b in _notes(midi, voiced):
        if b - a < 12:                                   # < 120 ms: a slide / scoop between notes, keep it
            continue
        centre = float(np.median(midi[a:b]))
        d = _nearest(centre, pcs) - centre
        if abs(d) * 100.0 >= min_cents:
            shift[a:b] = d * strength
            moved.append(abs(d) * 100.0)
    if not moved:
        if log: log("tune: already in tune - voice left as is")
        return voice
    k = max(1, int(round(ease_ms / 10.0)))              # ease the shift in/out of each note
    shift = np.convolve(shift, np.ones(k) / k, mode="same")
    new_f0 = f0 * 2.0 ** (shift / 12.0)
    manip = call(snd, "To Manipulation", 0.01, 70.0, 1000.0)
    tier = call("Create PitchTier", "tuned", snd.xmin, snd.xmax)
    for ti, fi in zip(t[voiced], new_f0[voiced]):
        call(tier, "Add point", float(ti), float(fi))
    call([tier, manip], "Replace pitch tier")
    out = call(manip, "Get resynthesis (overlap-add)").values[0]
    y = np.zeros(n)
    y[:min(n, len(out))] = out[:n]
    if log:
        log(f"tune: {len(moved)} notes moved to the key, average {np.mean(moved):.0f} cents, "
            f"max {np.max(moved):.0f} cents (vibrato and slides kept)")
    return y[:, None] + side


def tuned_vocal(stem_dir, raw, beat, active=None, log=print):
    """retuned vocal stem, cached next to the stems (prep.py clears it on re-separation)."""
    cache = os.path.join(stem_dir, "vocals_tuned.wav")
    if os.path.exists(cache):
        y, s = sf.read(cache, dtype="float64", always_2d=True)
        if s == SR and len(y) == len(raw):
            log("tune: cached retuned vocal")
            return y
    pcs, label, r = detect_key(beat)
    log(f"tune: key {label}" + (f" (confidence {r:.2f})" if "chromatic" not in label else ""))
    y = tune(raw, pcs, active=active, log=log)
    sf.write(cache, y.astype(np.float32), SR, subtype="FLOAT")
    return y
