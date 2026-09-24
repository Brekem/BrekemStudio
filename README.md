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
Inno Setup is installed) produces `BREKEM STUDIO Setup.exe`.

## License

GPL-3.0-or-later. This program bundles **Matchering** (GPLv3), so the whole work
is GPLv3. Full text in `LICENSE`. Third-party components and their licenses in
`NOTICE.md`. Source: ship this folder alongside any binary you distribute, or
point users to where they can get it.
