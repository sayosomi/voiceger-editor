"""Shared temporary-audio preparation for forced LAB alignment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALIGNMENT_SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class PreparedAlignmentAudio:
    """Metadata for a temporary mono 16 kHz PCM alignment copy."""

    original_duration_seconds: float
    alignment_duration_seconds: float
    samples: Any


def prepare_alignment_wav(source: Path, destination: Path) -> PreparedAlignmentAudio:
    """Create a mono 16 kHz PCM16 copy without changing the accepted WAV."""

    import numpy as np
    import soundfile as sf

    source = Path(source)
    destination = Path(destination)
    data, source_rate = sf.read(
        source,
        dtype="float32",
        always_2d=True,
    )
    if data.shape[0] == 0:
        raise ValueError("accepted WAV contains no samples")

    mono = data.mean(axis=1, dtype=np.float32)
    if source_rate != ALIGNMENT_SAMPLE_RATE:
        target_count = max(
            1,
            int(round(len(mono) * ALIGNMENT_SAMPLE_RATE / source_rate)),
        )
        source_positions = np.arange(len(mono), dtype=np.float64)
        target_positions = (
            np.arange(target_count, dtype=np.float64)
            * source_rate
            / ALIGNMENT_SAMPLE_RATE
        )
        target_positions = np.minimum(target_positions, len(mono) - 1)
        mono = np.interp(
            target_positions,
            source_positions,
            mono,
        ).astype(np.float32)

    sf.write(
        destination,
        mono,
        ALIGNMENT_SAMPLE_RATE,
        subtype="PCM_16",
        format="WAV",
    )
    samples, written_rate = sf.read(destination, dtype="int16")
    if written_rate != ALIGNMENT_SAMPLE_RATE:
        raise RuntimeError(
            f"alignment WAV has unexpected sample rate: {written_rate}"
        )
    if getattr(samples, "ndim", 1) != 1:
        raise RuntimeError("alignment WAV must be mono")

    original_duration = float(sf.info(source).duration)
    alignment_duration = len(samples) / ALIGNMENT_SAMPLE_RATE
    if abs(original_duration - alignment_duration) > 0.001:
        raise RuntimeError(
            "16 kHz alignment copy changed duration unexpectedly: "
            f"source={original_duration:.6f}s "
            f"alignment={alignment_duration:.6f}s"
        )
    return PreparedAlignmentAudio(
        original_duration_seconds=original_duration,
        alignment_duration_seconds=alignment_duration,
        samples=samples,
    )
