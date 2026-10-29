# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Speech models the app can install (td-mgcw8). One entry today: NVIDIA
Parakeet TDT 0.6B v3, int8 build published by the sherpa-onnx project. It
covers 25 European languages (French and English included), finds the
language by itself and runs on an ordinary processor."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class SpeechModel:
    model_id: str          # folder name in the model store
    label: str             # shown in Settings
    url: str               # .tar.bz2 archive
    archive_bytes: int     # exact size of the archive, checked after download
    archive_root: str      # top folder inside the archive
    model_type: str        # sherpa-onnx OfflineRecognizer model_type
    encoder: str
    decoder: str
    joiner: str
    tokens: str
    languages: str         # shown in Settings

    @property
    def required_files(self) -> Tuple[str, ...]:
        return (self.encoder, self.decoder, self.joiner, self.tokens)


PARAKEET_V3 = SpeechModel(
    model_id="parakeet-tdt-0.6b-v3-int8",
    label="Parakeet TDT 0.6B v3 (NVIDIA)",
    url=("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
         "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"),
    archive_bytes=487_170_055,
    archive_root="sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
    model_type="nemo_transducer",
    encoder="encoder.int8.onnx",
    decoder="decoder.int8.onnx",
    joiner="joiner.int8.onnx",
    tokens="tokens.txt",
    languages=("25 European languages, found automatically: English, French, "
               "German, Spanish, Italian, Portuguese, Dutch, Polish, Russian, "
               "Ukrainian and more"),
)

MODELS = (PARAKEET_V3,)
DEFAULT_MODEL = PARAKEET_V3


def get_model(model_id: str) -> SpeechModel:
    for model in MODELS:
        if model.model_id == model_id:
            return model
    raise KeyError(model_id)
