# Suno AI Remove Hissing

Windows desktop batch tool for reducing metallic hiss and harsh upper-frequency artifacts in Suno tracks. It keeps the source files untouched and writes a cleaned WAV, a `REMOVED` WAV, and a JSON report for every selected song.

## What it does

1. Scans a selected input folder recursively for common audio formats.
2. Lets the user tick exactly the tracks to process.
3. Applies one or both direct whole-mix effects.
4. Writes each result in its own output folder, alongside the exact removed-signal WAV and a JSON report.

The goal is the metallic fizz / unstable high partials that can occur in generated tracks. The `REMOVED` WAV is an inspection tool: it is exactly source minus final result, not an estimated stem.

## Architecture

- `src/SunoAiRemoveHissing` — .NET 10 WPF UI: folder selection, scan table, settings, process lifecycle, cancellation and per-file statuses.
- `backend/SunoClean_AI.py` — NumPy/SciPy whole-mix DSP engine, invoked as a subprocess by the UI.
- `ffmpeg` — input decoding and 24-bit WAV encoding.

The app does not use Whisper. Whisper transcribes speech; it is not an audio restoration model.

## Why Demucs was removed

The first experiments used Demucs to split a generated mix into estimated `vocals` and `no_vocals` stems. A useful food analogy changed the design: source separation would be appropriate if we could send an undercooked steak back to the kitchen, but a completed Suno mix is closer to øllebrød — its ingredients are already blended together. Demucs can only estimate those ingredients and recombining the estimates adds another uncertain processing stage.

The successful whole-mix dynamic test proved that the target artifacts can be reduced directly, without separation or GPU inference. Demucs is therefore deliberately not part of the current project.

## Prerequisites

- Windows 10/11
- .NET 10 SDK (for running from source)
- Python 3.11 or newer
- FFmpeg available in `PATH`

Create a Python environment and install the backend dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -r backend\requirements.txt
```

The UI asks for the `python.exe` belonging to that environment. Processing runs directly on the CPU; no CUDA setup is required.

## Run

```powershell
dotnet run --project src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj
```

Or run `START_WINDOWS.bat` from the repository root.

## Controls

- **Dynamic 1.8–4 kHz profile** — detects short transients and reduces that band. Normal is the proven original setting: +4 dB trigger above local median, max -3 dB, 250 ms release.
- **Harmonic de-fizzer profile** — reduces unusually prominent narrow spectral ridges at 3.5–11 kHz. Normal is the proven original setting: up to -6 dB with the original ridge sensitivity.
- **Profiles** — each effect has five fixed positions: **Off**, **Light**, **Normal**, **Strong**, **Brutal**. Normal is the default centre position. Light is deliberately only slightly milder; Strong and Brutal increase maximum reduction and sensitivity.
- **Replace existing output files** — off by default; preserves previous result folders until explicitly enabled.

The effects can be enabled together. Every selected song gets its own folder, preserving source subfolders, for example:

```text
Output\Velvet Paradise [ IX]\
  Velvet Paradise [ IX ]_D&H.wav
  Velvet Paradise [ IX ]_REMOVED_D&H.wav
  Velvet Paradise [ IX ]_D&H.json
```

The `REMOVED` file is always the exact original-minus-final difference for that specific combination.

Short suffixes are `_D` for dynamic only, `_H` for harmonic only, and `_D&H` when both are active.

## Build a Windows executable

Run `BUILD_WINDOWS.bat` from the repository root. It publishes a self-contained Windows x64 executable to `dist\SunoAiRemoveHissing-win-x64`.

Equivalent command:

```powershell
dotnet publish src\SunoAiRemoveHissing\SunoAiRemoveHissing.csproj -c Release -r win-x64 --self-contained true
```

The published application still requires its Python environment and FFmpeg.

## Local self-contained install

Run this from PowerShell in the repository root to publish directly to `C:\Apps\SunoAiRemoveHissing`:

```powershell
.\INSTALL_LOCAL.ps1
```

It replaces only that exact application folder, publishes a self-contained Windows executable, includes `backend\SunoClean_AI.py`, and removes `.pdb` debug-symbol files. To use another application folder below `C:\Apps`:

```powershell
.\INSTALL_LOCAL.ps1 -InstallPath 'C:\Apps\MySunoDenoiser'
```
