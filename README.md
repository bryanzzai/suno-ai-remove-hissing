# Suno AI Remove Hissing

Windows desktop batch tool for reducing metallic hiss and harsh upper-frequency artifacts in Suno tracks. It keeps the source files untouched and writes cleaned 24-bit WAV files to a separate output folder.

## What it does

1. Scans a selected input folder recursively for common audio formats.
2. Uses Demucs on the NVIDIA GPU to estimate `vocals` and `no_vocals` stems.
3. Applies a conservative, frequency-local spectral repair only to the vocal stem.
4. Recombines the repaired vocal with the accompaniment and writes `<name>_CLEANED.wav`.

The goal is the metallic fizz / unstable high partials that can occur in generated vocals. This is **not** a general master-noise remover: a high setting can soften vocal consonants or airy detail. Begin with the defaults and compare results before batch-processing a library.

## Architecture

- `src/SunoAiRemoveHissing` — .NET 10 WPF UI: folder selection, scan table, settings, process lifecycle, cancellation and per-file statuses.
- `backend/SunoClean_AI.py` — CUDA/Demucs cleanup engine, invoked as a subprocess by the UI.
- `ffmpeg` — input decoding and 24-bit WAV encoding.

The app does not use Whisper. Whisper transcribes speech; it is not an audio restoration model.

## Prerequisites

- Windows 10/11
- .NET 10 SDK (for running from source)
- Python 3.11 with CUDA-enabled PyTorch
- NVIDIA GPU supported by the selected PyTorch CUDA build
- FFmpeg available in `PATH`

Create a Python environment and install the backend dependencies. Install a CUDA-enabled PyTorch build appropriate for the system first, then install the remaining dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -r backend\requirements.txt
```

The UI asks for the `python.exe` belonging to that environment. It stops instead of silently using CPU if CUDA is unavailable.

## Run

```powershell
dotnet run --project src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj
```

Or run `START_WINDOWS.bat` from the repository root.

## Controls

- **Strength** — maximum spectral suppression, from 1 (gentle) to 6 (strong).
- **Blend** — how much of the repaired vocal is used, from 0 (off) to 1 (full repair).
- **GPU segment** — Demucs chunk length. Start at 7; reduce to 6 or lower if GPU memory is exhausted.
- **Replace existing cleaned files** — off by default; preserves previous output until explicitly enabled.
- **Harmonic de-fizzer** — direct whole-mix test; no Demucs. It finds unusually prominent narrow spectral ridges at 3.5–11 kHz relative to neighbouring frequency bins and reduces them by up to -6 dB. This first version is deliberately strong and does not claim to identify a singer's true fundamental; use its removed-signal WAV to hear whether it is removing metallic fizz or wanted musical material.
- **Dynamic whole-mix proof** — does not use Demucs. It watches the entire mix at 1.8–4.0 kHz and, when a short transient exceeds its local one-second median by 4 dB, reduces that band by up to -3 dB with a 250 ms hold/release. It writes three files: `<name>_DYNAMIC_1P8_4K_TEST.wav`, `<name>_REMOVED_BY_DYNAMIC_TEST.wav` (the exact difference between source and result), and a JSON event report. This is an intentionally audible diagnostic renderer, not yet the final de-noiser.

The two whole-mix tests can be enabled together. Their combined output is `<name>_DYNAMIC_AND_HARMONIC_TEST.wav`; its `REMOVED` file is always the exact original-minus-final difference for that specific combination.

## Build a Windows executable

Run `BUILD_WINDOWS.bat` from the repository root. It publishes a self-contained Windows x64 executable to `dist\SunoAiRemoveHissing-win-x64`.

Equivalent command:

```powershell
dotnet publish src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj -c Release -r win-x64 --self-contained true
```

The published application still requires its Python/Demucs environment and FFmpeg. Packaging that GPU runtime is deliberately deferred: PyTorch/Demucs CUDA bundles are large and must match the target NVIDIA driver environment.
