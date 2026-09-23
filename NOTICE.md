# Third-party components

BREKEM STUDIO is distributed under GPL-3.0-or-later (see `LICENSE`). It bundles
or depends on:

| Component | License | Notes |
|-----------|---------|-------|
| Matchering 2.0.6 | GPL-3.0 | Reference-based matching. Its licence is why the whole app is GPLv3. |
| Demucs | MIT | Source separation (htdemucs model weights: MIT, Meta). |
| DeepFilterNet | MIT / Apache-2.0 | Vocal denoise/dereverb (model weights included by the pip package). |
| PyTorch / torchaudio | BSD-3-Clause | |
| pedalboard | GPL-3.0 | Spotify audio-effects library. |
| numpy, scipy | BSD-3-Clause | |
| soundfile (libsndfile) | BSD-3-Clause / LGPL-2.1 | |
| librosa | ISC | |
| pyloudnorm | MIT | |
| FFmpeg (bundled `vendor/ffmpeg.exe`, `ffprobe.exe`) | GPL-3.0 (gyan.dev full build) | Redistributed unmodified. Source: https://ffmpeg.org/download.html |
| Python | PSF | |

Model weights for Demucs and DeepFilterNet are downloaded on first run (not
shipped in this repo) unless a build chooses to pre-bundle them.

If you distribute a binary built from this project you must also make the
corresponding source available (this folder), per GPLv3 §6.
