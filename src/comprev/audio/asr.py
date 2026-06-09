"""ASR behind an interface so the backend can be swapped.

Default implementation is faster-whisper (Hindi/Hinglish capable). Produces
segment-level text with start/end timestamps and a confidence proxy
(``avg_logprob``, with ``no_speech_prob`` surfaced). Segments below the
configured confidence are flagged low-confidence — and any check relying on a
low-confidence segment must not return ``pass``.

The original demuxed audio is kept on disk so a reviewer can spot-check; this
engine never discards evidence.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Optional, Protocol

from ..media import ffmpeg_bin
from ..schemas import Transcript, TranscriptSegment


class AsrEngine(Protocol):
    def transcribe(self, audio_path: Path) -> Transcript: ...


def extract_audio(video_path: Path | str, artifacts_dir: Path | str) -> Path:
    """Demux audio to 16 kHz mono WAV and keep it for audit. Returns its path."""
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    audio_path = artifacts_dir / "audio.wav"
    subprocess.run(
        [
            ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(video_path),
            "-ac", "1", "-ar", "16000", "-vn", str(audio_path),
        ],
        check=True,
    )
    return audio_path


class FasterWhisperEngine:
    def __init__(
        self,
        model: str = "large-v3",
        compute_type: str = "int8",
        language: Optional[str] = None,
        low_confidence_logprob: float = -1.0,
        max_no_speech_prob: float = 0.6,
        cpu_threads: int = 4,
    ):
        self.model_name = model
        self.compute_type = compute_type
        self.language = language
        self.low_confidence_logprob = low_confidence_logprob
        self.max_no_speech_prob = max_no_speech_prob
        self.cpu_threads = cpu_threads
        self._model = None
        self._load_lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from faster_whisper import WhisperModel  # lazy import

                    # device="auto" uses GPU/Metal if present (cpu_threads then
                    # ignored). On CPU, cpu_threads caps native threads so a
                    # concurrent OCR pass doesn't oversubscribe the cores.
                    self._model = WhisperModel(
                        self.model_name,
                        device="auto",
                        compute_type=self.compute_type,
                        cpu_threads=self.cpu_threads,
                        num_workers=1,
                    )
        return self._model

    def transcribe(self, audio_path: Path) -> Transcript:
        model = self._load()
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=self.language,
            vad_filter=True,
            word_timestamps=False,
        )

        segments: list[TranscriptSegment] = []
        for seg in segments_iter:
            avg_logprob = float(getattr(seg, "avg_logprob", 0.0))
            no_speech = float(getattr(seg, "no_speech_prob", 0.0))
            low_conf = (
                avg_logprob < self.low_confidence_logprob
                or no_speech > self.max_no_speech_prob
            )
            segments.append(
                TranscriptSegment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=seg.text.strip(),
                    avg_logprob=avg_logprob,
                    no_speech_prob=no_speech,
                    low_confidence=low_conf,
                )
            )

        return Transcript(
            language=getattr(info, "language", None),
            segments=segments,
            audio_path=str(audio_path),
            model=f"faster-whisper:{self.model_name}",
        )


# Warm cache: the reused worker process keeps the loaded WhisperModel across
# jobs instead of cold-loading large-v3 every run. Keyed by everything that
# changes behaviour (so --fast's `medium` gets its own cached engine).
_ASR_CACHE: dict[tuple, AsrEngine] = {}
_ASR_LOCK = threading.Lock()


def build_asr_engine(backend: str, cfg) -> AsrEngine:
    """cfg is an AudioConfig."""
    if backend != "faster_whisper":
        # PHASE 2: register additional ASR backends here.
        raise ValueError(f"Unknown ASR backend: {backend!r}")

    cpu_threads = getattr(cfg, "cpu_threads", 4)
    key = (
        backend, cfg.model, cfg.compute_type, cfg.language,
        cfg.low_confidence_logprob, cfg.max_no_speech_prob, cpu_threads,
    )
    with _ASR_LOCK:
        engine = _ASR_CACHE.get(key)
        if engine is None:
            engine = FasterWhisperEngine(
                model=cfg.model,
                compute_type=cfg.compute_type,
                language=cfg.language,
                low_confidence_logprob=cfg.low_confidence_logprob,
                max_no_speech_prob=cfg.max_no_speech_prob,
                cpu_threads=cpu_threads,
            )
            _ASR_CACHE[key] = engine
        return engine
