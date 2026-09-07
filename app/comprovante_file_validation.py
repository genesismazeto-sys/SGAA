"""Compatibility exports for the provider-neutral validated-file primitives."""

from app.file_validation import (
    MAX_DECODED_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    MIME_BY_EXTENSION,
    detect_supported_mime,
)


__all__ = [
    "MAX_DECODED_IMAGE_BYTES",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "MIME_BY_EXTENSION",
    "detect_supported_mime",
]
