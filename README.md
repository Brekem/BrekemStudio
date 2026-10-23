# BREKEM STUDIO

Free vocal/master chain for urban music. Takes a mixed song (or your voice + a
beat's stems), separates and cleans the vocal, and masters the result to match
reference songs **you** provide — then exports the four release deliverables.

Outputs per song:

- `MASTER.wav` · `INSTRUMENTAL.wav` · `ACAPELLA.wav` · `APPLE DIGITAL MASTER.wav` (48 kHz / 24-bit)
- `MASTER` and `APPLE DIGITAL MASTER` also as **FLAC** and **MP3 320 kbps**
- a 6-axis verdict (loudness, true-peak, low, presence, air, stereo) vs the mean of your references

## What it does

| Tab | Use |
|-----|-----|
| **Máster** | One finished mix in → 4 deliverables out. Separates every stem (Demucs) + cleans the vocal (DeepFilterNet) automatically. |
| **Lote** | A whole folder of songs, one after another. |
| **Mezcla desde stems** | Your recorded vocal + a beat delivered as stems → auto mix + master. |
| **Distribuible** | Any finished audio → loudness-normalised (2-pass), true-peak ≤ −1 dBTP, exported as 48k/24 + 44.1k/16 WAV + MP3 320. No separation, no references, no tonal change. Fast. |
| **Referencias** | Add 2–4 commercial songs in the target style. The chain matches their average tone and loudness. |

**Offline:** the Demucs and DeepFilterNet model weights are bundled inside the app.
No internet is needed, ever — not even on first run, not on a fresh machine.

"Más cariño" = more parameter-search attempts per song plus a polish pass that
pulls the worst tonal axis toward the centre without breaking the 6/6.

## Separation (stems)

Every song is split into all the stems the chosen Demucs model gives, not just
voice + instrumental:

| Option | Model | Stems |
|--------|-------|-------|
| 4 stems, best quality (default) | `htdemucs_ft` | vocals, drums, bass, other |
| 6 stems | `htdemucs_6s` | + guitar, piano (those two are the weakest) |
| 4 stems, fast | `htdemucs` | vocals, drums, bass, other |

The beat is then rebuilt stem by stem: transient punch on the drums only (not
on the 808), bass low end folded to mono, and the rest gets a small dip at
1.8–5 kHz while the vocal is singing so the voice sits in front.

The processed (cleaned) vocal is only used where the vocal stem really holds a
vocal. Everywhere else — intro, beat breaks, the song's tail — the mix uses the
untouched separation, and the ACAPELLA is silent there. That removes the
"interference" the old chain made from the separation bleed at the end of songs.

Stems are cached per song + model in `%LOCALAPPDATA%\BrekemStudio\stems`.

## Master styles (VARIANTS)

Tick "Also make 8 master styles" (on by default in the Master tab) and the same
song comes out in 8 styles in `<output>\VARIANTS\`, each as WAV + MP3, with
`COMPARE.html`: open it in the browser, press play and click between styles —
it switches at the same second so you compare on the same part of the song.

| Style | What it does |
|-------|--------------|
| 01 CD MASTER | balanced, classic CD master (-9.5 LUFS) |
| 02 CLARITY | vocal +1 dB, less mud at 300 Hz, more presence and air |
| 03 ESPACIAL | music widened (not the vocal, not the bass), deeper vocal plate |
| 04 PUNCH | drums forward with extra attack, bass steps aside for the kick, -8.5 LUFS |
| 05 WARM | tape saturation, low-mid body, softer top |
| 06 CLUB | big low end, loudest (-7.5 LUFS) |
| 07 STREAMING -14 | platform loudness, full dynamics, gentle limiting |
| 08 BREKEM SIGNATURE | clarity + punch + width, plus two layers made from the song itself |

Every style is built from the stems, so it can push the drums without the vocal
or widen the music without the bass. BREKEM SIGNATURE adds:

- **Harmonic fill** – reads the song's own chords (chroma of the music stems every
  0.25 s) and plays them as a soft, wide, detuned pad. It only plays where the
  song is tonal (silent in drum breaks), swells with the music and sits 6 dB lower
  while the vocal sings.
- **Shimmer** – an octave-up long reverb of the music stems (no vocal, no drums)
  that opens the top and fills the gaps, ducked under the vocal.

`_VARIANTS.txt` lists loudness, dynamics, true peak, tone and stereo per style.

Every tab except References has the style boxes: mark with **[X]** each style you
want and only those are made (none marked = none made). Master, Batch, Mix from
stems, Distribute and AI Clean + Distribute all put them in `<output>\VARIANTS\`.
CLI: `--styles punch,signature` (or `--styles all`) on any command.

## Extras (their own [X] in every tab, on by default)

**Bass centred + dry** — the bass/808 stem is processed on its own:
everything under 250 Hz folded to mono (the sub stays centred on every system),
nothing under 28 Hz, a decay expander that pulls each note's tail/room down by up
to 8 dB once it falls 8 dB under the note's peak (so notes stop cleanly instead
of ringing into each other), ~4:1 compression so every note hits the same, and a
2 dB dip on each kick hit. CLI: `--no-dry-bass` to turn it off.

**Band guard** — the result is split into 5 bands (sub/bass <120 Hz, low-mid
120-500, mid 500-2k, high-mid 2-6k, high >6k; the split adds back up exactly)
and compared with the original song at the same loudness:
- *tone*: a band's share may move at most 3 dB (masters) / 4 dB (styles) from
  the original's; beyond that a static gain brings it back to the edge
- *peaks*: each band's 10 ms peaks may exceed the original's by at most 1.5 dB;
  overs are pulled down by a smooth per-band limiter, so one band (an 808 boom,
  an "S", a hi-hat) can't slam the final limiter and distort everything else.
In Distribute it only applies the peak part (the file is its own reference).
CLI: `--no-guard` to turn it off.

## Natural pitch correction (3.0)

Tick **[X] Natural pitch correction** (Extras, every tab) and the vocal is tuned
before anything else touches it — like Melodyne's automatic mode, not like
hard auto-tune:

- the **key** is read from the beat (chroma vs. major/minor key profiles); if it
  is unclear the voice is tuned to the nearest semitone instead
- each **sung note** is moved *as a whole* to the nearest note of the key, so its
  centre lands in tune while the singer's own **vibrato, slides and scoops inside
  the note are kept** (pieces under 120 ms — slides between notes — are left alone,
  notes already within 8 cents too, and every move eases in/out over ~40 ms)
- Praat's PSOLA (Parselmouth) moves the pitch **without moving the formants**, so
  the voice keeps its timbre: no chipmunk, no metallic robot
- only where someone sings (the vocal-activity mask), so the beat's bleed in the
  vocal stem is never retuned

On a test voice sung 25-45 cents off with ±30-cent vibrato: every note centre
landed at 0 cents and the vibrato depth was unchanged. The retuned vocal is
cached next to the stems. In **Mix from stems** it tunes your own vocal to the
beat's key. In Distribute it needs AI Clean or a master style (it works on the
separated vocal). CLI: `--tune`.

**Styles & Tune tab (3.1)**: any audio (file or folder) in, *only* what you mark
out: the master styles you tick and/or, with pitch correction ticked,
`TUNED MIX.wav` (the song with the vocal in tune, nothing else changed) and
`ACAPELLA TUNED.wav`. CLI: `brekem_cli.py styles "<audio|folder>" "<out>" --styles clarity,punch --tune`.

## Exciter (3.2)

Tick **[X] Exciter** (Extras, every tab, off by default). An EQ can only turn up
what is already there (hiss included); the exciter *creates* new overtones from the
music itself, like an Aphex Aural Exciter on the top and Waves MaxxBass on the bottom:

- **highs**: the band above 3 kHz goes through a soft saturator. Only the *new*
  harmonics above 5 kHz are kept and mixed back low: sparkle and air (about +1.3 dB
  above 5 kHz). Where an "S" spikes the exciter backs off, so it never adds harshness.
- **bass**: the sub (30-110 Hz, centre only) gives its 2nd / 3rd harmonics (70-200 Hz,
  kept under the mud zone), so the bass is heard on phones, laptops and earbuds that
  can't play the sub. A clean 808 with no overtones gets them too. The layer always
  adds in phase with the bass's own overtones, never cancels them.
- both layers only play where the song plays (50+ dB under the loud parts = off), so
  hiss in gaps and in the tail is never brought up.

It runs on MASTER, INSTRUMENTAL and every master style, before the band guard and the
limiter: the loudness target doesn't change, the guard still holds every band inside
the song's range, and with references the verdict loop still matches their tone.
ACAPELLA is never excited. CLI: `--exciter`.

## NVIDIA GPU (3.3)

Two installers per release:

- **BREKEM STUDIO x.y.z Setup.exe**: CPU edition, runs on any PC.
- **BREKEM.STUDIO.x.y.z.GPU.Setup.exe + its `.bin` parts**: GPU edition, built with
  CUDA 12.8 PyTorch. Download the `.exe` and **every** `.bin` into the same empty folder
  and run the `.exe`.

With an NVIDIA card (GTX 16, RTX 20 / 30 / 40 / 50) and a recent driver, the GPU edition
runs the AI parts on the card: the **Demucs separation** (the slow step: minutes on a
CPU) and the **DeepFilterNet** vocal cleaning. On RTX 30 / 40 / 50 the matrix math uses
the **tensor cores** (TF32; convolutions already do through cuDNN). No fp16, so the
stems are the same quality as on the CPU. Everything else (EQ, matching, tuning,
exciter, limiter) is CPU DSP and is unchanged.

The app probes the card at startup with a real GPU computation and says in the log what
runs where, e.g. `GPU: NVIDIA GeForce RTX 4070 (12 GB, CUDA 12.8) - AI separation +
vocal cleaning run on it, tensor cores (TF32)`. No usable card (old driver, older
GPU), or the CPU edition: everything runs on the CPU, as before. If the GPU separation
fails (e.g. out of video memory) that song is separated again on the CPU. CLI: `--cpu`
turns the GPU off.

From source: after `pip install -r requirements.txt`, swap in the CUDA build with
`pip install --force-reinstall --no-deps torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128`.

## Loudness

All loudness targets are reached with one static gain + a 4x-oversampled
true-peak limiter. Nothing rides the level up and down: the old Distribute
step used ffmpeg `loudnorm`, which for loud targets falls back to its dynamic
mode and pumps, and the master's dynamics expander followed hi-hats and the
vocal instead of loudness (level dropped whenever the vocal stopped).

## References — read this

The app ships with **no** reference songs. You add your own. Do not distribute
the app with third-party commercial music inside it: that is copyright
infringement and it is on whoever redistributes it, not on this project.

## Run from source

```
py -3.10 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python BrekemStudio.py
```

First run downloads the Demucs weights for the chosen separation model
(`htdemucs_ft` ≈ 4 × 80 MB, `htdemucs_6s` / `htdemucs` ≈ 80 MB each) and the
DeepFilterNet model to `%LOCALAPPDATA%\BrekemStudio\models`. If the chosen
model can't be loaded, separation falls back to `htdemucs`.

CLI: `python brekem_cli.py master "<song>" "<out>" --sep htdemucs_6s --shifts 2`
(`--shifts 2` = cleaner separation, twice the time).

## Build the installer

See `build/BUILD.md`. Short version: `build\build.bat` runs PyInstaller and (if
Inno Setup is installed) produces `BREKEM STUDIO Setup.exe`; `build\build.bat gpu`
builds the GPU edition (CUDA PyTorch).

## License

GPL-3.0-or-later. This program bundles **Matchering** (GPLv3), so the whole work
is GPLv3. Full text in `LICENSE`. Third-party components and their licenses in
`NOTICE.md`. Source: ship this folder alongside any binary you distribute, or
point users to where they can get it.
