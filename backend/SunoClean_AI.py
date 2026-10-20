#!/usr/bin/env python3
"""SunoClean AI backend: direct whole-mix artifact reduction."""
from __future__ import annotations

import argparse
import json
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


def harmonic_de_fizzer(audio: np.ndarray, rate: int) -> tuple[np.ndarray, dict[str, object]]:
    """Whole-mix high-partial test, deliberately stronger than the final target.

    This does not claim to identify a singer's true fundamental.  It finds
    unusually narrow high-frequency spectral ridges relative to neighbouring
    frequency bins, then suppresses those ridges by up to 6 dB.  One mono
    detector controls both channels so the stereo image remains intact.
    """
    nfft = 4096 if rate <= 48000 else 8192
    hop = nfft // 4
    mono = audio.mean(axis=1)
    freqs, _, detector_spectrum = stft(mono, fs=rate, nperseg=nfft, noverlap=nfft - hop,
                                       boundary="zeros")
    magnitude = np.abs(detector_spectrum)
    local_envelope = median_filter(magnitude, size=(17, 3), mode="nearest")
    prominence = np.maximum(magnitude / (local_envelope + 1e-9) - 1.0, 0.0)
    ridge_mask = np.clip(prominence / 1.5, 0.0, 1.0)
    ramp_up = np.clip((freqs - 3500.0) / 1000.0, 0.0, 1.0)
    ramp_down = np.clip((11000.0 - freqs) / 1500.0, 0.0, 1.0)
    target_mask = ridge_mask * (ramp_up * ramp_down)[:, None]
    target_mask = gaussian_filter1d(target_mask, 0.8, axis=0)
    target_mask = gaussian_filter1d(target_mask, 0.6, axis=1)
    gain = 10.0 ** (-(6.0 * target_mask) / 20.0)

    channels = []
    for channel in range(audio.shape[1]):
        _, _, spectrum = stft(audio[:, channel], fs=rate, nperseg=nfft, noverlap=nfft - hop,
                              boundary="zeros")
        _, output = istft(spectrum * gain, fs=rate, nperseg=nfft, noverlap=nfft - hop,
                          input_onesided=True, boundary=True)
        channels.append(output[:len(audio)])
    output = np.column_stack(channels).astype(np.float32)
    target_band = (freqs >= 3500.0) & (freqs <= 11000.0)
    report: dict[str, object] = {
        "mode": "whole_mix_harmonic_de_fizzer_test",
        "band_hz": [3500, 11000],
        "maximum_reduction_db": 6.0,
        "affected_spectral_cells_percent": round(float(np.mean(target_mask[target_band] >= 0.05) * 100.0), 3),
        "mean_reduction_db_in_affected_cells": round(float(np.mean(6.0 * target_mask[target_mask >= 0.05])), 3)
        if np.any(target_mask >= 0.05) else 0.0,
    }
    return output, report


def dynamic_full_mix_test(audio: np.ndarray, rate: int) -> tuple[np.ndarray, dict[str, object]]:
    """An intentionally audible whole-mix dynamic EQ proof.

    The detector uses the mono sum to preserve stereo placement.  When energy
    in 1.8–4.0 kHz exceeds its local 1-second median by 4 dB, the same gain is
    applied to both channels: up to -3 dB for at least 250 ms.  This is a
    diagnostic renderer, not yet the final adaptive repair algorithm.
    """
    nfft = 2048 if rate <= 48000 else 4096
    hop = nfft // 4
    mono = audio.mean(axis=1)
    freqs, _, detector_spectrum = stft(mono, fs=rate, nperseg=nfft, noverlap=nfft - hop,
                                       boundary="zeros")
    band = (freqs >= 1800.0) & (freqs <= 4000.0)
    band_power = np.mean(np.abs(detector_spectrum[band]) ** 2, axis=0)
    band_db = 10.0 * np.log10(band_power + 1e-12)
    local_frames = max(3, int(round(rate / hop)))
    if local_frames % 2 == 0:
        local_frames += 1
    local_floor_db = median_filter(band_db, size=local_frames, mode="nearest")
    excess_db = np.maximum(0.0, band_db - (local_floor_db + 4.0))

    # 4 dB above the local floor begins reduction; 10 dB over it reaches -3 dB.
    requested_reduction_db = np.minimum(3.0, excess_db * 0.5)
    held_reduction_db = requested_reduction_db.copy()
    hold_frames = max(1, int(np.ceil(0.250 * rate / hop)))
    for frame in range(1, len(held_reduction_db)):
        held_reduction_db[frame] = max(
            requested_reduction_db[frame],
            held_reduction_db[frame - 1] - 3.0 / hold_frames,
        )

    gains = 10.0 ** (-held_reduction_db / 20.0)
    _, _, spectrum = stft(audio, fs=rate, nperseg=nfft, noverlap=nfft - hop,
                          axis=0, boundary="zeros")
    # scipy keeps a non-time channel axis between frequency and time here.
    spectrum[band, :, :] *= gains[None, None, :]
    _, output = istft(spectrum, fs=rate, nperseg=nfft, noverlap=nfft - hop,
                      input_onesided=True, time_axis=2, freq_axis=0, boundary=True)
    output = output.T[: len(audio)].astype(np.float32)
    events = []
    active = held_reduction_db >= 0.1
    start = None
    for index, is_active in enumerate(np.append(active, False)):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            end = index
            peak_index = start + int(np.argmax(held_reduction_db[start:end]))
            events.append({
                "start_seconds": round(start * hop / rate, 3),
                "end_seconds": round(end * hop / rate, 3),
                "peak_seconds": round(peak_index * hop / rate, 3),
                "peak_reduction_db": round(float(held_reduction_db[peak_index]), 3),
            })
            start = None
    report: dict[str, object] = {
        "mode": "whole_mix_dynamic_band_test",
        "band_hz": [1800, 4000],
        "trigger_above_local_median_db": 4.0,
        "maximum_reduction_db": 3.0,
        "hold_seconds": 0.250,
        "events": events,
    }
    return output, report


def output_path(output_root: Path, relative: Path, mode: str) -> Path:
    suffixes = {
        "dynamic": "DYNAMIC_1P8_4K.wav",
        "harmonic": "HARMONIC_DE_FIZZ.wav",
        "dynamic_harmonic": "DYNAMIC_AND_HARMONIC.wav",
    }
    return (output_root / relative.parent / relative.stem / suffixes[mode]).resolve()


def clean_file(source: Path, destination: Path, dynamic_full_mix_test_enabled: bool,
               harmonic_de_fizzer_enabled: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="sunoclean_") as raw_workspace:
        workspace = Path(raw_workspace)
        input_wav = workspace / "input.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", input_wav])
        rate, original = read_audio(input_wav)
        output = original
        reports = []
        if dynamic_full_mix_test_enabled:
            output, dynamic_report = dynamic_full_mix_test(output, rate)
            reports.append(dynamic_report)
        if harmonic_de_fizzer_enabled:
            output, harmonic_report = harmonic_de_fizzer(output, rate)
            reports.append(harmonic_report)
        removed = original[:len(output)] - output
        report = {"effects": reports}
        peak = float(np.max(np.abs(output)))
        if peak > 0.99:
            output *= 0.99 / peak
            removed = original[:len(output)] - output

        intermediate = workspace / "repaired_float.wav"
        wavfile.write(intermediate, rate, output.astype(np.float32))
        staged = workspace / "final.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", intermediate,
             "-c:a", "pcm_s24le", staged])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, destination)
        removed_intermediate = workspace / "removed_float.wav"
        wavfile.write(removed_intermediate, rate, removed.astype(np.float32))
        removed_destination = destination.with_name(f"REMOVED_BY_{destination.stem}.wav")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", removed_intermediate,
             "-c:a", "pcm_s24le", removed_destination])
        report_destination = destination.with_suffix(".json")
        report_destination.write_text(json.dumps(report, indent=2), encoding="utf-8")


def collect_files(input_root: Path, output_root: Path, selected_list: Path) -> list[Path]:
    output_root = output_root.resolve()
    selected = {
        line.strip().replace("\\", "/")
        for line in selected_list.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if not selected:
        raise ValueError("The selected-file list is empty.")
    files = []
    for candidate in input_root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.lower() not in EXTENSIONS:
            continue
        try:
            candidate.resolve().relative_to(output_root)
        except ValueError:
            relative = candidate.resolve().relative_to(input_root.resolve()).as_posix()
            if relative in selected:
                files.append(candidate)
    return sorted(files, key=lambda path: str(path).lower())


def main() -> int:
    parser = argparse.ArgumentParser(description="Whole-mix artifact reduction for selected Suno tracks. Originals remain untouched.")
    parser.add_argument("--input-root", required=True, type=Path, help="Folder containing source audio")
    parser.add_argument("--output-root", required=True, type=Path, help="Folder for cleaned WAV output")
    parser.add_argument("--selected-list", required=True, type=Path,
                        help="UTF-8 text file containing selected paths relative to input root")
    parser.add_argument("--dynamic-full-mix-test", action="store_true",
                        help="Whole-mix dynamic test: up to -3 dB at 1.8–4.0 kHz for 250 ms after strong transients")
    parser.add_argument("--harmonic-de-fizzer", action="store_true",
                        help="Whole-mix test: attenuate unusually prominent high-frequency spectral ridges up to 6 dB")
    parser.add_argument("--force", action="store_true", help="Replace existing output files")
    arguments = parser.parse_args()

    if not arguments.input_root.is_dir():
        parser.error("--input-root must be an existing directory")
    if not arguments.selected_list.is_file():
        parser.error("--selected-list must be an existing text file")
    if not arguments.dynamic_full_mix_test and not arguments.harmonic_de_fizzer:
        parser.error("Choose at least one whole-mix effect.")
    if not shutil.which("ffmpeg"):
        sys.exit("ERROR: ffmpeg was not found in PATH.")

    input_root = arguments.input_root.resolve()
    output_root = arguments.output_root.resolve()
    files = collect_files(input_root, output_root, arguments.selected_list)
    if not files:
        sys.exit("No supported audio files were found in the input folder.")
    print("Whole-mix processing: direct CPU DSP; Demucs/GPU are not used.", flush=True)

    failed = 0
    for index, source in enumerate(files, 1):
        relative = source.relative_to(input_root)
        mode_key = ("dynamic_harmonic" if arguments.dynamic_full_mix_test and arguments.harmonic_de_fizzer
                    else "dynamic" if arguments.dynamic_full_mix_test
                    else "harmonic")
        destination = output_path(output_root, relative, mode_key)
        relative_text = str(relative).replace("\\", "/")
        if destination.exists() and not arguments.force:
            emit("skip", index, len(files), relative_text, "Skipped existing cleaned file")
            continue
        mode = ("Testing dynamic 1.8–4 kHz compression plus harmonic de-fizzer" if arguments.dynamic_full_mix_test and arguments.harmonic_de_fizzer
                else "Testing whole-mix dynamic 1.8–4 kHz compression" if arguments.dynamic_full_mix_test
                else "Testing whole-mix harmonic de-fizzer")
        emit("running", index - 1, len(files), relative_text, f"{mode}: {relative.name}")
        try:
            clean_file(source, destination, arguments.dynamic_full_mix_test, arguments.harmonic_de_fizzer)
            emit("done", index, len(files), relative_text, f"Saved {destination.name}")
        except Exception as exc:  # Keep the batch running and make the failure visible per track.
            failed += 1
            emit("failed", index, len(files), relative_text, f"Failed: {exc}")
            print(f"FAILED {source}: {exc}", file=sys.stderr, flush=True)

    print(f"Done. Failed: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
