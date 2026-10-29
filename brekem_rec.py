"""BREKEM STUDIO - recorder: sing over a beat on a headset, takes come out lined up with the beat.

The beat plays and the mic records in ONE full-duplex stream, so both run on the same clock.
What the stream can't see is the round trip (beat leaves the PC -> your ear -> your voice ->
back in the mic): that is measured once per mic/headphones pair (calibrate) and every take is
shifted back by it. Takes are saved full song length (silence before a punch-in start), mono,
24-bit, at the device rate - ready for 'Mix from stems'.
"""
import os
import re
import json
import glob
import shutil
import subprocess
import threading

import numpy as np
import soundfile as sf

import brekem_env as E

TAKES = os.path.join(E.DATA, "takes")
_CFG = os.path.join(E.DATA, "recorder.json")
CLIP = 0.98


def _sd():
    import sounddevice   # imported late: a missing PortAudio must not stop the rest of the app
    return sounddevice


# ---------------------------------------------------------------- devices
def _apis():
    """WASAPI first (lowest latency in shared mode), then the others."""
    sd = _sd()
    names = [a["name"] for a in sd.query_hostapis()]
    order = [i for i, n in enumerate(names) if "WASAPI" in n]
    return order or list(range(len(names)))


def devices(kind):
    """[(device index, label)] of 'input' or 'output' devices on the preferred host API."""
    sd = _sd()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    api = _apis()[0]
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["hostapi"] == api and d[key] > 0]


def default_device(kind):
    sd = _sd()
    i = sd.query_hostapis(_apis()[0])["default_" + kind + "_device"]
    return i if i is not None and i >= 0 else None


def matching_output(in_dev):
    """the headphones of the same headset as this mic (same name in brackets), or None."""
    sd = _sd()
    m = re.search(r"\((.+?)\)", sd.query_devices(in_dev)["name"])
    if not m:
        return None
    return next((i for i, _ in devices("output") if m.group(1) in sd.query_devices(i)["name"]), None)


def rescan():
    """PortAudio lists the devices once, when it starts. A USB headset that Windows (or the
    headset's own software) re-plugs since then leaves that list stale and opening it fails -
    restart PortAudio so the list is read again."""
    sd = _sd()
    sd._terminate()
    sd._initialize()


def find(kind, name):
    """the index of the device with this name now (indices move after a rescan), or None."""
    return next((i for i, n in devices(kind) if n == name), None)


def device_rate(in_dev, out_dev):
    """the rate both devices run at in shared mode (the output's mixer rate)."""
    sd = _sd()
    return int(sd.query_devices(out_dev)["default_samplerate"] or
               sd.query_devices(in_dev)["default_samplerate"] or 48000)


def _in_channels(in_dev):
    return max(1, min(2, int(_sd().query_devices(in_dev)["max_input_channels"])))


# ---------------------------------------------------------------- settings (latency per pair)
def _pair_key(in_dev, out_dev):
    sd = _sd()
    return sd.query_devices(in_dev)["name"] + " | " + sd.query_devices(out_dev)["name"]


def _load_cfg():
    try:
        with open(_CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def saved_latency_ms(in_dev, out_dev):
    """the measured round trip for this mic/headphones pair, or None if never calibrated."""
    return _load_cfg().get("latency_ms", {}).get(_pair_key(in_dev, out_dev))


def save_latency_ms(in_dev, out_dev, ms):
    c = _load_cfg()
    c.setdefault("latency_ms", {})[_pair_key(in_dev, out_dev)] = round(float(ms), 1)
    with open(_CFG, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1)


# ---------------------------------------------------------------- audio helpers
def load_audio(path, sr):
    """any audio file -> float32 (n, 2) at sr (ffmpeg decodes mp3 / m4a / opus too)."""
    os.makedirs(E.WORK, exist_ok=True)
    tmp = os.path.join(E.WORK, "rec_decode.wav")
    r = subprocess.run([E.FFMPEG, "-v", "error", "-y", "-i", path, "-ar", str(sr), "-ac", "2",
                        "-c:a", "pcm_f32le", tmp],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError(f"could not read {os.path.basename(path)}: {r.stderr[-300:]}")
    x, _ = sf.read(tmp, dtype="float32", always_2d=True)
    os.remove(tmp)
    return x


def align(raw, lat, start, total):
    """recorded samples -> a take on the beat's timeline. raw[i] was sung against beat sample
    start + i - lat, so drop the first lat samples and place the rest at 'start'."""
    out = np.zeros(total, dtype=np.float32)
    v = raw[max(0, lat):]
    n = max(0, min(len(v), total - start))
    out[start:start + n] = v[:n]
    return out


def onsets(x, sr, n, gap_s):
    """sample positions of the n loudest clicks, at least gap_s apart (calibration)."""
    k = max(1, int(0.002 * sr))   # 2 ms energy envelope: one smooth hump per click
    work = np.convolve(x.astype(np.float64) ** 2, np.ones(k) / k, mode="same")
    gap = int(gap_s * sr)
    found = []
    for _ in range(n):
        i = int(np.argmax(work))
        if work[i] <= 0:
            break
        found.append(i)
        work[max(0, i - gap // 2):i + gap // 2] = 0
    return sorted(found)


def click_train(sr, n=6, every_s=0.5, lead_s=0.5):
    """n short 2 kHz clicks, the first after lead_s. Returns (signal mono, click positions)."""
    total = int(sr * (lead_s + every_s * (n + 1)))
    x = np.zeros(total, dtype=np.float32)
    ln = int(0.004 * sr)
    t = np.arange(ln) / sr
    click = (np.sin(2 * np.pi * 2000 * t) * np.hanning(ln)).astype(np.float32) * 0.8
    pos = [int(sr * (lead_s + k * every_s)) for k in range(n)]
    for p in pos:
        x[p:p + ln] += click
    return x, pos


def write_take(path, take, sr):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, take, sr, subtype="PCM_24")


def takes_dir(beat):
    tag = re.sub(r"[^A-Za-z0-9 _.\-]", "", os.path.splitext(os.path.basename(beat))[0]).strip()
    return os.path.join(TAKES, (tag.replace(" ", "_") or "beat")[:60])


def list_takes(beat):
    return sorted(glob.glob(os.path.join(takes_dir(beat), "take_*.wav")))


def next_take_path(beat):
    nums = [int(m.group(1)) for p in list_takes(beat)
            if (m := re.search(r"take_(\d+)", os.path.basename(p)))]
    return os.path.join(takes_dir(beat), f"take_{(max(nums) + 1) if nums else 1:02d}.wav")


# ---------------------------------------------------------------- duplex session
class Session:
    """plays `play` (n, 2) on out_dev while recording in_dev, both in one stream.
    on_level(peak 0..1, seconds) is called from the audio thread - keep it cheap."""

    def __init__(self, play, sr, in_dev, out_dev, monitor=0.0, on_level=None, on_end=None):
        self.play, self.sr = play, sr
        self.in_dev, self.out_dev = in_dev, out_dev
        self.monitor = float(monitor)
        self.on_level, self.on_end = on_level, on_end
        self.pos = 0
        self.chunks = []
        self.peak = 0.0
        self.clipped = False
        self.stream = None
        self.latency = (0.0, 0.0)
        self.done = threading.Event()

    def _cb(self, indata, outdata, frames, time, status):
        sd = _sd()
        mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
        self.chunks.append(mono.copy())
        pk = float(np.max(np.abs(mono))) if len(mono) else 0.0
        self.peak = max(self.peak * 0.85, pk)
        if pk >= CLIP:
            self.clipped = True
        seg = self.play[self.pos:self.pos + frames]
        outdata[:len(seg)] = seg
        outdata[len(seg):] = 0
        if self.monitor > 0:
            outdata += (mono * self.monitor)[:, None]
        self.pos += frames
        if self.on_level:
            self.on_level(self.peak, self.pos / self.sr)
        if self.pos >= len(self.play):
            raise sd.CallbackStop

    def _finished(self):
        self.done.set()
        if self.on_end:
            self.on_end()

    def _open(self):
        sd = _sd()
        self.stream = sd.Stream(device=(self.in_dev, self.out_dev), samplerate=self.sr,
                                channels=(_in_channels(self.in_dev), 2), dtype="float32",
                                latency="low", callback=self._cb, finished_callback=self._finished)
        self.stream.start()

    def start(self):
        sd = _sd()
        names = sd.query_devices(self.in_dev)["name"], sd.query_devices(self.out_dev)["name"]
        try:
            self._open()
        except sd.PortAudioError:
            # stale device list (headset re-plugged since PortAudio started): read it again
            self.stream = None
            rescan()
            i, o = find("input", names[0]), find("output", names[1])
            if i is None or o is None:
                raise RuntimeError(f"{names[0] if i is None else names[1]} is not connected")
            self.in_dev, self.out_dev = i, o
            self._open()

    def stop(self):
        st, self.stream = self.stream, None
        if st is not None:
            self.latency = st.latency
            st.stop()
            st.close()
        self.done.set()

    def reported_latency_s(self):
        """what the driver says the round trip is (input + output buffers)."""
        lat = self.stream.latency if self.stream is not None else self.latency
        return float(lat[0] + lat[1])

    def recorded(self):
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)


def calibrate(in_dev, out_dev, log=print):
    """play clicks with the earcup held against the mic. Returns (round trip ms, mic, headphones):
    the device indices it really used (they move if the devices had to be rescanned)."""
    sr = device_rate(in_dev, out_dev)
    x, pos = click_train(sr)
    s = Session(np.repeat(x[:, None], 2, 1), sr, in_dev, out_dev)
    s.start()
    s.done.wait(len(x) / sr + 3)
    s.stop()
    rec = s.recorded()
    pos = onsets(x, sr, len(pos), 0.5)   # same detector on what was played: its bias cancels out
    got = onsets(rec, sr, len(pos), 0.5)
    if len(got) < len(pos) or float(np.max(np.abs(rec))) < 0.02:
        raise RuntimeError("did not hear the clicks - hold the earcup right on the mic and turn "
                           "the headphones up")
    d = np.array(got) - np.array(pos)
    if np.ptp(d) > 0.004 * sr:   # clicks must agree within 4 ms, else it heard something else
        raise RuntimeError("the clicks did not line up (noise in the room?) - try again")
    ms = float(np.median(d)) / sr * 1000.0
    log(f"round trip measured: {ms:.1f} ms  (driver says {s.reported_latency_s() * 1000:.1f} ms)")
    return ms, s.in_dev, s.out_dev


def beat_stems(beat, split, sep, log):
    """the folder of .wav stems 'Mix from stems' wants. split: Demucs separates the beat
    (cached), else the whole beat is one 'other' stem."""
    import brekem_cli as C
    tag = "rec_" + C._safe_tag(beat)
    d = os.path.join(E.WORK, tag + "_beatstems")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    if split:
        rc = C._prep(beat, tag, sep, 1, log)
        sdir = os.path.join(E.STEMS, tag)
        try:
            with open(os.path.join(sdir, "stems.json"), encoding="utf-8") as f:
                names = json.load(f).get("stems", [])
        except Exception:
            names = []
        if rc == 0 and names:
            for n in names:
                a, r = sf.read(os.path.join(sdir, n + ".flac"), dtype="float32", always_2d=True)
                # a vocal chop in the beat stays part of the beat, mixed with the 'other' chain
                out = "other_beatvox" if n == "vocals" else n
                sf.write(os.path.join(d, out + ".wav"), a, r, subtype="FLOAT")
            log(f"  beat split into: {', '.join(names)}")
            return d
        log("  !! beat separation failed - using the whole beat as one stem")
    sr = 48000
    sf.write(os.path.join(d, "other_beat.wav"), load_audio(beat, sr), sr, subtype="FLOAT")
    return d
