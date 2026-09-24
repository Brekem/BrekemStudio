"""BREKEM STUDIO - GUI (tkinter, standard library only)."""
import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import brekem_env as E
import brekem_cli as C

APP = "BREKEM STUDIO"
PAD = 8
SEP_CHOICES = (  # label -> Demucs model used by prep.py
    ("4 stems, best quality (vocals / drums / bass / other)", "htdemucs_ft"),
    ("6 stems (+ guitar / piano, lower quality on those two)", "htdemucs_6s"),
    ("4 stems, fast", "htdemucs"),
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
        self.tab_master(nb)
        self.tab_batch(nb)
        self.tab_stem(nb)
        self.tab_distrib(nb)
        self.tab_clean(nb)
        self.tab_refs(nb)

        self.con = Console(self)
        self.con.grid(row=1, column=0, sticky="nsew", pady=(PAD, 0))
        self.status = ttk.Label(self, text="Ready")
        self.status.grid(row=2, column=0, sticky="w", pady=(4, 0))

        self.log(APP)
        self.log(f"user data   : {E.DATA}")
        self.log(f"references  : {E.REFS}")
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
        ttk.Button(f, text="Master", command=self._go_master).grid(row=4, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text="Makes MASTER / INSTRUMENTAL / ACAPELLA / APPLE DIGITAL MASTER  + FLAC + MP3-320.\n"
                          "The song is split into every stem; drums, bass and the rest are mixed separately.\n"
                          "With references set: matches their average tone + loudness and reports a 6-axis verdict.\n"
                          "With no references: a self master that gets the best out of the source.",
                  foreground="#7b8794").grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _go_master(self):
        a, o = self.m_in.get().strip(), self.m_out.get().strip()
        if not (a and os.path.exists(a)):
            messagebox.showwarning(APP, "Pick a song."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        sep = self.m_sep()
        self._run_bg(lambda: C.master_one(a, o, care=self.m_care.get(), log=self.log, sep=sep))

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
            row=4, column=1, sticky="w", padx=6, pady=(10, 0))

    def _go_batch(self):
        i, o = self.b_in.get().strip(), self.b_out.get().strip()
        if not (i and os.path.isdir(i)):
            messagebox.showwarning(APP, "Pick the songs folder."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        sep = self.b_sep()
        self._run_bg(lambda: C.batch(i, o, care=self.b_care.get(), log=self.log, sep=sep))

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

    def _go_stem(self):
        st, vx, o = self.s_stems.get().strip(), self.s_vox.get().strip(), self.s_out.get().strip()
        if not (st and os.path.isdir(st)):
            messagebox.showwarning(APP, "Pick the stems folder."); return
        if not (vx and os.path.exists(vx)):
            messagebox.showwarning(APP, "Pick your vocal wav."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        self._run_bg(lambda: C.stemmix(st, vx, o, vox=float(self.s_vox_off.get()), log=self.log))

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
                   command=lambda: self._go_distrib(d_in, d_out, d_lufs, d_split, clean, d_sep())).grid(
            row=5, column=1, sticky="w", padx=6, pady=(10, 0))
        ttk.Label(f, text=note, foreground="#7b8794").grid(row=6, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def tab_distrib(self, nb):
        self._distrib_panel(nb, "Distribute", clean=False)

    def tab_clean(self, nb):
        self._distrib_panel(nb, "AI Clean + Distribute", clean=True)

    def _go_distrib(self, d_in, d_out, d_lufs, d_split, clean, sep):
        i, o = d_in.get().strip(), d_out.get().strip()
        if not (i and os.path.exists(i)):
            messagebox.showwarning(APP, "Pick an audio file or a folder."); return
        if not o:
            messagebox.showwarning(APP, "Pick an output folder."); return
        lufs, sp = float(d_lufs.get()), bool(d_split.get())
        if os.path.isdir(i):
            self._run_bg(lambda: C.distribute_batch(i, o, target_lufs=lufs, split=sp, clean=clean, log=self.log,
                                                    sep=sep),
                         needs_refs=False)
        else:
            self._run_bg(lambda: C.distribute(i, o, target_lufs=lufs, split=sp, clean=clean, log=self.log,
                                              sep=sep),
                         needs_refs=False)

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
                        capture_output=True, text=True,
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
    root.title(APP)
    root.geometry("860x660")
    try:
        root.call("ttk::style", "theme", "use", "clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
