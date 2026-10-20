#!/usr/bin/env python3
"""SunoClean AI backend: Demucs vocal separation plus conservative spectral repair.

The filter only changes the estimated vocal stem and writes a separate 24-bit
WAV below the chosen output root. It is intentionally conservative: it reduces
prominent upper-frequency ridges often heard as metallic fizz in generated
vocals; it is not a general-purpose noise remover.
"""
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


def raw_tin_can_reduction(channel: np.ndarray, rate: int) -> np.ndarray:
    """Fixed, intentionally blunt accompaniment EQ for A/B evaluation.

    This is not a transient detector. It reduces the two requested bands for
    the entire accompaniment stem: 1.8–2.2 kHz by 3 dB and 2.2–4.0 kHz by
    1.5 dB. The vocal stem stays untouched.
    """
    nfft = 4096 if rate <= 48000 else 8192
    hop = nfft // 4
    freqs, _, spectrum = stft(channel, fs=rate, nperseg=nfft, noverlap=nfft - hop, boundary="zeros")
    gain = np.ones_like(freqs, dtype=np.float32)
    gain[(freqs >= 1800.0) & (freqs < 2200.0)] = 10.0 ** (-3.0 / 20.0)
    gain[(freqs >= 2200.0) & (freqs <= 4000.0)] = 10.0 ** (-1.5 / 20.0)
    _, output = istft(spectrum * gain[:, None], fs=rate, nperseg=nfft, noverlap=nfft - hop,
                      input_onesided=True, boundary=True)
    return output[: len(channel)].astype(np.float32)


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
        "clean": "_CLEANED.wav",
        "tin_can": "_TIN_CAN_TEST.wav",
        "dynamic": "_DYNAMIC_1P8_4K_TEST.wav",
    }
    suffix = suffixes[mode]
    return (output_root / relative.parent / f"{relative.stem}{suffix}").resolve()


def clean_file(source: Path, destination: Path, strength: float, blend: float, segment: int,
               tin_can_test: bool, dynamic_full_mix_test_enabled: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="sunoclean_") as raw_workspace:
        workspace = Path(raw_workspace)
        input_wav = workspace / "input.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", input_wav])
        dynamic_report = None
        if dynamic_full_mix_test_enabled:
            rate, original = read_audio(input_wav)
            output, dynamic_report = dynamic_full_mix_test(original, rate)
            removed = original[:len(output)] - output
        else:
            run([sys.executable, "-m", "demucs", "-n", "htdemucs", "--two-stems", "vocals", "--device", "cuda",
                 "--segment", str(segment), "--overlap", "0.25", "-o", workspace / "stems", input_wav])
            stem_root = workspace / "stems" / "htdemucs" / "input"
            rate, vocals = read_audio(stem_root / "vocals.wav")
            accompaniment_rate, accompaniment = read_audio(stem_root / "no_vocals.wav")
            if rate != accompaniment_rate:
                raise RuntimeError("Demucs returned mismatched stem sample rates.")
            samples = min(len(vocals), len(accompaniment))
            vocals, accompaniment = vocals[:samples], accompaniment[:samples]
            if tin_can_test:
                repaired_accompaniment = np.column_stack([
                    raw_tin_can_reduction(accompaniment[:, channel], rate)
                    for channel in range(accompaniment.shape[1])
                ])
                output = vocals + repaired_accompaniment
            else:
                repaired_vocals = np.column_stack([
                    repair(vocals[:, channel], rate, strength, blend)
                    for channel in range(vocals.shape[1])
                ])
                output = repaired_vocals + accompaniment
        peak = float(np.max(np.abs(output)))
        if peak > 0.99:
            output *= 0.99 / peak
            if dynamic_full_mix_test_enabled:
                # The report mode is expected to remain below full scale, but
                # keep its difference signal truthful if safety scaling occurs.
                removed = original[:len(output)] - output

        intermediate = workspace / "repaired_float.wav"
        wavfile.write(intermediate, rate, output.astype(np.float32))
        staged = workspace / "final.wav"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", intermediate,
             "-c:a", "pcm_s24le", staged])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, destination)
        if dynamic_full_mix_test_enabled:
            removed_intermediate = workspace / "removed_float.wav"
            wavfile.write(removed_intermediate, rate, removed.astype(np.float32))
            removed_destination = destination.with_name(destination.stem.replace("_DYNAMIC_1P8_4K_TEST", "_REMOVED_BY_DYNAMIC_TEST") + ".wav")
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", removed_intermediate,
                 "-c:a", "pcm_s24le", removed_destination])
            report_destination = destination.with_suffix(".json")
            report_destination.write_text(json.dumps(dynamic_report, indent=2), encoding="utf-8")


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
    parser.add_argument("--tin-can-test", action="store_true",
                        help="Apply fixed -3 dB (1.8–2.2 kHz) and -1.5 dB (2.2–4.0 kHz) to accompaniment only")
    parser.add_argument("--dynamic-full-mix-test", action="store_true",
                        help="Whole-mix dynamic test: up to -3 dB at 1.8–4.0 kHz for 250 ms after strong transients")
    parser.add_argument("--force", action="store_true", help="Replace existing output files")
    arguments = parser.parse_args()

    if not arguments.input_root.is_dir():
        parser.error("--input-root must be an existing directory")
    if not 1 <= arguments.strength <= 6 or not 0 <= arguments.blend <= 1:
        parser.error("--strength must be 1–6 and --blend must be 0–1")
    if not 1 <= arguments.segment <= 7:
        parser.error("--segment must be an integer from 1 to 7")
    if arguments.tin_can_test and arguments.dynamic_full_mix_test:
        parser.error("Choose either --tin-can-test or --dynamic-full-mix-test, not both.")
    if not shutil.which("ffmpeg"):
        sys.exit("ERROR: ffmpeg was not found in PATH.")

    input_root = arguments.input_root.resolve()
    output_root = arguments.output_root.resolve()
    files = collect_files(input_root, output_root)
    if not files:
        sys.exit("No supported audio files were found in the input folder.")
    if arguments.dynamic_full_mix_test:
        print("Whole-mix dynamic test: direct CPU DSP; Demucs/GPU are intentionally not used.", flush=True)
    else:
        import torch
        if not torch.cuda.is_available():
            sys.exit("ERROR: CUDA is not available. Install a CUDA-enabled PyTorch build; this backend has no CPU fallback.")
        print(f"Using GPU: {torch.cuda.get_device_name(0)} | Demucs segment: {arguments.segment}s", flush=True)

    failed = 0
    for index, source in enumerate(files, 1):
        relative = source.relative_to(input_root)
        mode_key = "dynamic" if arguments.dynamic_full_mix_test else ("tin_can" if arguments.tin_can_test else "clean")
        destination = output_path(output_root, relative, mode_key)
        relative_text = str(relative).replace("\\", "/")
        if destination.exists() and not arguments.force:
            emit("skip", index, len(files), relative_text, "Skipped existing cleaned file")
            continue
        mode = ("Testing whole-mix dynamic 1.8–4 kHz compression" if arguments.dynamic_full_mix_test
                else "Testing tin-can reduction" if arguments.tin_can_test else "Cleaning vocal artifacts")
        emit("running", index - 1, len(files), relative_text, f"{mode}: {relative.name}")
        try:
            clean_file(source, destination, arguments.strength, arguments.blend, arguments.segment,
                       arguments.tin_can_test, arguments.dynamic_full_mix_test)
            emit("done", index, len(files), relative_text, f"Saved {destination.name}")
        except Exception as exc:  # Keep the batch running and make the failure visible per track.
            failed += 1
            emit("failed", index, len(files), relative_text, f"Failed: {exc}")
            print(f"FAILED {source}: {exc}", file=sys.stderr, flush=True)

    print(f"Done. Failed: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
