"""English forced alignment for production LAB sidecars."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import wave

from .english_stress import normalize_english_phonemes
from .lab_audio import ALIGNMENT_SAMPLE_RATE, prepare_alignment_wav
from .voicevox_api_models import AudioQuery


LAB_UNITS_PER_SECOND = 10_000_000
POCKETSPHINX_DICTIONARY_WORD = "voicegerutt"
POCKETSPHINX_SILENCE_PHONES = frozenset({"SIL"})
CONTIGUITY_TOLERANCE_SECONDS = 0.015
ENGLISH_NON_ACOUSTIC_TOKENS = frozenset({"!", "?", "…", ",", ".", "-"})
ENGLISH_VOWELS = frozenset(
    {
        "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER",
        "EY", "IH", "IY", "OW", "OY", "UH", "UW",
    }
)


@dataclass(frozen=True)
class TimedAlignment:
    start_seconds: float
    end_seconds: float
    phoneme: str


def english_query_phonemes(query: AudioQuery) -> list[str]:
    """Return the exact editable Voiceger ARPAbet snapshot for pure English."""

    segments = query.voicegerSegments
    if not segments:
        raise ValueError("PocketSphinx LAB alignment requires voicegerSegments")
    if any(segment.language != "en" for segment in segments):
        raise ValueError("PocketSphinx LAB alignment requires a pure English query")

    result: list[str] = []
    for segment in segments:
        if segment.phonemes is None:
            raise ValueError("English query segment contains no phoneme override")
        result.extend(normalize_english_phonemes(segment.phonemes))
    if not result:
        raise ValueError("English query contains no phonemes")
    return result


def to_pocketsphinx_phonemes(phonemes: list[str]) -> list[str]:
    """Strip stress only at the PocketSphinx acoustic boundary."""

    normalized = normalize_english_phonemes(phonemes)
    result: list[str] = []
    for phoneme in normalized:
        if phoneme in ENGLISH_NON_ACOUSTIC_TOKENS:
            continue
        if phoneme == "UNK":
            raise ValueError(
                "Voiceger returned UNK; refusing to invent an English pronunciation"
            )
        if len(phoneme) >= 2 and phoneme[-1] in "012":
            base = phoneme[:-1]
            if base not in ENGLISH_VOWELS:
                raise ValueError(
                    f"unexpected stress digit on non-vowel English phone: {phoneme!r}"
                )
            result.append(base)
        else:
            result.append(phoneme)
    if not result:
        raise ValueError("English pronunciation contains no acoustic phones")
    return result


def _run_pocketsphinx(
    wav_path: Path,
    phonemes: list[str],
) -> list[TimedAlignment]:
    try:
        from pocketsphinx import Decoder
    except ImportError as exc:
        raise RuntimeError(
            "PocketSphinx 5.1.1 is required for English LAB output; "
            "install the adapter's 'lab' extra"
        ) from exc

    with wave.open(str(wav_path), "rb") as wav_file:
        if wav_file.getnchannels() != 1:
            raise ValueError("PocketSphinx alignment WAV must be mono")
        if wav_file.getsampwidth() != 2:
            raise ValueError("PocketSphinx alignment WAV must be 16-bit PCM")
        sample_rate = wav_file.getframerate()
        if sample_rate != ALIGNMENT_SAMPLE_RATE:
            raise ValueError(
                "PocketSphinx alignment WAV must be 16 kHz, "
                f"got {sample_rate}"
            )
        audio = wav_file.readframes(wav_file.getnframes())

    decoder = Decoder(lm=None, samprate=sample_rate)
    decoder.add_word(POCKETSPHINX_DICTIONARY_WORD, " ".join(phonemes))
    decoder.set_align_text(POCKETSPHINX_DICTIONARY_WORD)

    decoder.start_utt()
    decoder.process_raw(audio, full_utt=True)
    decoder.end_utt()
    hypothesis = decoder.hyp()
    if (
        hypothesis is None
        or hypothesis.hypstr != POCKETSPHINX_DICTIONARY_WORD
    ):
        got = None if hypothesis is None else hypothesis.hypstr
        raise RuntimeError(
            "PocketSphinx word alignment failed: "
            f"expected {POCKETSPHINX_DICTIONARY_WORD!r}, got {got!r}"
        )

    decoder.set_alignment()
    decoder.start_utt()
    decoder.process_raw(audio, full_utt=True)
    decoder.end_utt()
    alignment = decoder.get_alignment()
    if alignment is None:
        raise RuntimeError("PocketSphinx returned no phone alignment")

    result = [
        TimedAlignment(
            phone.start / 100.0,
            (phone.start + phone.duration) / 100.0,
            phone.name,
        )
        for phone in alignment.phones()
    ]
    if not result:
        raise RuntimeError("PocketSphinx returned no phone alignment")
    return result


def render_pocketsphinx_lab(
    alignments: list[TimedAlignment],
    expected_phonemes: list[str],
    *,
    wav_duration_seconds: float,
) -> str:
    actual = [
        item.phoneme
        for item in alignments
        if item.phoneme not in POCKETSPHINX_SILENCE_PHONES
    ]
    if actual != expected_phonemes:
        raise RuntimeError(
            "PocketSphinx aligned phone sequence does not match the accepted query: "
            f"expected={' '.join(expected_phonemes)!r}, actual={' '.join(actual)!r}"
        )
    if wav_duration_seconds <= 0:
        raise ValueError("accepted WAV duration must be positive")

    rendered: list[tuple[float, float, str]] = []
    previous_end = 0.0
    for item in alignments:
        start = max(0.0, item.start_seconds)
        end = min(wav_duration_seconds, item.end_seconds)
        if start > wav_duration_seconds + CONTIGUITY_TOLERANCE_SECONDS:
            raise RuntimeError("PocketSphinx returned a phone after WAV end")

        if rendered:
            gap = start - previous_end
            if abs(gap) <= CONTIGUITY_TOLERANCE_SECONDS:
                start = previous_end
            elif gap > 0:
                raise RuntimeError(
                    "PocketSphinx phone alignment contains an internal gap; "
                    "refusing to invent timing"
                )
            else:
                raise RuntimeError(
                    "PocketSphinx phone alignment contains overlapping intervals"
                )
        elif start > CONTIGUITY_TOLERANCE_SECONDS:
            rendered.append((0.0, start, "pau"))
        else:
            start = 0.0

        if end <= start:
            raise RuntimeError(
                f"PocketSphinx interval collapsed for {item.phoneme!r}"
            )
        label = (
            "pau"
            if item.phoneme in POCKETSPHINX_SILENCE_PHONES
            else item.phoneme
        )
        rendered.append((start, end, label))
        previous_end = end

    if previous_end < wav_duration_seconds - CONTIGUITY_TOLERANCE_SECONDS:
        rendered.append((previous_end, wav_duration_seconds, "pau"))
    elif rendered:
        start, _, label = rendered[-1]
        rendered[-1] = (start, wav_duration_seconds, label)

    return "".join(
        f"{round(start * LAB_UNITS_PER_SECOND)} "
        f"{round(end * LAB_UNITS_PER_SECOND)} {label}\n"
        for start, end, label in rendered
    )


def align_english_lab(wav_path: Path, query: AudioQuery) -> str:
    """Forced-align a pure-English accepted WAV with PocketSphinx 5.1.1."""

    adapter_phonemes = english_query_phonemes(query)
    acoustic_phonemes = to_pocketsphinx_phonemes(adapter_phonemes)
    with tempfile.TemporaryDirectory(prefix="voiceger-lab-en-") as temporary:
        alignment_wav = Path(temporary) / "alignment.wav"
        prepared = prepare_alignment_wav(wav_path, alignment_wav)
        alignments = _run_pocketsphinx(alignment_wav, acoustic_phonemes)
        return render_pocketsphinx_lab(
            alignments,
            acoustic_phonemes,
            wav_duration_seconds=prepared.original_duration_seconds,
        )
