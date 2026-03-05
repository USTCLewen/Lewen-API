"""BGE-M3 dense embedding wrapper with lazy loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

import config

if TYPE_CHECKING:
    from FlagEmbedding import BGEM3FlagModel

_model: "BGEM3FlagModel | None" = None


def _get_model() -> "BGEM3FlagModel":
    """Lazily load BGE-M3 model on first call.

    Returns:
        The loaded BGEM3FlagModel instance.
    """
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel

        print(f"🚀 Loading BGE-M3 from {config.BGE_M3_MODEL_PATH} on GPU {config.GPU_DEVICE_ID} ...")
        _model = BGEM3FlagModel(
            config.BGE_M3_MODEL_PATH,
            use_fp16=True,
            devices=f"cuda:{config.GPU_DEVICE_ID}",
        )
        print("✅ BGE-M3 loaded.")
    return _model


def encode(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """Encode texts into dense vectors using BGE-M3.

    Args:
        texts: List of text strings to encode.
        batch_size: Batch size for encoding.

    Returns:
        numpy array of shape (len(texts), 1024).
    """
    model = _get_model()
    output = model.encode(
        texts,
        batch_size=batch_size,
        max_length=8192,
    )
    return output["dense_vecs"]
