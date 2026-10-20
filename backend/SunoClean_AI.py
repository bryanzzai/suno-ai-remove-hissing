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
PROFILE_NAMES = ["Off", "Light", "Normal", "Strong", "Brutal"]
DYNAMIC_PROFILES = {
    1: {"threshold_db": 4.5, "maximum_reduction_db": 2.5, "release_seconds": 0.22},
    2: {"threshold_db": 4.0, "maximum_reduction_db": 3.0, "release_seconds": 0.25},
    3: {"threshold_db": 3.0, "maximum_reduction_db": 4.5, "release_seconds": 0.30},
    4: {"threshold_db": 2.0, "maximum_reduction_db": 6.0, "release_seconds": 0.35},
}
HARMONIC_PROFILES = {
    1: {"maximum_reduction_db": 5.0, "prominence_scale": 1.7},
    2: {"maximum_reduction_db": 6.0, "prominence_scale": 1.5},
    3: {"maximum_reduction_db": 8.0, "prominence_scale": 1.3},
    4: {"maximum_reduction_db": 10.0, "prominence_scale": 1.1},
}


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


def harmonic_de_fizzer(audio: np.ndarray, rate: int, profile: int) -> tuple[np.ndarray, dict[str, object]]:
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
    settings = HARMONIC_PROFILES[profile]
    maximum_reduction_db = settings["maximum_reduction_db"]
    ridge_mask = np.clip(prominence / settings["prominence_scale"], 0.0, 1.0)
    ramp_up = np.clip((freqs - 3500.0) / 1000.0, 0.0, 1.0)
    ramp_down = np.clip((11000.0 - freqs) / 1500.0, 0.0, 1.0)
    target_mask = ridge_mask * (ramp_up * ramp_down)[:, None]
    target_mask = gaussian_filter1d(target_mask, 0.8, axis=0)
    target_mask = gaussian_filter1d(target_mask, 0.6, axis=1)
    gain = 10.0 ** (-(maximum_reduction_db * target_mask) / 20.0)

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
        "profile": PROFILE_NAMES[profile],
        "band_hz": [3500, 11000],
        "maximum_reduction_db": maximum_reduction_db,
        "prominence_scale": settings["prominence_scale"],
        "affected_spectral_cells_percent": round(float(np.mean(target_mask[target_band] >= 0.05) * 100.0), 3),
        "mean_reduction_db_in_affected_cells": round(float(np.mean(maximum_reduction_db * target_mask[target_mask >= 0.05])), 3)
        if np.any(target_mask >= 0.05) else 0.0,
    }
    return output, report


def dynamic_full_mix_test(audio: np.ndarray, rate: int, profile: int) -> tuple[np.ndarray, dict[str, object]]:
    """An intentionally audible whole-mix dynamic EQ proof.

    The detector uses the mono sum to preserve stereo placement.  When energy
    in 1.8–4.0 kHz exceeds its local 1-second median by 4 dB, the same gain is
    applied to both channels: up to -3 dB for at least 250 ms.  This is a
    diagnostic renderer, not yet the final adaptive repair algorithm.
    """
    nfft = 2048 if rate <= 48000 else 4096
    hop = nfft // 4
    settings = DYNAMIC_PROFILES[profile]
    threshold_db = settings["threshold_db"]
    maximum_reduction_db = settings["maximum_reduction_db"]
    release_seconds = settings["release_seconds"]
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
    excess_db = np.maximum(0.0, band_db - (local_floor_db + threshold_db))

    requested_reduction_db = np.minimum(maximum_reduction_db, excess_db * 0.5)
    held_reduction_db = requested_reduction_db.copy()
    release_frames = max(1, int(np.ceil(release_seconds * rate / hop)))
    for frame in range(1, len(held_reduction_db)):
        held_reduction_db[frame] = max(
            requested_reduction_db[frame],
            held_reduction_db[frame - 1] - maximum_reduction_db / release_frames,
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
        "profile": PROFILE_NAMES[profile],
        "band_hz": [1800, 4000],
        "trigger_above_local_median_db": threshold_db,
        "maximum_reduction_db": maximum_reduction_db,
        "release_seconds": release_seconds,
        "events": events,
    }
    return output, report


def output_path(output_root: Path, relative: Path, mode: str, output_format: str) -> Path:
    suffixes = {
        "dynamic": "_D",
        "harmonic": "_H",
        "dynamic_harmonic": "_D&H",
    }
    return (output_root / relative.parent / relative.stem / f"{relative.stem}{suffixes[mode]}.{output_format}").resolve()


def clean_file(source: Path, destination: Path, dynamic_profile: int, harmonic_profile: int) -> None:
    with tempfile.TemporaryDirectory(prefix="sunoclean_") as raw_workspace:
        workspace = Path(raw_workspace)
        input_wav = workspace / "input.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", input_wav])
        rate, original = read_audio(input_wav)
        output = original
        reports = []
        if dynamic_profile:
            output, dynamic_report = dynamic_full_mix_test(output, rate, dynamic_profile)
            reports.append(dynamic_report)
        if harmonic_profile:
            output, harmonic_report = harmonic_de_fizzer(output, rate, harmonic_profile)
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
        if destination.suffix.lower() == ".m4a":
            # Processed audio is input 0; input 1 supplies source tags and cover art.
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-i", staged, "-i", source,
                 "-map", "0:a:0", "-map", "1:v?", "-map_metadata", "1",
                 "-c:a", "aac", "-b:a", "256k", "-c:v", "copy",
                 "-disposition:v:0", "attached_pic", "-movflags", "+faststart", destination])
        else:
            shutil.copy2(staged, destination)
        removed_intermediate = workspace / "removed_float.wav"
        wavfile.write(removed_intermediate, rate, removed.astype(np.float32))
        for suffix in ("_D&H", "_D", "_H"):
            if destination.stem.endswith(suffix):
                removed_stem = destination.stem[:-len(suffix)] + "_REMOVED" + suffix
                break
        else:
            raise RuntimeError("Could not derive the removed-signal file name.")
        removed_destination = destination.with_name(f"{removed_stem}.wav")
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
    parser.add_argument("--output-root", required=True, type=Path, help="Folder for cleaned output")
    parser.add_argument("--selected-list", required=True, type=Path,
                        help="UTF-8 text file containing selected paths relative to input root")
    parser.add_argument("--dynamic-profile", required=True, type=int, choices=range(0, 5),
                        help="0=Off, 1=Light, 2=Normal, 3=Strong, 4=Brutal")
    parser.add_argument("--harmonic-profile", required=True, type=int, choices=range(0, 5),
                        help="0=Off, 1=Light, 2=Normal, 3=Strong, 4=Brutal")
    parser.add_argument("--output-format", required=True, choices=("wav", "m4a"),
                        help="Cleaned output format. REMOVED output is always WAV.")
    parser.add_argument("--force", action="store_true", help="Replace existing output files")
    arguments = parser.parse_args()

    if not arguments.input_root.is_dir():
        parser.error("--input-root must be an existing directory")
    if not arguments.selected_list.is_file():
        parser.error("--selected-list must be an existing text file")
    if not arguments.dynamic_profile and not arguments.harmonic_profile:
        parser.error("Choose at least one whole-mix effect.")
    if not shutil.which("ffmpeg"):
        sys.exit("ERROR: ffmpeg was not found in PATH.")

    input_root = arguments.input_root.resolve()
    output_root = arguments.output_root.resolve()
    files = collect_files(input_root, output_root, arguments.selected_list)
    if not files:
        sys.exit("No supported audio files were found in the input folder.")
    print(f"Whole-mix processing: dynamic={PROFILE_NAMES[arguments.dynamic_profile]}, "
          f"harmonic={PROFILE_NAMES[arguments.harmonic_profile]}; Demucs/GPU are not used.", flush=True)

    failed = 0
    for index, source in enumerate(files, 1):
        relative = source.relative_to(input_root)
        mode_key = ("dynamic_harmonic" if arguments.dynamic_profile and arguments.harmonic_profile
                    else "dynamic" if arguments.dynamic_profile
                    else "harmonic")
        destination = output_path(output_root, relative, mode_key, arguments.output_format)
        relative_text = str(relative).replace("\\", "/")
        if destination.exists() and not arguments.force:
            emit("skip", index, len(files), relative_text, "Skipped existing cleaned file")
            continue
        mode = ("Applying dynamic and harmonic profiles" if arguments.dynamic_profile and arguments.harmonic_profile
                else "Applying dynamic profile" if arguments.dynamic_profile else "Applying harmonic profile")
        emit("running", index - 1, len(files), relative_text, f"{mode}: {relative.name}")
        try:
            clean_file(source, destination, arguments.dynamic_profile, arguments.harmonic_profile)
            emit("done", index, len(files), relative_text, f"Saved {destination.name}")
        except Exception as exc:  # Keep the batch running and make the failure visible per track.
            failed += 1
            emit("failed", index, len(files), relative_text, f"Failed: {exc}")
            print(f"FAILED {source}: {exc}", file=sys.stderr, flush=True)

    print(f"Done. Failed: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
