from __future__ import annotations

import warnings
from io import BytesIO

from PIL import Image
from pypdf import PdfReader


MIME_BY_EXTENSION = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

MAX_IMAGE_PIXELS = 8_000_000
MAX_IMAGE_DIMENSION = 20_000
MAX_DECODED_IMAGE_BYTES = 64 * 1024 * 1024


def _image_within_limits(image: Image.Image) -> bool:
    width, height = image.size
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
    ):
        return False
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        return False
    # Two bytes per band is conservative for accepted 8/16-bit image modes.
    decoded_bytes = pixels * max(1, len(image.getbands())) * 2
    return decoded_bytes <= MAX_DECODED_IMAGE_BYTES


def _valid_image(content: bytes, *, signature: bytes, expected_format: str) -> bool:
    if not content.startswith(signature):
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format or not _image_within_limits(image):
                    return False
                image.verify()
            with Image.open(BytesIO(content)) as image:
                if image.format != expected_format or not _image_within_limits(image):
                    return False
                image.load()
                return True
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError, Warning):
        return False


def _valid_pdf(content: bytes) -> bool:
    if not content.startswith(b"%PDF-"):
        return False
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            return False
        root = reader.trailer.get("/Root")
        if root is None:
            return False
        catalog = root.get_object()
        if catalog.get("/Type") != "/Catalog":
            return False
        pages_root = catalog.get("/Pages")
        if pages_root is None or pages_root.get_object().get("/Type") != "/Pages":
            return False
        if len(reader.pages) < 1:
            return False
        page = reader.pages[0]
        if page.get("/Type") != "/Page":
            return False
        _ = page.mediabox
        return True
    except Exception:
        # Uploaded parser failures are validation failures, not request errors.
        return False


def detect_supported_mime(content: bytes) -> str | None:
    if _valid_pdf(content):
        return "application/pdf"
    if _valid_image(
        content, signature=b"\x89PNG\r\n\x1a\n", expected_format="PNG"
    ):
        return "image/png"
    if _valid_image(content, signature=b"\xff\xd8", expected_format="JPEG"):
        return "image/jpeg"
    return None


__all__ = [
    "MAX_DECODED_IMAGE_BYTES",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_PIXELS",
    "MIME_BY_EXTENSION",
    "detect_supported_mime",
]
