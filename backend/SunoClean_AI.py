#!/usr/bin/env python3
"""SunoClean AI backend: Demucs vocal separation plus conservative spectral repair.

The filter only changes the estimated vocal stem and writes a separate 24-bit
WAV below the chosen output root. It is intentionally conservative: it reduces
prominent upper-frequency ridges often heard as metallic fizz in generated
vocals; it is not a general-purpose noise remover.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import istft, stft

EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".aiff", ".aif"}


def emit(phase: str, completed: int, total: int, relative: str, message: str) -> None:
    """Stable UI protocol. Keep ordinary diagnostics outside this prefix."""
    print(f"PROGRESS|{phase}|{completed}|{total}|{relative}|{message}", flush=True)


def run(command: list[object]) -> None:
    print("  >", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True)


def read_audio(path: Path) -> tuple[int, np.ndarray]:
    rate, data = wavfile.read(path)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    else:
        data = data.astype(np.float32)
    if data.ndim == 1:
        data = data[:, None]
    return rate, data


def repair(channel: np.ndarray, rate: int, strength: float, blend: float) -> np.ndarray:
    """Attenuate protruding upper partials in a vocal stem without hard gating."""
    nfft = 4096 if rate <= 48000 else 8192
    hop = nfft // 4
    freqs, _, spectrum = stft(channel, fs=rate, nperseg=nfft, noverlap=nfft - hop, boundary="zeros")
    magnitude = np.abs(spectrum)
    envelope = median_filter(magnitude, size=(15, 1), mode="nearest")
    prominence = np.maximum(magnitude / (envelope + 1e-7) - 1.0, 0.0)
    peak_mask = np.clip(prominence / 2.0, 0.0, 1.0)

    ramp_up = np.clip((freqs - 1300.0) / 1200.0, 0.0, 1.0)
    ramp_down = np.clip((9500.0 - freqs) / 2500.0, 0.0, 1.0)
    region = (ramp_up * ramp_down)[:, None]
    maximum_reduction_db = 2.0 + strength * 1.5
    maximum_attenuation = 1.0 - 10.0 ** (-maximum_reduction_db / 20.0)
    gain = 1.0 - blend * maximum_attenuation * region * peak_mask
    gain = gaussian_filter1d(gain, 0.7, axis=0)
    _, output = istft(spectrum * gain, fs=rate, nperseg=nfft, noverlap=nfft - hop, input_onesided=True, boundary=True)
    return output[: len(channel)].astype(np.float32)


def output_path(output_root: Path, relative: Path) -> Path:
    return (output_root / relative.parent / f"{relative.stem}_CLEANED.wav").resolve()


def clean_file(source: Path, destination: Path, strength: float, blend: float, segment: int) -> None:
    with tempfile.TemporaryDirectory(prefix="sunoclean_") as raw_workspace:
        workspace = Path(raw_workspace)
        input_wav = workspace / "input.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", input_wav])
        run([sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals", "--device", "cuda",
             "--segment", str(segment), "--overlap", "0.25", "-o", workspace / "stems", input_wav])

        stem_root = workspace / "stems" / "htdemucs" / "input"
        rate, vocals = read_audio(stem_root / "vocals.wav")
        accompaniment_rate, accompaniment = read_audio(stem_root / "no_vocals.wav")
        if rate != accompaniment_rate:
            raise RuntimeError("Demucs returned mismatched stem sample rates.")
        samples = min(len(vocals), len(accompaniment))
        vocals, accompaniment = vocals[:samples], accompaniment[:samples]
        repaired = np.column_stack([repair(vocals[:, channel], rate, strength, blend)
                                    for channel in range(vocals.shape[1])])
        output = repaired + accompaniment
        peak = float(np.max(np.abs(output)))
        if peak > 0.99:
            output *= 0.99 / peak

        intermediate = workspace / "repaired_float.wav"
        wavfile.write(intermediate, rate, output.astype(np.float32))
        staged = workspace / "final.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", intermediate,
             "-c:a", "pcm_s24le", staged])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, destination)


def collect_files(input_root: Path, output_root: Path) -> list[Path]:
    output_root = output_root.resolve()
    files = []
    for candidate in input_root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.lower() not in EXTENSIONS:
            continue
        try:
            candidate.resolve().relative_to(output_root)
        except ValueError:
            files.append(candidate)
    return sorted(files, key=lambda path: str(path).lower())


def main() -> int:
    parser = argparse.ArgumentParser(description="Demucs vocal cleanup for Suno tracks. Originals remain untouched.")
    parser.add_argument("--input-root", required=True, type=Path, help="Folder containing source audio")
    parser.add_argument("--output-root", required=True, type=Path, help="Folder for cleaned WAV output")
    parser.add_argument("--strength", type=float, default=3.0, help="1–6; upper-partial suppression")
    parser.add_argument("--blend", type=float, default=0.75, help="0–1; repaired-vocal mix")
    parser.add_argument("--segment", type=int, default=7, help="Demucs CUDA segment, 1–7 seconds")
    parser.add_argument("--force", action="store_true", help="Replace existing output files")
    arguments = parser.parse_args()

    if not arguments.input_root.is_dir():
        parser.error("--input-root must be an existing directory")
    if not 1 <= arguments.strength <= 6 or not 0 <= arguments.blend <= 1:
        parser.error("--strength must be 1–6 and --blend must be 0–1")
    if not 1 <= arguments.segment <= 7:
        parser.error("--segment must be an integer from 1 to 7")
    if not shutil.which("ffmpeg"):
        sys.exit("ERROR: ffmpeg was not found in PATH.")

    import torch
    if not torch.cuda.is_available():
        sys.exit("ERROR: CUDA is not available. Install a CUDA-enabled PyTorch build; this backend has no CPU fallback.")

    input_root = arguments.input_root.resolve()
    output_root = arguments.output_root.resolve()
    files = collect_files(input_root, output_root)
    if not files:
        sys.exit("No supported audio files were found in the input folder.")
    print(f"Using GPU: {torch.cuda.get_device_name(0)} | Demucs segment: {arguments.segment}s", flush=True)

    failed = 0
    for index, source in enumerate(files, 1):
        relative = source.relative_to(input_root)
        destination = output_path(output_root, relative)
        relative_text = str(relative).replace("\\", "/")
        if destination.exists() and not arguments.force:
            emit("skip", index, len(files), relative_text, "Skipped existing cleaned file")
            continue
        emit("running", index - 1, len(files), relative_text, f"Cleaning {relative.name}")
        try:
            clean_file(source, destination, arguments.strength, arguments.blend, arguments.segment)
            emit("done", index, len(files), relative_text, f"Saved {destination.name}")
        except Exception as exc:  # Keep the batch running and make the failure visible per track.
            failed += 1
            emit("failed", index, len(files), relative_text, f"Failed: {exc}")
            print(f"FAILED {source}: {exc}", file=sys.stderr, flush=True)

    print(f"Done. Failed: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
