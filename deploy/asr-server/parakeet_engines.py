"""Sprint TQ4 T1 — the two ways asr-server runs Parakeet-TDT-0.6B-v3.

* ``nemo`` (default, the HF T4 endpoint): NeMo's own ASRModel restored from the
  baked ``.nemo`` file, fp16 on CUDA. Above ``LOCAL_ATTENTION_AFTER_S`` the
  encoder switches to local attention (``rel_pos_local_attn``, 256/256) and
  chunked subsampling — NVIDIA's documented setting for long audio — so a
  90-minute file fits a T4.
* ``onnx`` (the dev Mac, and the documented fallback if the NeMo image is too
  large for the endpoint build): the ONNX export of the same weights through
  ``onnx-asr`` (MIT), CoreML / CPU execution providers.

Both return :class:`parakeet_format.Word` lists; the server never sees which.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from parakeet_format import Word, words_from_tokens

LOCAL_ATTENTION_AFTER_S = float(os.environ.get("MDX_ASR_LOCAL_ATTENTION_AFTER_S", "1200"))


class Engine(Protocol):
    model_id: str

    def load(self) -> None: ...

    def transcribe(self, pcm: np.ndarray) -> list[Word]: ...


class NemoEngine:
    def __init__(self, model_path: str, device: str = "cuda") -> None:
        self.model_id = "nvidia/parakeet-tdt-0.6b-v3"
        self._path = model_path
        self._device = device
        self._model: Any = None
        self._local = False

    def load(self) -> None:
        import torch
        from nemo.collections.asr.models import ASRModel

        model = ASRModel.restore_from(self._path, map_location=self._device)
        model.eval()
        if self._device == "cuda":
            model = model.half()
        torch.set_grad_enabled(False)
        self._model = model

    def _attention(self, seconds: float) -> None:
        want_local = seconds > LOCAL_ATTENTION_AFTER_S
        if want_local == self._local:
            return
        if want_local:
            self._model.change_attention_model("rel_pos_local_attn", [256, 256])
            self._model.change_subsampling_conv_chunking_factor(1)
        else:
            self._model.change_attention_model("rel_pos")
            self._model.change_subsampling_conv_chunking_factor(-1)
        self._local = want_local

    def transcribe(self, pcm: np.ndarray) -> list[Word]:
        self._attention(len(pcm) / 16_000)
        (hyp,) = self._model.transcribe([pcm], batch_size=1, timestamps=True, verbose=False)
        stamps = (getattr(hyp, "timestamp", None) or {}).get("word") or []
        return [
            Word(str(w["word"]), round(float(w["start"]), 3), round(float(w["end"]), 3), None)
            for w in stamps
            if str(w.get("word", "")).strip()
        ]


class OnnxEngine:
    def __init__(self, model_dir: str | None, quantization: str | None = None) -> None:
        self.model_id = "nvidia/parakeet-tdt-0.6b-v3 (onnx)"
        self._dir = model_dir
        self._quantization = quantization
        self._model: Any = None

    def load(self) -> None:
        import onnx_asr

        if self._dir and Path(self._dir).is_dir():
            base = onnx_asr.load_model(
                "nemo-parakeet-tdt-0.6b-v3", self._dir, quantization=self._quantization
            )
        else:  # dev only: from the hub cache (HF_HUB_OFFLINE stops a fetch)
            base = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization=self._quantization)
        self._model = base.with_timestamps()

    def transcribe(self, pcm: np.ndarray) -> list[Word]:
        result = self._model.recognize(pcm.astype(np.float32), sample_rate=16_000)
        return words_from_tokens(
            list(result.tokens or []),
            list(result.timestamps or []),
            list(result.logprobs) if getattr(result, "logprobs", None) is not None else None,
            duration=len(pcm) / 16_000,
        )


def build(runtime: str) -> Engine:
    if runtime == "nemo":
        return NemoEngine(
            os.environ.get("MDX_ASR_MODEL_PATH", "/opt/models/parakeet/parakeet-tdt-0.6b-v3.nemo"),
            os.environ.get("MDX_ASR_DEVICE", "cuda"),
        )
    if runtime == "onnx":
        return OnnxEngine(
            os.environ.get("MDX_ASR_MODEL_DIR"),
            os.environ.get("MDX_ASR_QUANTIZATION") or None,
        )
    raise RuntimeError(f"MDX_ASR_RUNTIME must be nemo or onnx, not {runtime!r}")
