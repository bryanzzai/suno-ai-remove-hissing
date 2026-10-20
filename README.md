# Suno AI Remove Hissing

Windows desktop batch tool for reducing metallic hiss and harsh upper-frequency artifacts in Suno tracks. It keeps the source files untouched and writes a cleaned WAV or M4A, a `REMOVED` WAV, and a JSON report for every selected song.

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

## Portable Windows build

The GitHub Actions artifact is a complete x64 Windows folder. It needs no installed .NET runtime, Python, NumPy, SciPy or FFmpeg, and does not use `PATH`.

```text
SunoAiRemoveHissing-Portable\
  SunoAiRemoveHissing.exe
  backend\SunoClean_AI.py
  runtime\python.exe
  runtime\Lib\site-packages\numpy\
  runtime\Lib\site-packages\scipy\
  tools\ffmpeg.exe
```

Keep this layout intact and run `SunoAiRemoveHissing.exe`. The program checks for each required component and reports its exact expected path if the folder is incomplete.

## Run from source

Building from source requires Windows 10/11, the .NET 10 SDK, Python 3.11+ and FFmpeg. The regular source run still needs a portable folder beside the executable, so use `BUILD_PORTABLE.ps1` when creating a runnable build.

Create a Python environment and install the backend dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install --upgrade pip
pip install -r backend\requirements.txt
```

The build machine uses that Python only to assemble the portable runtime. Processing runs directly on the CPU; no CUDA setup is required.

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
- **Output format** — choose **WAV** for uncompressed 24-bit audio suitable for further work, or **M4A** for a new AAC file. M4A output copies metadata and embedded cover artwork from the source file. The `REMOVED` signal remains 24-bit WAV in both modes.

The effects can be enabled together. Every selected song gets its own folder, preserving source subfolders, for example:

```text
Output\Velvet Paradise [ IX]\
  Velvet Paradise [ IX ]_D&H.wav
  Velvet Paradise [ IX ]_REMOVED_D&H.wav
  Velvet Paradise [ IX ]_D&H.json
```

The `REMOVED` file is always the exact original-minus-final difference for that specific combination.

Short suffixes are `_D` for dynamic only, `_H` for harmonic only, and `_D&H` when both are active.

When M4A is selected, only the cleaned file changes extension, for example `Velvet Paradise [ IX ]_D&H.m4a`; the matching `REMOVED` and JSON files remain WAV and JSON.

## Build the portable folder

On a Windows build machine with the .NET SDK and Python 3.11+ installed:

```powershell
.\BUILD_PORTABLE.ps1
```

The script publishes the .NET application, downloads the official CPython embeddable distribution, installs NumPy/SciPy into that local runtime, downloads a static FFmpeg build, and verifies both executables. The finished folder is `dist\SunoAiRemoveHissing-Portable`.

## Local self-contained install

Run this from PowerShell in the repository root to publish directly to `C:\Apps\SunoAiRemoveHissing`:

```powershell
.\INSTALL_LOCAL.ps1
```

It replaces only that exact application folder and publishes the .NET application. For the complete portable folder, use `BUILD_PORTABLE.ps1`. To use another application folder below `C:\Apps`:

```powershell
.\INSTALL_LOCAL.ps1 -InstallPath 'C:\Apps\MySunoDenoiser'
```
