"""BREKEM STUDIO - GUI (tkinter, standard library only)."""
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import soundfile as sf

import brekem_env as E
import brekem_cli as C
import brekem_rec as R

APP = "BREKEM STUDIO"
PAD = 8
SEP_CHOICES = (  # label -> Demucs model used by prep.py
    ("4 stems, best quality (vocals / drums / bass / other)", "htdemucs_ft"),
    ("6 stems (+ guitar / piano, lower quality on those two)", "htdemucs_6s"),
    ("4 stems, fast", "htdemucs"),
)
STYLE_CHOICES = (  # id (brekem_cli.STYLE_IDS) -> box label
    ("cd", "CD Master"), ("clarity", "Clarity"), ("espacial", "Espacial"), ("punch", "Punch"),
    ("warm", "Warm"), ("club", "Club"), ("streaming", "Streaming -14"), ("signature", "BREKEM Signature"),
)
AUDIO_FT = (("Audio", "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.opus *.aif *.aiff *.wma"),
            ("All files", "*.*"))


class Console(tk.Text):
    def __init__(self, master):
        super().__init__(master, height=18, wrap="word", bg="#0f1113", fg="#d7dde3",
                         insertbackground="#d7dde3", font=("Consolas", 9), relief="flat")
        self.configure(state="disabled")
        self.q = queue.Queue()
        self.after(80, self._pump)

    def write(self, line):
        self.q.put(str(line))

    def _pump(self):
        n = 0
        while n < 400:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                break
            self.configure(state="normal")
            self.insert("end", line + "\n")
            self.see("end")
            self.configure(state="disabled")
            n += 1
        self.after(80, self._pump)


class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root, padding=PAD)
        self.root = root
        self.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.busy = False

        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky="nsew")
        self.tab_record(nb)
        self.tab_master(nb)
        self.tab_batch(nb)
        self.tab_stem(nb)
        self.tab_distrib(nb)
        self.tab_clean(nb)
        self.tab_styles(nb)
        self.tab_refs(nb)

        self.con = Console(self)
        self.con.grid(row=1, column=0, sticky="nsew", pady=(PAD, 0))
        self.status = ttk.Label(self, text="Ready")
        self.status.grid(row=2, column=0, sticky="w", pady=(4, 0))

        self.log(APP)
        self.log(f"user data   : {E.DATA}")
        self.log(f"references  : {E.REFS}")
        threading.Thread(target=self._say_gpu, daemon=True).start()
        self._refresh_refs()

    # ---------- helpers ----------
    def log(self, s):
        self.con.write(s)

    def _pick_file(self, var):
        p = filedialog.askopenfilename(filetypes=AUDIO_FT)
        if p:
            var.set(p)

    def _pick_dir(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    def _xbox(self, parent, label, value=False):
        """a toggle that reads [X] when on, [  ] when off."""
        var = tk.BooleanVar(value=value)
        b = tk.Checkbutton(parent, variable=var, indicatoron=False, anchor="w", relief="flat",
                           offrelief="flat", overrelief="groove", bd=1, padx=6, pady=2,
                           font=("Consolas", 10), selectcolor="#e0b04a", cursor="hand2")
        upd = lambda *_: b.configure(text=("[X] " if var.get() else "[  ] ") + label)
        var.trace_add("write", upd); upd()
        return b, var

    def _say_gpu(self):
        """find the NVIDIA GPU in the background (a few seconds) and say what runs where."""
        line = E.gpu_line()
        if not C._GPU_SAID:
            C._GPU_SAID.append(1); self.log(line)

    def _opts_panel(self, f, row, styles=()):
        """styles (each its own [X]) + dry bass / band guard / tuning / exciter [X]; returns a getter."""
        box = ttk.LabelFrame(f, text="Master styles  (mark with X the ones you want, each comes out separately)",
                             padding=6)
        box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        picks = []
        for i, (sid, lbl) in enumerate(STYLE_CHOICES):
            b, v = self._xbox(box, lbl, sid in styles)
            b.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 10))
            picks.append((sid, v))
        ext = ttk.LabelFrame(f, text="Extras", padding=6)
        ext.grid(row=row + 1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        b1, dry = self._xbox(ext, "Bass centred + dry (mono low end, tight tail, steady, out of the kick's way)", True)
        b1.grid(row=0, column=0, sticky="w")
        b2, grd = self._xbox(ext, "Band guard (vocal / beat / bass / mids / highs stay inside the song's own range)",
                             True)
        b2.grid(row=1, column=0, sticky="w")
        b3, tun = self._xbox(ext, "Natural pitch correction - auto-tune without the robot (key read from the beat, "
                                  "vibrato and slides kept)", False)
        b3.grid(row=2, column=0, sticky="w")
        b4, exc = self._xbox(ext, "Exciter - new harmonics: brighter, airier top + bass you hear on phones and "
                                  "earbuds (no hiss lifted)", False)
        b4.grid(row=3, column=0, sticky="w")
        return lambda: dict(variants=[sid for sid, v in picks if v.get()], dry=dry.get(), guard=grd.get(),
                            tune=tun.get(), exciter=exc.get())

    def _sep_row(self, f, row):
        """'Separation' dropdown; returns a getter for the chosen Demucs model."""
        var = tk.StringVar(value=SEP_CHOICES[0][0])
        ttk.Label(f, text="Separation:").grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(f, textvariable=var, state="readonly", values=[c[0] for c in SEP_CHOICES]).grid(
            row=row, column=1, sticky="ew", padx=6, pady=(6, 0))
        return lambda: dict(SEP_CHOICES).get(var.get(), SEP_CHOICES[0][1])

    def _run_bg(self, fn, needs_refs=True):
        if self.busy:
            messagebox.showinfo(APP, "A job is already running.")
            return
        if needs_refs and not E.have_refs():
            if not messagebox.askyesno(
                    APP, "No reference songs are set.\n\n"
                         "Continue with a NO-REFERENCE master (gets the best out of the "
                         "audio itself, no external target)?"):
                return
        self.busy = True
        self.status.configure(text="Working...  (a few minutes per song)")

        def wrap():
            try:
                fn()
            except Exception as e:
                self.log(f"!! ERROR: {e}")
            finally:
                self.busy = False
                self.root.after(0, lambda: self.status.configure(text="Ready"))

        threading.Thread(target=wrap, daemon=True).start()

    def _bg_then(self, fn, done):
        """fn() on a worker thread, then done(result, error) back on the Tk thread."""
        box = {}

        def work():
            try:
                box["r"] = fn()
            except Exception as e:
                box["e"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.root.after(60, poll)
            else:
                done(box.get("r"), box.get("e"))
        poll()

    # ---------- tab: record ----------
    def tab_record(self, nb):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text="Record")
        f.columnconfigure(1, weight=1)
        self.r_beat = tk.StringVar()
        self.r_in = tk.StringVar()
        self.r_out = tk.StringVar()
        self.r_start = tk.StringVar(value="0:00")
        self.r_beatvol = tk.DoubleVar(value=0.8)
        self.r_mon = tk.DoubleVar(value=0.0)
        self.r_fine = tk.DoubleVar(value=0.0)
        self.r_dir = tk.StringVar()
        self.r_vox_off = tk.DoubleVar(value=-3.0)
        self.r_sess = None        # the running Session (recording or playing back)
        self.r_beat_x = None      # (path, rate, audio) of the decoded beat

        ttk.Label(f, text="Beat:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.r_beat).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=self._rec_pick_beat).grid(row=0, column=2)

        ttk.Label(f, text="Mic:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.r_in_cb = ttk.Combobox(f, textvariable=self.r_in, state="readonly")
        self.r_in_cb.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(f, text="Refresh", command=self._rec_devices).grid(row=1, column=2, pady=(6, 0))
        ttk.Label(f, text="Headphones:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.r_out_cb = ttk.Combobox(f, textvariable=self.r_out, state="readonly")
        self.r_out_cb.grid(row=2, column=1, sticky="ew", padx=6, pady=(6, 0))
        for cb in (self.r_in_cb, self.r_out_cb):
            cb.bind("<<ComboboxSelected>>", lambda _e: self._rec_lat_label())

        lat = ttk.LabelFrame(f, text="Timing (voice lined up with the beat)", padding=6)
        lat.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        lat.columnconfigure(3, weight=1)
        self.r_lat_lbl = ttk.Label(lat, text="")
        self.r_lat_lbl.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Button(lat, text="Calibrate", command=self._rec_calibrate).grid(row=1, column=0, sticky="w",
                                                                           pady=(4, 0))
        ttk.Label(lat, text="Fine tune (ms, + = voice earlier):").grid(row=1, column=1, sticky="w", padx=(10, 0))
        self.r_fine_lbl = ttk.Label(lat, text="0", width=4)
        self.r_fine_lbl.grid(row=1, column=2)
        ttk.Scale(lat, from_=-60.0, to=60.0, variable=self.r_fine, orient="horizontal",
                  command=lambda v: self.r_fine_lbl.configure(text=f"{float(v):+.0f}")).grid(
            row=1, column=3, sticky="ew", padx=6)
        ttk.Label(lat, text="Calibrate once per headset: press it, then hold one earcup tight against the mic "
                            "(you will hear 6 clicks).", foreground="#7b8794").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        mix = ttk.Frame(f)
        mix.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        mix.columnconfigure(3, weight=1)
        mix.columnconfigure(5, weight=1)
        ttk.Label(mix, text="Start at (m:ss):").grid(row=0, column=0, sticky="w")
        ttk.Entry(mix, textvariable=self.r_start, width=6).grid(row=0, column=1, padx=6)
        ttk.Label(mix, text="Beat volume:").grid(row=0, column=2, sticky="e", padx=(10, 0))
        ttk.Scale(mix, from_=0.0, to=1.0, variable=self.r_beatvol, orient="horizontal").grid(
            row=0, column=3, sticky="ew", padx=6)
        ttk.Label(mix, text="Hear myself:").grid(row=0, column=4, sticky="e", padx=(10, 0))
        ttk.Scale(mix, from_=0.0, to=1.0, variable=self.r_mon, orient="horizontal").grid(
            row=0, column=5, sticky="ew", padx=6)

        bar = ttk.Frame(f)
        bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        bar.columnconfigure(3, weight=1)
        self.r_rec_btn = tk.Button(bar, text="●  REC", bg="#b3261e", fg="white", activebackground="#d93a30",
                                   activeforeground="white", relief="flat", padx=14, pady=4,
                                   font=("Segoe UI", 10, "bold"), command=self._rec_start)
        self.r_rec_btn.grid(row=0, column=0)
        ttk.Button(bar, text="■  Stop", command=self._rec_stop).grid(row=0, column=1, padx=6)
        self.r_time = ttk.Label(bar, text="0:00", width=6, font=("Consolas", 11))
        self.r_time.grid(row=0, column=2, padx=(6, 6))
        self.r_meter = ttk.Progressbar(bar, maximum=1.0)
        self.r_meter.grid(row=0, column=3, sticky="ew")
        self.r_clip = ttk.Label(bar, text="", foreground="#b3261e", width=6)
        self.r_clip.grid(row=0, column=4, padx=(6, 0))

        tk_ = ttk.LabelFrame(f, text="Takes", padding=6)
        tk_.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        tk_.columnconfigure(0, weight=1)
        self.r_takes = tk.Listbox(tk_, height=5, exportselection=False)
        self.r_takes.grid(row=0, column=0, sticky="ew")
        tb = ttk.Frame(tk_)
        tb.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(tb, text="▶  Play with beat", command=self._rec_play).pack(side="left")
        ttk.Button(tb, text="Delete take", command=self._rec_del).pack(side="left", padx=6)
        ttk.Button(tb, text="Open folder", command=self._rec_open_dir).pack(side="left")

        ttk.Label(f, text="Output folder:").grid(row=7, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(f, textvariable=self.r_dir).grid(row=7, column=1, sticky="ew", padx=6, pady=(10, 0))
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.r_dir)).grid(row=7, column=2,
                                                                                            pady=(10, 0))
        ttk.Label(f, text="Vocal level vs beat (dB):").grid(row=8, column=0, sticky="w", pady=6)
        ttk.Scale(f, from_=-8.0, to=2.0, variable=self.r_vox_off, orient="horizontal").grid(
            row=8, column=1, sticky="ew", padx=6)
        b, self.r_split = self._xbox(f, "Split the beat into stems first (Demucs - better mix, takes a few "
                                        "minutes the first time)", True)
        b.grid(row=9, column=0, columnspan=3, sticky="w")
        self.r_sep = self._sep_row(f, 10)
        ttk.Button(f, text="Mix and master the selected take", command=self._go_rec_mix).grid(
            row=11, column=1, sticky="w", padx=6, pady=(10, 0))
        self.r_opts = self._opts_panel(f, 12)
        self._rec_devices()

    def _rec_devices(self):
        try:
            ins, outs = R.devices("input"), R.devices("output")
            di = R.default_device("input")
            do = (R.matching_output(di) if di is not None else None) or R.default_device("output")
        except Exception as e:
            self.log(f"!! audio devices unavailable: {e}")
            return
        lab = lambda i, n: f"{i}: {n}"
        self.r_in_cb.configure(values=[lab(i, n) for i, n in ins])
        self.r_out_cb.configure(values=[lab(i, n) for i, n in outs])
        if not self.r_in.get() and ins:
            self.r_in.set(next((lab(i, n) for i, n in ins if i == di), lab(*ins[0])))
        if not self.r_out.get() and outs:
            self.r_out.set(next((lab(i, n) for i, n in outs if i == do), lab(*outs[0])))
        self._rec_lat_label()

    def _rec_devs(self):
        try:
            return int(self.r_in.get().split(":")[0]), int(self.r_out.get().split(":")[0])
        except ValueError:
            messagebox.showwarning(APP, "Pick the mic and the headphones.")
            return None

    def _rec_lat_label(self):
        try:
            i, o = int(self.r_in.get().split(":")[0]), int(self.r_out.get().split(":")[0])
            ms = R.saved_latency_ms(i, o)
        except Exception:
            ms = None
        self.r_lat_lbl.configure(
            text=f"Round trip: {ms:.1f} ms (calibrated)" if ms is not None else
            "Not calibrated yet - using the driver's estimate (press Calibrate for exact timing).")

    def _rec_pick_beat(self):
        p = filedialog.askopenfilename(filetypes=AUDIO_FT)
        if p:
            self.r_beat.set(p)
            self.r_dir.set(os.path.join(R.takes_dir(p), "MIX"))
            self._rec_refresh_takes()

    def _rec_refresh_takes(self, select=None):
        self.r_takes.delete(0, "end")
        beat = self.r_beat.get().strip()
        if not beat:
            return
        for p in R.list_takes(beat):
            self.r_takes.insert("end", os.path.basename(p))
        if select:
            names = self.r_takes.get(0, "end")
            if select in names:
                k = names.index(select)
                self.r_takes.selection_set(k)
                self.r_takes.see(k)

    def _rec_take(self):
        sel = self.r_takes.curselection()
        if not sel:
            messagebox.showinfo(APP, "Pick a take in the list.")
            return None
        return os.path.join(R.takes_dir(self.r_beat.get().strip()), self.r_takes.get(sel[0]))

    def _rec_start_s(self):
        s = self.r_start.get().strip() or "0"
        try:
            m, _, sec = s.rpartition(":")
            return max(0.0, int(m or 0) * 60 + float(sec))
        except ValueError:
            messagebox.showwarning(APP, "Start at: write it as m:ss, e.g. 1:05")
            return None

    def _rec_beat(self, sr, then):
        """decoded beat at sr (cached), handed to then(audio) on the Tk thread."""
        beat = self.r_beat.get().strip()
        if self.r_beat_x and self.r_beat_x[:2] == (beat, sr):
            then(self.r_beat_x[2])
            return
        self.status.configure(text="Loading beat...")

        def done(x, err):
            self.status.configure(text="Ready")
            if err:
                self.log(f"!! {err}")
                return
            self.r_beat_x = (beat, sr, x)
            then(x)
        self._bg_then(lambda: R.load_audio(beat, sr), done)

    def _rec_ready(self):
        if self.r_sess is not None:
            return False
        if self.busy:
            messagebox.showinfo(APP, "A job is already running.")
            return False
        if not (self.r_beat.get().strip() and os.path.exists(self.r_beat.get().strip())):
            messagebox.showwarning(APP, "Pick the beat.")
            return False
        return True

    def _rec_run(self, play, sr, devs, monitor, on_done):
        """start a Session and follow it (meter, clock) until it ends, then on_done(session)."""
        i, o = devs
        s = R.Session(play, sr, i, o, monitor=monitor)
        try:
            s.start()
        except Exception as e:
            self.log(f"!! could not open the audio devices: {e}")
            return
        self.r_sess = s
        t0 = self.r_t0

        def poll():
            self.r_meter.configure(value=min(1.0, s.peak))
            t = t0 + s.pos / sr
            self.r_time.configure(text=f"{int(t // 60)}:{int(t % 60):02d}")
            self.r_clip.configure(text="CLIP" if s.clipped else "")
            if s.done.is_set():
                s.stop()
                self.r_sess = None
                self.r_meter.configure(value=0)
                self.status.configure(text="Ready")
                on_done(s)
            else:
                self.root.after(50, poll)
        poll()

    def _rec_start(self):
        if not self._rec_ready():
            return
        devs = self._rec_devs()
        st = self._rec_start_s()
        if devs is None or st is None:
            return
        sr = R.device_rate(*devs)

        def go(x):
            s0 = int(st * sr)
            if s0 >= len(x):
                messagebox.showwarning(APP, "Start at is past the end of the beat.")
                return
            self.r_t0 = st
            self.status.configure(text="Recording...  (Stop when done)")
            self._rec_run(x[s0:] * float(self.r_beatvol.get()), sr, devs, float(self.r_mon.get()),
                          lambda s: self._rec_save(s, devs, sr, s0, len(x)))
        self._rec_beat(sr, go)

    def _rec_save(self, s, devs, sr, s0, total):
        raw = s.recorded()
        if len(raw) < sr:
            self.log("take shorter than 1 s - discarded")
            return
        ms = R.saved_latency_ms(*devs)
        how = "calibrated"
        if ms is None:
            ms, how = s.reported_latency_s() * 1000.0, "driver estimate"
        ms += float(self.r_fine.get())
        take = R.align(raw, int(round(ms * sr / 1000.0)), s0, total)
        path = R.next_take_path(self.r_beat.get().strip())
        R.write_take(path, take, sr)
        self.log(f"saved {os.path.basename(path)}  ({len(raw) / sr:.1f} s, shifted {ms:.1f} ms, {how})"
                 + ("  !! the mic CLIPPED - move back a little or lower the mic gain" if s.clipped else ""))
        self._rec_refresh_takes(select=os.path.basename(path))

    def _rec_stop(self):
        if self.r_sess is not None:
            self.r_sess.stop()

    def _rec_play(self):
        take = self._rec_take()
        if not take or not self._rec_ready():
            return
        devs = self._rec_devs()
        st = self._rec_start_s()
        if devs is None or st is None:
            return
        v, vsr = sf.read(take, dtype="float32")
        sr = R.device_rate(*devs)
        if vsr != sr:
            messagebox.showwarning(APP, f"This take was recorded at {vsr} Hz and the headphones now run at "
                                        f"{sr} Hz - it can still be mixed, just not played here.")
            return

        def go(x):
            n = min(len(x), len(v))
            s0 = int(st * sr)
            mix = x[:n] * float(self.r_beatvol.get()) + v[:n, None]
            self.r_t0 = st
            self.status.configure(text="Playing take...")
            self._rec_run(np.clip(mix[s0:], -1, 1), sr, devs, 0.0, lambda s: None)
        self._rec_beat(sr, go)

    def _rec_open_dir(self):
        beat = self.r_beat.get().strip()
        if beat:
            os.makedirs(R.takes_dir(beat), exist_ok=True)
            os.startfile(R.takes_dir(beat))

    def _rec_del(self):
        take = self._rec_take()
        if take and messagebox.askyesno(APP, f"Delete {os.path.basename(take)}?"):
            os.remove(take)
            self._rec_refresh_takes()

    def _rec_calibrate(self):
        if self.r_sess is not None:
            return
        devs = self._rec_devs()
        if devs is None:
            return
        if not messagebox.askokcancel(APP, "Hold one earcup tight against the mic, then press OK.\n"
                                           "You will hear 6 clicks."):
            return
        self.status.configure(text="Calibrating...")

        def done(ms, err):
            self.status.configure(text="Ready")
            if err:
                messagebox.showwarning(APP, f"Calibration failed: {err}")
                return
            R.save_latency_ms(*devs, ms)
            self._rec_lat_label()
        self._bg_then(lambda: R.calibrate(*devs, log=self.log), done)

    def _go_rec_mix(self):
        take = self._rec_take()
        beat, o = self.r_beat.get().strip(), self.r_dir.get().strip()
        if not take:
            return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        split, sep, vox, kw = self.r_split.get(), self.r_sep(), float(self.r_vox_off.get()), self.r_opts()

        def job():
            d = R.beat_stems(beat, split, sep, self.log)
            C.stemmix(d, take, o, vox=vox, log=self.log, **kw)
        self._run_bg(job)

    # ---------- tab: master ----------
    def tab_master(self, nb):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text="Master")
        f.columnconfigure(1, weight=1)
        self.m_in = tk.StringVar()
        self.m_out = tk.StringVar()
        self.m_care = tk.BooleanVar(value=True)
        ttk.Label(f, text="Song (finished mix):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.m_in).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_file(self.m_in)).grid(row=0, column=2)
        ttk.Label(f, text="Output folder:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.m_out).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.m_out)).grid(row=1, column=2)
        ttk.Checkbutton(f, text="Extra care (more attempts + tonal polish)", variable=self.m_care).grid(
            row=2, column=1, sticky="w", padx=6)
        self.m_sep = self._sep_row(f, 3)
        self.m_opts = self._opts_panel(f, 7)
        ttk.Button(f, text="Master", command=self._go_master).grid(row=5, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text="Makes MASTER / INSTRUMENTAL / ACAPELLA / APPLE DIGITAL MASTER  + FLAC + MP3-320.\n"
                          "The song is split into every stem; drums, bass and the rest are mixed separately.\n"
                          "With references set: matches their average tone + loudness and reports a 6-axis verdict.\n"
                          "With no references: a self master that gets the best out of the source.",
                  foreground="#7b8794").grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _go_master(self):
        a, o = self.m_in.get().strip(), self.m_out.get().strip()
        if not (a and os.path.exists(a)):
            messagebox.showwarning(APP, "Pick a song."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        sep, care, kw = self.m_sep(), self.m_care.get(), self.m_opts()
        self._run_bg(lambda: C.master_one(a, o, care=care, log=self.log, sep=sep, **kw))

    # ---------- tab: batch ----------
    def tab_batch(self, nb):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text="Batch")
        f.columnconfigure(1, weight=1)
        self.b_in = tk.StringVar()
        self.b_out = tk.StringVar()
        self.b_care = tk.BooleanVar(value=True)
        ttk.Label(f, text="Folder of songs:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.b_in).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.b_in)).grid(row=0, column=2)
        ttk.Label(f, text="Output folder:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.b_out).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.b_out)).grid(row=1, column=2)
        ttk.Checkbutton(f, text="Extra care", variable=self.b_care).grid(row=2, column=1, sticky="w", padx=6)
        self.b_sep = self._sep_row(f, 3)
        ttk.Button(f, text="Process folder", command=self._go_batch).grid(
            row=5, column=1, sticky="w", padx=6, pady=(10, 0))
        self.b_opts = self._opts_panel(f, 7)

    def _go_batch(self):
        i, o = self.b_in.get().strip(), self.b_out.get().strip()
        if not (i and os.path.isdir(i)):
            messagebox.showwarning(APP, "Pick the songs folder."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        sep, care, kw = self.b_sep(), self.b_care.get(), self.b_opts()
        self._run_bg(lambda: C.batch(i, o, care=care, log=self.log, sep=sep, **kw))

    # ---------- tab: mix from stems ----------
    def tab_stem(self, nb):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text="Mix from stems")
        f.columnconfigure(1, weight=1)
        self.s_stems = tk.StringVar()
        self.s_vox = tk.StringVar()
        self.s_out = tk.StringVar()
        self.s_vox_off = tk.DoubleVar(value=-3.0)
        ttk.Label(f, text="Beat stems folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.s_stems).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.s_stems)).grid(row=0, column=2)
        ttk.Label(f, text="Your vocal (wav):").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.s_vox).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_file(self.s_vox)).grid(row=1, column=2)
        ttk.Label(f, text="Output folder:").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.s_out).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.s_out)).grid(row=2, column=2)
        ttk.Label(f, text="Vocal level vs beat (dB):").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Scale(f, from_=-8.0, to=2.0, variable=self.s_vox_off, orient="horizontal").grid(
            row=3, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="Mix and master", command=self._go_stem).grid(
            row=4, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text="Stems detected by name: drum / bass / guitar / keys / strings / synth / other.",
                  foreground="#7b8794").grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.s_opts = self._opts_panel(f, 7)

    def _go_stem(self):
        st, vx, o = self.s_stems.get().strip(), self.s_vox.get().strip(), self.s_out.get().strip()
        if not (st and os.path.isdir(st)):
            messagebox.showwarning(APP, "Pick the stems folder."); return
        if not (vx and os.path.exists(vx)):
            messagebox.showwarning(APP, "Pick your vocal wav."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        vox, kw = float(self.s_vox_off.get()), self.s_opts()
        self._run_bg(lambda: C.stemmix(st, vx, o, vox=vox, log=self.log, **kw))

    # ---------- shared distribute panel ----------
    def _distrib_panel(self, nb, tab_text, clean):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text=tab_text)
        f.columnconfigure(1, weight=1)
        d_in = tk.StringVar()
        d_out = tk.StringVar()
        d_lufs = tk.DoubleVar(value=-9.5)
        d_split = tk.BooleanVar(value=True)
        ttk.Label(f, text="Audio or folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=d_in).grid(row=0, column=1, sticky="ew", padx=6)
        bb = ttk.Frame(f); bb.grid(row=0, column=2)
        ttk.Button(bb, text="File", width=7, command=lambda: self._pick_file(d_in)).pack()
        ttk.Button(bb, text="Folder", width=7, command=lambda: self._pick_dir(d_in)).pack()
        ttk.Label(f, text="Output folder:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=d_out).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(d_out)).grid(row=1, column=2)
        ttk.Label(f, text="Target loudness (LUFS):").grid(row=2, column=0, sticky="w")
        row = ttk.Frame(f); row.grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Scale(row, from_=-16.0, to=-6.0, variable=d_lufs, orient="horizontal").pack(side="left", fill="x", expand=True)
        lbl = ttk.Label(row, width=6, text="-9.5")
        lbl.pack(side="left")
        d_lufs.trace_add("write", lambda *_: lbl.configure(text=f"{d_lufs.get():.1f}"))
        ttk.Checkbutton(f, text="Also output INSTRUMENTAL and ACAPELLA (separates with Demucs, takes a few min)",
                        variable=d_split).grid(row=3, column=1, sticky="w", padx=6, pady=(6, 0))
        d_sep = self._sep_row(f, 4)
        note = ("Makes the audio upload-ready: one fixed gain to the target loudness + true-peak -1 dBTP\n"
                "(no automatic level riding, so nothing pumps).\n"
                "Each track as WAV 48k/24 + WAV 44.1k/16 + MP3 320.\n"
                "-9.5 LUFS = loud (urban).  -14 LUFS = streaming-platform standard.")
        if clean:
            note = ("AI clean first (denoise / de-static, de-breath, de-plosive, de-reverb on the vocal),\n"
                    "then the same distribute step.\n") + note
        ttk.Button(f, text="Clean + distribute" if clean else "Regulate audio",
                   command=lambda: self._go_distrib(d_in, d_out, d_lufs, d_split, clean, d_sep(), d_opts())).grid(
            row=5, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text=note, foreground="#7b8794").grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))
        d_opts = self._opts_panel(f, 7)

    def tab_distrib(self, nb):
        self._distrib_panel(nb, "Distribute", clean=False)

    def tab_clean(self, nb):
        self._distrib_panel(nb, "AI Clean + Distribute", clean=True)

    def _go_distrib(self, d_in, d_out, d_lufs, d_split, clean, sep, kw):
        i, o = d_in.get().strip(), d_out.get().strip()
        if not (i and os.path.exists(i)):
            messagebox.showwarning(APP, "Pick an audio file or a folder."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        lufs, sp = float(d_lufs.get()), bool(d_split.get())
        if os.path.isdir(i):
            self._run_bg(lambda: C.distribute_batch(i, o, target_lufs=lufs, split=sp, clean=clean, log=self.log,
                                                    sep=sep, **kw),
                         needs_refs=False)
        else:
            self._run_bg(lambda: C.distribute(i, o, target_lufs=lufs, split=sp, clean=clean, log=self.log,
                                              sep=sep, **kw),
                         needs_refs=False)

    # ---------- tab: styles & tune only ----------
    def tab_styles(self, nb):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text="Styles & Tune")
        f.columnconfigure(1, weight=1)
        self.y_in = tk.StringVar()
        self.y_out = tk.StringVar()
        ttk.Label(f, text="Audio or folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.y_in).grid(row=0, column=1, sticky="ew", padx=6)
        bb = ttk.Frame(f); bb.grid(row=0, column=2)
        ttk.Button(bb, text="File", width=7, command=lambda: self._pick_file(self.y_in)).pack()
        ttk.Button(bb, text="Folder", width=7, command=lambda: self._pick_dir(self.y_in)).pack()
        ttk.Label(f, text="Output folder:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.y_out).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(f, text="...", width=3, command=lambda: self._pick_dir(self.y_out)).grid(row=1, column=2)
        self.y_sep = self._sep_row(f, 2)
        ttk.Button(f, text="Make only these", command=self._go_styles).grid(
            row=3, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text="Any audio in, ONLY what you mark out: the master styles you tick (each as WAV + MP3,\n"
                          "with COMPARE.html) and/or, with Natural pitch correction ticked, TUNED MIX.wav (the song with\n"
                          "the vocal in tune, nothing else changed) + ACAPELLA TUNED.wav. No MASTER / INSTRUMENTAL / APPLE.",
                  foreground="#7b8794").grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.y_opts = self._opts_panel(f, 7)

    def _go_styles(self):
        i, o = self.y_in.get().strip(), self.y_out.get().strip()
        if not (i and os.path.exists(i)):
            messagebox.showwarning(APP, "Pick an audio file or a folder."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        sep, kw = self.y_sep(), self.y_opts()
        if not kw["variants"] and not kw["tune"]:
            messagebox.showwarning(APP, "Mark at least one style or Natural pitch correction."); return
        self._run_bg(lambda: C.styles_only(i, o, sep=sep, log=self.log, **kw), needs_refs=False)

    # ---------- tab: references ----------
    def tab_refs(self, nb):
        f = ttk.Frame(nb, padding=PAD)
        nb.add(f, text="References")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        ttk.Label(f, text="Drop in 2-4 commercial songs whose sound you want to match.\n"
                          "They are copied to your references folder. They must be YOURS or cleared\n"
                          "for use - do not ship the app with third-party music inside it.\n"
                          "mp3 / m4a / opus are converted to wav automatically.",
                  foreground="#7b8794").grid(row=0, column=0, sticky="w")
        self.refbox = tk.Listbox(f, height=8)
        self.refbox.grid(row=1, column=0, sticky="nsew", pady=6)
        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, sticky="w")
        ttk.Button(bar, text="Add...", command=self._add_ref).pack(side="left")
        ttk.Button(bar, text="Remove selected", command=self._del_ref).pack(side="left", padx=6)
        ttk.Button(bar, text="Open folder", command=lambda: os.startfile(E.REFS)).pack(side="left")

    def _refresh_refs(self):
        self.refbox.delete(0, "end")
        for p in E.refs_list():
            self.refbox.insert("end", os.path.basename(p))
        n = len(E.refs_list())
        self.status.configure(text=f"{n} reference(s)" + ("" if n >= 2 else "  - need at least 2 (or use no-reference master)"))

    def _invalidate_curve(self):
        cc = os.path.join(E.WORK, "composite_curve_cache2.npz")
        if os.path.exists(cc):
            try:
                os.remove(cc)
            except Exception:
                pass

    def _add_ref(self):
        ps = filedialog.askopenfilenames(title="Pick 2-4 reference songs", filetypes=AUDIO_FT)
        if not ps:
            return
        try:
            os.makedirs(E.REFS, exist_ok=True)
        except Exception as e:
            messagebox.showerror(APP, f"Cannot create the references folder:\n{E.REFS}\n{e}")
            return
        added = 0
        for p in ps:
            base = os.path.splitext(os.path.basename(p))[0]
            base = "".join(c for c in base if c not in '<>:"/\\|?*').strip() or "ref"
            ext = os.path.splitext(p)[1].lower()
            try:
                if ext in (".wav", ".flac"):
                    shutil.copy2(p, os.path.join(E.REFS, base + ext))
                else:
                    dst = os.path.join(E.REFS, base + ".wav")
                    self.log(f"converting {os.path.basename(p)} -> wav ...")
                    r = subprocess.run(
                        [E.FFMPEG, "-v", "error", "-y", "-i", p, "-ar", "48000",
                         "-ac", "2", "-c:a", "pcm_s24le", dst],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if r.returncode != 0 or not os.path.exists(dst):
                        self.log(f"!! ffmpeg could not convert {os.path.basename(p)}: {r.stderr[-300:]}")
                        continue
                self.log(f"reference + {base}")
                added += 1
            except Exception as e:
                self.log(f"!! error adding {os.path.basename(p)}: {e}")
        self._invalidate_curve()
        self._refresh_refs()
        if added == 0:
            messagebox.showwarning(APP, "No reference was added. Check the console.")

    def _del_ref(self):
        sel = self.refbox.curselection()
        if not sel:
            return
        name = self.refbox.get(sel[0])
        try:
            os.remove(os.path.join(E.REFS, name))
        except Exception as e:
            self.log(f"!! {e}")
        self._invalidate_curve()
        self._refresh_refs()


def main():
    E.apply_env()
    root = tk.Tk()
    root.title(f"{APP} {E.VERSION}")
    root.geometry("1000x860")
    try:
        root.call("ttk::style", "theme", "use", "clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
