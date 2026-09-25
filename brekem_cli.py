"""BREKEM STUDIO - headless orchestrator.
Drives the proven engine scripts (prep, track_v2, noref, daw_song, stemmix, clean):
adaptive per-track parameter search + optional polish pass + consolidation to
MASTER / INSTRUMENTAL / ACAPELLA / APPLE DIGITAL MASTER + FLAC + MP3-320 + the
6-axis verdict against the user's own reference songs (or a no-reference master
when no references are set).

CLI:
  brekem_cli.py master   "<audio>"   "<outdir>" [--fast] [--sep MODEL] [--shifts N] [STYLE OPTS]
  brekem_cli.py batch    "<folder>"  "<outdir>" [--fast] [--sep MODEL] [--shifts N] [STYLE OPTS]
STYLE OPTS (every command): --styles cd,clarity,espacial,punch,warm,club,streaming,signature | all
  -> those master styles (+ COMPARE.html) in <outdir>/VARIANTS
  --no-dry-bass  keep the bass as separated (default: centred + dry)
  --no-guard     no band guard (default: every band stays inside the song's own range)
  brekem_cli.py stemmix  "<stemdir>" "<voxfile>" "<outdir>" [--vox -3.0]
  brekem_cli.py distribute "<audio|folder>" "<outdir>" [--lufs -9.5] [--no-split] [--clean] [--sep MODEL]
MODEL (stem separation): htdemucs_ft (default, 4 stems, best) | htdemucs_6s (6 stems) | htdemucs (fast)
"""
import os, re, sys, glob, shutil, argparse
import brekem_env as E

AUDIO_EXT = (".wav", ".flac", ".mp3", ".m4a", ".aif", ".aiff", ".ogg", ".wma")
DELTA_RE = re.compile(
    r"vs MEAN refs:\s+low ([+-][\d.]+)\s+pres ([+-][\d.]+)\s+air ([+-][\d.]+)\s+I ([+-][\d.]+)\s+corr ([+-][\d.]+)")
OKN_RE = re.compile(r"(\d+)/6 axes")
AX_LBL = {"low": "low  +-1.5 dB", "pres": "pres +-1.5 dB", "air": "air  +-1.5 dB", "stereo": "stereo in range"}
DELIV = ("MASTER", "INSTRUMENTAL", "ACAPELLA", "APPLE DIGITAL MASTER")
SEP_MODELS = ("htdemucs_ft", "htdemucs_6s", "htdemucs")
SEP_DEFAULT = "htdemucs_ft"
STYLE_IDS = ("cd", "clarity", "espacial", "punch", "warm", "club", "streaming", "signature")


def _opts(dry, guard):
    """dry-bass / band-guard switches, read by the engine scripts (env is inherited)."""
    os.environ["BREKEM_DRY_BASS"] = "1" if dry else "0"
    os.environ["BREKEM_GUARD"] = "1" if guard else "0"


def _style_list(styles):
    if styles is True:
        return list(STYLE_IDS)
    return [s for s in (styles or []) if s in STYLE_IDS]


def _safe_tag(path):
    b = os.path.splitext(os.path.basename(path))[0]
    b = re.sub(r"\s*master$", "", b, flags=re.I)
    b = re.sub(r"[^A-Za-z0-9 _.\-]", "", b).strip().replace(" ", "_")
    return (b or "track")[:60]


def _parse(out):
    okm = OKN_RE.search(out); dm = DELTA_RE.search(out)
    ok = int(okm.group(1)) if okm else -1
    verd = {}
    for ax, lbl in AX_LBL.items():
        m = re.search(r"\[(OK |XX )\] " + re.escape(lbl), out)
        verd[ax] = (m.group(1).strip() == "OK") if m else None
    d = {}
    if dm:
        d = dict(low=float(dm.group(1)), pres=float(dm.group(2)), air=float(dm.group(3)),
                 I=float(dm.group(4)), corr=float(dm.group(5)))
    return ok, d, verd


def _next_params(sh, air, nar, pr, wd, d, verd):
    if verd.get("low") is False and "low" in d:
        sh = max(-6.0, min(6.0, sh - 1.9 * d["low"]))
    if verd.get("air") is False and "air" in d:
        air = max(-8.0, min(2.0, air - 2.0 * d["air"]))
    if verd.get("pres") is False and "pres" in d:
        pr = max(-6.0, min(3.0, pr - 1.7 * d["pres"]))
    if verd.get("stereo") is False:
        c = d.get("corr", 0.0)
        if c >= 0.025:
            wd = 1.16 if wd == 0.0 else min(1.5, wd + 0.08)
        else:
            nar = 0.78 if nar == 0.0 else min(0.86, nar + 0.03)
    return round(sh, 2), round(air, 2), round(nar, 2), round(pr, 2), round(wd, 2)


def _tonal(d):
    return sum(abs(d.get(k, 9)) for k in ("low", "pres", "air")) if d else 99.0


def _cleanup_keep():
    for d in glob.glob(os.path.join(E.WORK, "keep_*")):
        shutil.rmtree(d, ignore_errors=True)


def _snapshot(stage):
    snap = {}
    keep = os.path.join(E.WORK, "keep_" + os.path.basename(stage) + f"_{id(stage)}")
    os.makedirs(keep, exist_ok=True)
    for k in DELIV:
        s = os.path.join(stage, k + ".wav")
        if os.path.exists(s):
            d = os.path.join(keep, k + ".wav")
            shutil.copy2(s, d)
            snap[k] = d
    return snap


def _refine(par, d):
    sh, air, nar, pr, wd = par
    picks = sorted((abs(d[a]), a) for a in ("low", "pres", "air") if a in d and abs(d[a]) >= 1.2)
    if not picks:
        return None
    ax = picks[-1][1]
    if ax == "low":
        sh = max(-6.0, min(6.0, sh - 1.4 * d["low"]))
    elif ax == "air":
        air = max(-8.0, min(2.0, air - 1.5 * d["air"]))
    else:
        pr = max(-6.0, min(3.0, pr - 1.4 * d["pres"]))
    return round(sh, 2), round(air, 2), round(pr, 2)


def _prep(audio, tag, sep, shifts, log):
    """separate into all the stems the model gives (cached per song + model)."""
    return E.run_engine("prep.py", [os.path.abspath(audio), tag, sep or SEP_DEFAULT, str(max(1, int(shifts)))],
                        on_line=lambda s: log("  " + s))


def _variants(tag, outdir, log, styles=True):
    """the song in the picked master styles + COMPARE.html (see engine/variants.py)."""
    ids = _style_list(styles)
    if not ids:
        return None
    vd = os.path.join(os.path.abspath(outdir), "VARIANTS")
    log(f"--- master styles: {', '.join(ids)}")
    rc = E.run_engine("variants.py", [tag, vd, ",".join(ids)], on_line=lambda s: log("  " + s))
    if rc != 0:
        log("!! variants failed")
    return vd


def _encode_extras(folder, log):
    import subprocess
    ff = E.FFMPEG
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for kind in ("MASTER", "APPLE DIGITAL MASTER"):
        src = os.path.join(folder, kind + ".wav")
        if not os.path.exists(src):
            continue
        base = os.path.join(folder, kind)
        subprocess.run([ff, "-v", "error", "-y", "-i", src, "-c:a", "flac",
                        "-compression_level", "8", base + ".flac"], creationflags=cf)
        subprocess.run([ff, "-v", "error", "-y", "-i", src, "-c:a", "libmp3lame",
                        "-b:a", "320k", "-id3v2_version", "3", base + ".mp3"], creationflags=cf)
    log("  + FLAC/MP3 (MASTER, APPLE DIGITAL MASTER)")


# ------------------------------------------------------------------ master (ref)
def _master_noref(audio, outdir, log, sep=None, shifts=1, variants=None):
    tag = _safe_tag(audio)
    log(f"=== {os.path.basename(audio)}  (no references -> self master)")
    rc = _prep(audio, tag, sep, shifts, log)
    if rc != 0:
        log("!! Separation failed."); return {"ok": -1, "reason": "prep-failed"}
    os.makedirs(outdir, exist_ok=True)
    stage = os.path.join(E.WORK, "nrstage_" + tag)
    shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage, exist_ok=True)
    out = []
    rc = E.run_engine("noref.py", [tag + " master.wav", stage, ""],
                      on_line=lambda s: (out.append(s), log("  " + s)))
    m = re.search(r"(\d+)/4 absolute targets met", "\n".join(out))
    score = int(m.group(1)) if m else -1
    for k in DELIV:
        s = os.path.join(stage, k + ".wav")
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(outdir, k + ".wav"))
    _encode_extras(outdir, log)
    shutil.rmtree(stage, ignore_errors=True)
    if variants:
        _variants(tag, outdir, log, variants)
    log(f"=> DONE {os.path.basename(audio)}  {score}/4 targets  -> {outdir}")
    return {"ok": score, "mode": "noref", "outdir": outdir}


def master_one(audio, outdir, care=True, log=print, sep=None, shifts=1, variants=None,
               dry=True, guard=True):
    """variants: list of style ids (or True = all) -> <outdir>/VARIANTS."""
    E.apply_env()
    _opts(dry, guard)
    if not E.have_refs():
        return _master_noref(audio, outdir, log, sep, shifts, variants)
    tag = _safe_tag(audio)
    log(f"=== {os.path.basename(audio)}  (tag={tag})")
    rc = _prep(audio, tag, sep, shifts, log)
    if rc != 0:
        log("!! Separation failed."); return {"ok": -1, "reason": "prep-failed"}

    name = tag + " master.wav"
    os.makedirs(outdir, exist_ok=True)
    stage = os.path.join(E.WORK, "stage_" + tag)
    attempts = 6 if care else 3
    sh, air, nar, pr, wd = 1.5, 0.0, 0.0, 0.0, 0.0
    best = None
    seen = set()
    for i in range(1, attempts + 1):
        shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage, exist_ok=True)
        out = []
        E.run_engine("track_v2.py",
                     [name, stage, "", f"{sh:.2f}", f"{air:.2f}", f"{nar:.2f}", f"{pr:.2f}", f"{wd:.2f}"],
                     on_line=lambda s: (out.append(s), log("  " + s)))
        ok, d, verd = _parse("\n".join(out))
        have4 = all(os.path.exists(os.path.join(stage, k + ".wav")) for k in DELIV)
        log(f"  attempt {i}: {ok}/6  tonal={_tonal(d):.1f}  params=({sh},{air},{nar},{pr},{wd})")
        if best is None or ok > best[0] or (ok == best[0] and _tonal(d) < _tonal(best[3])):
            best = (ok, (sh, air, nar, pr, wd), _snapshot(stage), d)
        if ok >= 6 and have4:
            break
        seen.add((sh, air, nar, pr, wd))
        sh, air, nar, pr, wd = _next_params(sh, air, nar, pr, wd, d, verd)
        if (sh, air, nar, pr, wd) in seen:
            log("  no new params -> stop"); break

    bok, bpar, bsnap, bd = best
    if care and bok >= 6 and _tonal(bd) >= 1.2:
        rp = _refine(bpar, bd)
        if rp:
            sh2, air2, pr2 = rp
            shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage, exist_ok=True)
            out = []
            E.run_engine("track_v2.py",
                         [name, stage, "", f"{sh2:.2f}", f"{air2:.2f}", f"{bpar[2]:.2f}", f"{pr2:.2f}", f"{bpar[4]:.2f}"],
                         on_line=lambda s: (out.append(s), log("  " + s)))
            ok, d, _ = _parse("\n".join(out))
            have4 = all(os.path.exists(os.path.join(stage, k + ".wav")) for k in DELIV)
            if ok >= 6 and have4 and _tonal(d) < _tonal(bd):
                log("  polish accepted")
                best = (ok, (sh2, air2, bpar[2], pr2, bpar[4]), _snapshot(stage), d)

    bok, bpar, bsnap, bd = best
    for k in DELIV:
        s = bsnap.get(k)
        if s and os.path.exists(s):
            shutil.copy2(s, os.path.join(outdir, k + ".wav"))
    _encode_extras(outdir, log)
    shutil.rmtree(stage, ignore_errors=True)
    _cleanup_keep()
    if variants:
        _variants(tag, outdir, log, variants)
    log(f"=> DONE {os.path.basename(audio)}  {bok}/6  tonal {_tonal(bd):.1f}  -> {outdir}")
    return {"ok": bok, "tonal": _tonal(bd), "params": bpar, "outdir": outdir}


def batch(folder, outroot, care=True, log=print, sep=None, shifts=1, variants=None,
          dry=True, guard=True):
    files = sorted({p for e in AUDIO_EXT for p in glob.glob(os.path.join(folder, "*" + e))})
    if not files:
        log("!! No audio in the folder."); return
    log(f"=== BATCH: {len(files)} songs ===")
    res = []
    for i, f in enumerate(files, 1):
        name = os.path.splitext(os.path.basename(f))[0]
        od = os.path.join(outroot, f"{i:02d} - {name}")
        log(f"\n----- [{i}/{len(files)}] {name} -----")
        r = master_one(f, od, care=care, log=log, sep=sep, shifts=shifts, variants=variants,
                       dry=dry, guard=guard)
        res.append((name, r.get("ok", -1)))
    log("\n=== BATCH SUMMARY ===")
    for name, k in res:
        log(f"  {k}  {name}")


def _stem_styles(pm, voxfile, outdir, styles, log):
    """styles for the stems tab: stemmix.py's own groups become the stem cache."""
    if not _style_list(styles):
        return
    import numpy as np, soundfile as sf
    tag = "sm_" + _safe_tag(voxfile)
    sd = os.path.join(E.STEMS, tag)
    shutil.rmtree(sd, ignore_errors=True); os.makedirs(sd, exist_ok=True)
    vox, sr = sf.read(os.path.join(pm, "VOX_premix.wav"), dtype="float32", always_2d=True)
    sf.write(os.path.join(sd, "vocals.flac"), np.clip(vox, -1, 1), sr, subtype="PCM_24")
    sf.write(os.path.join(sd, "vocals_proc.wav"), vox, sr, subtype="FLOAT")   # already clean
    inst, _ = sf.read(os.path.join(pm, "INSTRUMENTAL_premix.wav"), dtype="float32", always_2d=True)
    sf.write(os.path.join(sd, "no_vocals.flac"), np.clip(inst, -1, 1), sr, subtype="PCM_24")
    for g in ("drums", "bass", "other"):
        p = os.path.join(pm, "groups", g + ".wav")
        if os.path.exists(p):
            a, _ = sf.read(p, dtype="float32", always_2d=True)
            sf.write(os.path.join(sd, g + ".flac"), np.clip(a, -1, 1), sr, subtype="PCM_24")
    _variants(tag, outdir, log, styles)


def stemmix(stemdir, voxfile, outdir, vox=-3.0, care=True, log=print, variants=None, dry=True, guard=True):
    E.apply_env()
    _opts(dry, guard)
    os.makedirs(outdir, exist_ok=True)
    pm = os.path.join(E.WORK, "sm_" + _safe_tag(voxfile))
    os.makedirs(pm, exist_ok=True)
    log("=== MIX FROM STEMS ===")
    rc = E.run_engine("stemmix.py", [os.path.abspath(stemdir), os.path.abspath(voxfile), pm, f"{vox:.2f}"],
                      on_line=lambda s: log("  " + s))
    if rc != 0:
        log("!! stemmix failed."); return
    MIX = os.path.join(pm, "MIX_premix.wav")
    INST = os.path.join(pm, "INSTRUMENTAL_premix.wav")
    VOX = os.path.join(pm, "VOX_premix.wav")

    if not E.have_refs():
        log("  no references -> no-reference master of the mix")
        stage = os.path.join(E.WORK, "nds_stage")
        shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage, exist_ok=True)
        E.run_engine("noref_daw.py", [MIX, INST, VOX, stage], on_line=lambda s: log("  " + s))
        for k in DELIV:
            s = os.path.join(stage, k + ".wav")
            if os.path.exists(s):
                shutil.copy2(s, os.path.join(outdir, k + ".wav"))
        _encode_extras(outdir, log)
        shutil.copy2(MIX, os.path.join(outdir, "mix premaster.wav"))
        shutil.rmtree(stage, ignore_errors=True)
        _stem_styles(pm, voxfile, outdir, variants, log)
        log(f"=> DONE mix (no-ref)  -> {outdir}")
        return

    sh, air, pr, corr_m, nar = 1.5, 0.0, 0.0, 0.80, 0.0
    best = None; seen = set()
    for i in range(1, (5 if care else 3) + 1):
        stage = os.path.join(E.WORK, f"dsstage_{i}")
        shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage, exist_ok=True)
        out = []
        E.run_engine("daw_song.py",
                     [MIX, INST, VOX, stage, f"{sh:.2f}", f"{air:.2f}", f"{pr:.2f}", f"{corr_m:.2f}", f"{nar:.2f}"],
                     on_line=lambda s: (out.append(s), log("  " + s)))
        ok, d, verd = _parse("\n".join(out))
        have4 = all(os.path.exists(os.path.join(stage, k + ".wav")) for k in DELIV)
        log(f"  attempt {i}: {ok}/6  tonal={_tonal(d):.1f}")
        if best is None or ok > best[0] or (ok == best[0] and _tonal(d) < _tonal(best[3])):
            best = (ok, (sh, air, pr, corr_m, nar), _snapshot(stage), d)
        if ok >= 6 and have4:
            break
        seen.add((sh, air, pr, corr_m, nar))
        sh, air, nar, pr, _wd = _next_params(sh, air, nar, pr, 0.0, d, verd)
        if (sh, air, pr, corr_m, nar) in seen:
            break
    bok, bpar, bsnap, bd = best
    for k in DELIV:
        s = bsnap.get(k)
        if s and os.path.exists(s):
            shutil.copy2(s, os.path.join(outdir, k + ".wav"))
    _encode_extras(outdir, log)
    shutil.copy2(MIX, os.path.join(outdir, "mix premaster.wav"))
    _cleanup_keep()
    _stem_styles(pm, voxfile, outdir, variants, log)
    log(f"=> DONE mix  {bok}/6  tonal {_tonal(bd):.1f}  -> {outdir}")


# ------------------------------------------------------------------ distribute
def _ebur(path):
    import subprocess
    r = subprocess.run([E.FFMPEG, "-hide_banner", "-nostats", "-i", path,
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    s = r.stderr.split("Summary:")[-1]
    def g(k, u):
        m = re.search(k + r":\s*(-?[\d.]+)\s*" + u, s)
        return float(m.group(1)) if m else None
    return g("I", "LUFS"), g("LRA", "LU"), g("Peak", "dBFS")


# ffmpeg feature fallbacks, best first: alimiter delay compensation (ffmpeg >= 5.1) and the
# soxr resampler (not in every ffmpeg build). The first combination that works is kept.
_MODES = [(":latency=1", ":resampler=soxr:precision=28"), ("", ":resampler=soxr:precision=28"),
          (":latency=1", ""), ("", "")]
_MODE = [0]


def _limit(src, dst, gain_db, tp):
    """one static gain for the whole song -> 4x-oversampled lookahead limiter -> 48k
    limiter a hair under the target true-peak. No AGC anywhere."""
    import subprocess
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    while _MODE[0] < len(_MODES):
        lat, rs = _MODES[_MODE[0]]
        af = (f"volume={gain_db:.2f}dB,aresample=192000{rs},"
              f"alimiter=limit={10 ** ((tp - 0.5) / 20.0):.4f}:level=0:asc=1{lat},"
              f"aresample=48000{rs},"
              f"alimiter=limit={10 ** ((tp - 0.3) / 20.0):.4f}:level=0{lat}")
        r = subprocess.run([E.FFMPEG, "-v", "error", "-y", "-i", src, "-af", af,
                            "-ar", "48000", "-c:a", "pcm_s24le", dst], creationflags=cf)
        if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 44:
            return True
        _MODE[0] += 1
    _MODE[0] = len(_MODES) - 1
    return False


def _fade_tail(path, ms=15.0):
    """a song that stops on a non-zero sample clicks; fade the last few ms to zero."""
    try:
        import numpy as np, soundfile as sf
        y, s = sf.read(path, dtype="float64", always_2d=True)
        k = min(len(y), int(ms / 1000 * s))
        if k < 2 or np.max(np.abs(y[-k:])) < 1e-4:
            return
        y[-k:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, k)))[:, None]
        sf.write(path, y, s, subtype="PCM_24")
    except Exception:
        pass


def _regulate(src, dst_dir, kind, target_lufs, tp, log):
    """static gain + true-peak limit -> <kind> {48k24,44k16}.wav + <kind>.mp3
    (ffmpeg's loudnorm was used here before: for loud targets it can never stay in
    'linear' mode, falls back to its dynamic AGC and pumps - the level goes down and
    up, worst on quiet endings. A single gain, re-measured, can't do that.)"""
    import subprocess
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    w48 = os.path.join(dst_dir, f"{kind} 48k24.wav")
    w44 = os.path.join(dst_dir, f"{kind} 44k16.wav")
    mp3 = os.path.join(dst_dir, f"{kind}.mp3")
    i0 = _ebur(src)[0]
    gain = target_lufs - (i0 if i0 is not None else -14.0)
    for _ in range(3):                      # the limiter eats some gain: re-aim from the source
        gain = max(-20.0, min(20.0, gain))
        if not _limit(src, w48, gain, tp):
            log(f"  !! {kind}: ffmpeg failed"); return None, None, None
        i1 = _ebur(w48)[0]
        if i1 is None or abs(i1 - target_lufs) <= 0.3:
            break
        gain += target_lufs - i1
    _fade_tail(w48)
    subprocess.run([E.FFMPEG, "-v", "error", "-y", "-i", w48,
                    "-af", f"aresample=44100{_MODES[_MODE[0]][1]}:dither_method=triangular_hp",
                    "-c:a", "pcm_s16le", w44], creationflags=cf)
    subprocess.run([E.FFMPEG, "-v", "error", "-y", "-i", w48,
                    "-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3", mp3],
                   creationflags=cf)
    i1, lra1, tp1 = _ebur(w48)
    log(f"  {kind:12} -> {i1:.1f} LUFS  TP {tp1:.1f} dBTP" if i1 is not None else f"  {kind}: done")
    return i1, lra1, tp1


def distribute(audio, outdir, target_lufs=-9.5, tp=-1.0, split=True, clean=False, log=print,
               sep=None, variants=None, dry=True, guard=True):
    """Make a finished audio distribution-ready: one static gain to the target loudness
    + true-peak limit. Outputs MASTER (and, when split=True, INSTRUMENTAL + ACAPELLA via Demucs),
    each as WAV 48k/24 + WAV 44.1k/16 + MP3 320. clean=True runs an AI clean pass
    (denoise/dereverb + de-breath + de-plosive on the vocal) before regulating.
    No references, no tonal re-balancing. guard=True keeps each band's peaks inside the
    file's own range before the limiter; variants -> the picked master styles too."""
    E.apply_env()
    _opts(dry, guard)
    os.makedirs(outdir, exist_ok=True)
    name = os.path.splitext(os.path.basename(audio))[0]
    i0, lra0, tp0 = _ebur(audio)
    log(f"=== {'AI CLEAN + ' if clean else ''}DISTRIBUTE: {name} ===")
    log(f"  input: {i0:.1f} LUFS  peak {tp0:.1f} dBFS  LRA {lra0:.1f}" if i0 is not None
        else "  input: not measurable")

    master_src = audio
    vc = ic = None
    tag = _safe_tag(audio)
    if split or clean or _style_list(variants):
        log("  separating (Demucs)... this takes a few minutes")
        rc = _prep(audio, tag, sep, 1, log)
        vc = os.path.join(E.STEMS, tag, "vocals.flac")
        ic = os.path.join(E.STEMS, tag, "no_vocals.flac")
        if rc != 0 or not (os.path.exists(vc) and os.path.exists(ic)):
            log("  !! separation failed; MASTER only, no clean")
            vc = ic = None
        elif clean:
            log("  AI clean on the vocal...")
            E.run_engine("clean.py", [tag], on_line=lambda s: log("  " + s))
            mc = os.path.join(E.STEMS, tag, "mix_clean.wav")
            vcl = os.path.join(E.STEMS, tag, "vocals_clean.flac")
            if os.path.exists(mc):
                master_src = mc
            if os.path.exists(vcl):
                vc = vcl

    def _g(src, kind):
        if not guard:
            return src
        dst = os.path.join(E.WORK, f"guard_{tag}_{kind}.wav")
        rc = E.run_engine("guard.py", [os.path.abspath(src), dst], on_line=lambda s: log(f"  {kind}: " + s))
        return dst if rc == 0 and os.path.exists(dst) else src

    res = {"MASTER": _regulate(_g(master_src, "MASTER"), outdir, "MASTER", target_lufs, tp, log)}
    if split and vc and ic:
        res["INSTRUMENTAL"] = _regulate(_g(ic, "INSTRUMENTAL"), outdir, "INSTRUMENTAL", target_lufs, tp, log)
        res["ACAPELLA"] = _regulate(_g(vc, "ACAPELLA"), outdir, "ACAPELLA", target_lufs, tp, log)
    for k in ("MASTER", "INSTRUMENTAL", "ACAPELLA"):
        try: os.remove(os.path.join(E.WORK, f"guard_{tag}_{k}.wav"))
        except OSError: pass
    if vc and ic:
        _variants(tag, outdir, log, variants)

    with open(os.path.join(outdir, "_INFO.txt"), "w", encoding="utf-8") as f:
        f.write(f"{name}\ninput: {i0} LUFS / peak {tp0} dBFS / LRA {lra0}\n"
                f"target: {target_lufs} LUFS, true-peak <= {tp} dBTP\n"
                f"AI clean: {'yes' if clean else 'no'}   band guard: {'yes' if guard else 'no'}\n\n")
        for k, v in res.items():
            f.write(f"{k}: {v[0]} LUFS / TP {v[2]} dBTP / LRA {v[1]}\n")
        f.write("\nper track: WAV 48k/24, WAV 44.1k/16, MP3 320\n")
    log(f"=> DONE -> {outdir}")
    return {"in_lufs": i0, "outdir": outdir, "tracks": list(res)}


def distribute_batch(folder, outroot, target_lufs=-9.5, tp=-1.0, split=True, clean=False, log=print,
                     sep=None, variants=None, dry=True, guard=True):
    files = sorted({p for e in AUDIO_EXT for p in glob.glob(os.path.join(folder, "*" + e))})
    if not files:
        log("!! No audio in the folder."); return
    log(f"=== {'AI CLEAN + ' if clean else ''}DISTRIBUTE BATCH: {len(files)} files ===")
    for i, f in enumerate(files, 1):
        name = os.path.splitext(os.path.basename(f))[0]
        od = os.path.join(outroot, f"{i:02d} - {name}")
        log(f"\n--- [{i}/{len(files)}] {name} ---")
        distribute(f, od, target_lufs=target_lufs, tp=tp, split=split, clean=clean, log=log, sep=sep,
                   variants=variants, dry=dry, guard=guard)


def _cli():
    ap = argparse.ArgumentParser(prog="brekem_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("master"); a.add_argument("audio"); a.add_argument("outdir"); a.add_argument("--fast", action="store_true")
    b = sub.add_parser("batch"); b.add_argument("folder"); b.add_argument("outdir"); b.add_argument("--fast", action="store_true")
    for p in (a, b):
        p.add_argument("--sep", choices=SEP_MODELS, default=SEP_DEFAULT)
        p.add_argument("--shifts", type=int, default=1)
    c = sub.add_parser("stemmix"); c.add_argument("stemdir"); c.add_argument("voxfile"); c.add_argument("outdir"); c.add_argument("--vox", type=float, default=-3.0)
    d = sub.add_parser("distribute"); d.add_argument("path"); d.add_argument("outdir")
    for p in (a, b, c, d):
        p.add_argument("--styles", default="", help="comma list of " + ",".join(STYLE_IDS) + " or 'all'")
        p.add_argument("--no-dry-bass", action="store_true"); p.add_argument("--no-guard", action="store_true")
    d.add_argument("--lufs", type=float, default=-9.5); d.add_argument("--tp", type=float, default=-1.0)
    d.add_argument("--no-split", action="store_true"); d.add_argument("--clean", action="store_true")
    d.add_argument("--sep", choices=SEP_MODELS, default=SEP_DEFAULT)
    ns = ap.parse_args()
    st = True if ns.styles.strip().lower() == "all" else [x.strip() for x in ns.styles.split(",") if x.strip()]
    kw = dict(variants=st, dry=not ns.no_dry_bass, guard=not ns.no_guard)
    if ns.cmd == "master":
        master_one(ns.audio, ns.outdir, care=not ns.fast, sep=ns.sep, shifts=ns.shifts, **kw)
    elif ns.cmd == "batch":
        batch(ns.folder, ns.outdir, care=not ns.fast, sep=ns.sep, shifts=ns.shifts, **kw)
    elif ns.cmd == "stemmix":
        stemmix(ns.stemdir, ns.voxfile, ns.outdir, vox=ns.vox, **kw)
    elif ns.cmd == "distribute":
        sp = not ns.no_split
        fn = distribute_batch if os.path.isdir(ns.path) else distribute
        fn(ns.path, ns.outdir, target_lufs=ns.lufs, tp=ns.tp, split=sp, clean=ns.clean, sep=ns.sep, **kw)


if __name__ == "__main__":
    _cli()
