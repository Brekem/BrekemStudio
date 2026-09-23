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
| **Máster** | One finished mix in → 4 deliverables out. Separates (Demucs) + cleans the vocal (DeepFilterNet) automatically. |
| **Lote** | A whole folder of songs, one after another. |
| **Mezcla desde stems** | Your recorded vocal + a beat delivered as stems → auto mix + master. |
| **Distribuible** | Any finished audio → loudness-normalised (2-pass), true-peak ≤ −1 dBTP, exported as 48k/24 + 44.1k/16 WAV + MP3 320. No separation, no references, no tonal change. Fast. |
| **Referencias** | Add 2–4 commercial songs in the target style. The chain matches their average tone and loudness. |

**Offline:** the Demucs and DeepFilterNet model weights are bundled inside the app.
No internet is needed, ever — not even on first run, not on a fresh machine.

"Más cariño" = more parameter-search attempts per song plus a polish pass that
pulls the worst tonal axis toward the centre without breaking the 6/6.

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

First run downloads the Demucs (~80 MB) and DeepFilterNet models to
`%LOCALAPPDATA%\BrekemStudio\models`.

## Build the installer

See `build/BUILD.md`. Short version: `build\build.bat` runs PyInstaller and (if
Inno Setup is installed) produces `BREKEM STUDIO Setup.exe`.

## License

GPL-3.0-or-later. This program bundles **Matchering** (GPLv3), so the whole work
is GPLv3. Full text in `LICENSE`. Third-party components and their licenses in
`NOTICE.md`. Source: ship this folder alongside any binary you distribute, or
point users to where they can get it.
