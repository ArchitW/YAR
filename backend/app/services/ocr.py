"""OCR processing service using RapidOCR (ONNX-accelerated).

Handles standalone image files and embedded image extraction from scanned documents.
"""

import io
import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)
_engine = None


def get_ocr_engine():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        except Exception as exc:
            logger.error("Failed to initialize RapidOCR engine: %s", exc)
            _engine = None
    return _engine


def ocr_image(image_path: str, min_confidence: float = 0.3) -> str:
    """Extract text from an image file on disk.

    Supports PNG, JPG, JPEG, TIFF, WEBP, and BMP formats.
    """
    engine = get_ocr_engine()
    if engine is None:
        logger.warning("OCR engine not available; returning empty string")
        return ""

    try:
        result, _ = engine(image_path)
        if not result:
            return ""

        extracted_lines = [
            line[1].strip()
            for line in result
            if len(line) >= 3 and line[2] >= min_confidence and line[1].strip()
        ]
        return "\n".join(extracted_lines)
    except Exception as exc:
        logger.warning("OCR extraction failed on %s: %s", image_path, exc)
        return ""


def ocr_image_bytes(image_bytes: bytes, min_confidence: float = 0.3) -> str:
    """Extract text from in-memory image bytes (e.g., extracted PDF embedded pages/images)."""
    if not image_bytes:
        return ""

    engine = get_ocr_engine()
    if engine is None:
        return ""

    try:
        result, _ = engine(image_bytes)
        if not result:
            return ""

        extracted_lines = [
            line[1].strip()
            for line in result
            if len(line) >= 3 and line[2] >= min_confidence and line[1].strip()
        ]
        return "\n".join(extracted_lines)
    except Exception as exc:
        logger.warning("OCR on image bytes failed: %s", exc)
        return ""
