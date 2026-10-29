# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Speech to text with sherpa-onnx (td-mgcw8). Processor only: the thread
count stays small so a transcription never takes the whole machine."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from core.voice_input.catalog import SpeechModel
from core.voice_input.store import model_path

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_seconds: float
    compute_seconds: float


def _threads() -> int:
    return max(1, min(4, (os.cpu_count() or 2) - 1))


class Transcriber:
    """Loads the model once (a few seconds) and reuses it."""

    def __init__(self, model: SpeechModel):
        import sherpa_onnx
        folder = model_path(model)
        started = time.perf_counter()
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(folder / model.encoder),
            decoder=str(folder / model.decoder),
            joiner=str(folder / model.joiner),
            tokens=str(folder / model.tokens),
            num_threads=_threads(),
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            model_type=model.model_type,
        )
        self.load_seconds = time.perf_counter() - started

    def transcribe(self, samples, sample_rate: int = SAMPLE_RATE) -> Transcript:
        """``samples``: 1-D float32 numpy array in [-1, 1], mono."""
        started = time.perf_counter()
        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        self._recognizer.decode_stream(stream)
        return Transcript(
            text=stream.result.text.strip(),
            audio_seconds=len(samples) / float(sample_rate),
            compute_seconds=time.perf_counter() - started,
        )
