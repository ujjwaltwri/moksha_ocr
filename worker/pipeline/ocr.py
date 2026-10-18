"""OCR engine: RapidOCR (PaddleOCR's PP-OCR models as ONNX, bundled in the pip package, CPU)."""

import threading

import numpy as np

from .types import OcrLine

_engine = None
_lock = threading.Lock()


def _get():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def read(bgr: np.ndarray) -> list[OcrLine]:
    with _lock:  # one OCR at a time per process; scale out with more worker processes
        result, _ = _get()(bgr)
    lines = []
    for box, text, conf in result or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append(OcrLine(text=text, conf=float(conf), box=(min(xs), min(ys), max(xs), max(ys))))
    return sorted(lines, key=lambda l: (l.box[1], l.box[0]))
