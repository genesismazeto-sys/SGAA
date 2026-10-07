"""Content validation and normalization for database-backed images (prod-1/v13).

Nothing here trusts a filename, an extension or a browser Content-Type: the
bytes are decoded with Pillow and only what Pillow proves is stored.

PROFILE PHOTOS (``normalize_profile_photo``)
    Input: PNG or JPEG, at most ``PROFILE_PHOTO_MAX_UPLOAD_BYTES`` (2 MiB) from
    a browser.  The image is decoded completely (decompression-bomb guarded),
    rotated upright from its EXIF orientation, reduced to at most
    ``PROFILE_PHOTO_MAX_EDGE`` (512) px on its longest side and RE-ENCODED, so
    no EXIF, GPS, ICC, text chunk or trailing byte of the upload survives.
    Output format is deterministic:

    * the image really uses transparency (some alpha < 255) -> PNG (RGBA), as
      long as that PNG fits the stored cap;
    * otherwise -> baseline JPEG, quality 85, RGB (transparent pixels, if a
      PNG could not fit, are flattened onto white).

    The stored result is at most ``PROFILE_PHOTO_MAX_STORED_BYTES`` (1 MiB).

REPORT SCREENSHOTS (``validate_report_screenshot``)
    Input: PNG, JPEG or WEBP, at most ``REPORT_SCREENSHOT_MAX_BYTES`` (4 MiB).
    The structure is verified and the pixels decoded completely (truncation and
    bombs refused); a still image is required.  The original bytes are kept --
    a bug report needs the screenshot exactly as it was taken -- and are later
    served only with their verified type and ``nosniff``.

Every refusal is an :class:`ImageRejected` carrying a fixed ``code``; it
never includes the image bytes or the uploaded filename.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps

from app.prod1_images_ddl import (
    PROFILE_PHOTO_MAX_EDGE,
    PROFILE_PHOTO_MAX_STORED_BYTES,
    REPORT_SCREENSHOT_MAX_BYTES,
    REPORT_SCREENSHOT_MAX_EDGE,
)


PROFILE_PHOTO_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
PROFILE_PHOTO_JPEG_QUALITY = 85
#: A 24-megapixel camera photo still decodes; larger inputs are refused
#: before their pixels are allocated.
PROFILE_PHOTO_MAX_SOURCE_PIXELS = 25_000_000
#: A tall full-page capture (e.g. 1920 x 20000) still decodes.
REPORT_SCREENSHOT_MAX_PIXELS = 40_000_000
MAX_SOURCE_EDGE = 20_000

_PROFILE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
_SCREENSHOT_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
)


class ImageRejected(ValueError):
    """The upload is not an acceptable image; ``code`` says why (value-free)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ImageTooLarge(ImageRejected):
    """The upload exceeds the byte limit of its category."""

    def __init__(self) -> None:
        super().__init__("TOO_LARGE")


@dataclass(frozen=True)
class StoredImage:
    """Verified image content plus the metadata it is stored and served with."""

    mime_type: str
    width: int
    height: int
    content: bytes
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)

    @property
    def version(self) -> str:
        """Short, stable cache marker (never a path)."""
        return self.sha256[:16]


def _stored(mime_type: str, width: int, height: int, content: bytes) -> StoredImage:
    return StoredImage(mime_type, int(width), int(height), content, hashlib.sha256(content).hexdigest())


def read_upload_limited(file_storage, limit: int) -> bytes:
    """Read at most ``limit`` bytes of an upload; refuse anything longer or empty."""
    stream = getattr(file_storage, "stream", file_storage)
    content = stream.read(limit + 1)
    if len(content) > limit:
        raise ImageTooLarge()
    if not content:
        raise ImageRejected("EMPTY")
    return content


def _signature_format(content: bytes) -> str | None:
    for signature, name in _SIGNATURES:
        if content.startswith(signature):
            return name
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "WEBP"
    return None


def _open_verified(content: bytes, formats: dict[str, str], max_pixels: int) -> Image.Image:
    """Return a fully decoded image whose real format is one of ``formats``.

    Order matters: the signature and the header geometry are checked before
    any pixel is allocated, ``verify`` walks the container structure, and a
    second open decodes every pixel (``load``) so truncation is refused too.
    """
    claimed = _signature_format(content)
    if claimed not in formats:
        raise ImageRejected("UNSUPPORTED_FORMAT")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content), formats=[claimed]) as probe:
                _check_geometry(probe, claimed, max_pixels)
                probe.verify()
            image = Image.open(BytesIO(content), formats=[claimed])
            try:
                _check_geometry(image, claimed, max_pixels)
                image.load()
            except BaseException:
                image.close()
                raise
    except ImageRejected:
        raise
    except Image.DecompressionBombError as exc:
        raise ImageRejected("TOO_MANY_PIXELS") from exc
    except (OSError, SyntaxError, ValueError, EOFError, Warning, MemoryError) as exc:
        raise ImageRejected("INVALID_IMAGE") from exc
    return image


def _check_geometry(image: Image.Image, claimed: str, max_pixels: int) -> None:
    if image.format != claimed:
        raise ImageRejected("UNSUPPORTED_FORMAT")
    width, height = image.size
    if width <= 0 or height <= 0 or width > MAX_SOURCE_EDGE or height > MAX_SOURCE_EDGE:
        raise ImageRejected("TOO_MANY_PIXELS")
    if width * height > max_pixels:
        raise ImageRejected("TOO_MANY_PIXELS")


def detect_image(content: bytes, *, formats: dict[str, str], max_pixels: int) -> StoredImage:
    """Verify ``content`` and describe it without changing a byte."""
    image = _open_verified(content, formats, max_pixels)
    try:
        if getattr(image, "is_animated", False):
            raise ImageRejected("ANIMATED")
        return _stored(formats[image.format], image.width, image.height, content)
    finally:
        image.close()


def validate_report_screenshot(content: bytes) -> StoredImage:
    """A still PNG/JPEG/WEBP screenshot, stored as uploaded."""
    if len(content) > REPORT_SCREENSHOT_MAX_BYTES:
        raise ImageTooLarge()
    if not content:
        raise ImageRejected("EMPTY")
    stored = detect_image(content, formats=_SCREENSHOT_FORMATS, max_pixels=REPORT_SCREENSHOT_MAX_PIXELS)
    if stored.width > REPORT_SCREENSHOT_MAX_EDGE or stored.height > REPORT_SCREENSHOT_MAX_EDGE:
        raise ImageRejected("TOO_MANY_PIXELS")
    return stored


def _uses_alpha(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA"):
        return False
    low, _high = image.getchannel("A").getextrema()
    return low < 255


def _encode(image: Image.Image, fmt: str) -> bytes:
    buffer = BytesIO()
    if fmt == "PNG":
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.save(
            buffer, format="JPEG", quality=PROFILE_PHOTO_JPEG_QUALITY,
            optimize=True, progressive=False,
        )
    return buffer.getvalue()


def normalize_profile_photo(content: bytes, *, max_input_bytes: int = PROFILE_PHOTO_MAX_UPLOAD_BYTES) -> StoredImage:
    """Decode, orient, shrink to <= 512 px and re-encode a profile photo.

    ``max_input_bytes`` exists for the legacy importer, whose source files were
    accepted under the former 16 MiB request limit; the stored result obeys
    the same 1 MiB / 512 px contract either way.
    """
    if len(content) > max_input_bytes:
        raise ImageTooLarge()
    if not content:
        raise ImageRejected("EMPTY")
    source = _open_verified(content, _PROFILE_FORMATS, PROFILE_PHOTO_MAX_SOURCE_PIXELS)
    try:
        upright = ImageOps.exif_transpose(source)
        has_transparency = upright.mode in ("RGBA", "LA", "PA") or (
            upright.mode == "P" and "transparency" in upright.info
        )
        working = upright.convert("RGBA" if has_transparency else "RGB")
        working.thumbnail((PROFILE_PHOTO_MAX_EDGE, PROFILE_PHOTO_MAX_EDGE), Image.Resampling.LANCZOS)
        # A fresh image carries pixels only: no EXIF, ICC, text or palette info.
        clean = Image.new(working.mode, working.size)
        clean.paste(working)
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        raise ImageRejected("INVALID_IMAGE") from exc
    finally:
        source.close()

    if _uses_alpha(clean):
        encoded = _encode(clean, "PNG")
        if len(encoded) <= PROFILE_PHOTO_MAX_STORED_BYTES:
            return _stored("image/png", clean.width, clean.height, encoded)
        flattened = Image.new("RGB", clean.size, (255, 255, 255))
        flattened.paste(clean, mask=clean.getchannel("A"))
        clean = flattened
    elif clean.mode != "RGB":
        clean = clean.convert("RGB")
    encoded = _encode(clean, "JPEG")
    if len(encoded) > PROFILE_PHOTO_MAX_STORED_BYTES:  # pragma: no cover - 512 px JPEG q85 cannot reach 1 MiB
        raise ImageRejected("TOO_LARGE_AFTER_NORMALIZATION")
    return _stored("image/jpeg", clean.width, clean.height, encoded)


PROFILE_LEGACY_FORMATS = _PROFILE_FORMATS
SCREENSHOT_FORMATS = _SCREENSHOT_FORMATS


__all__ = [
    "ImageRejected",
    "ImageTooLarge",
    "MAX_SOURCE_EDGE",
    "PROFILE_LEGACY_FORMATS",
    "PROFILE_PHOTO_JPEG_QUALITY",
    "PROFILE_PHOTO_MAX_EDGE",
    "PROFILE_PHOTO_MAX_SOURCE_PIXELS",
    "PROFILE_PHOTO_MAX_STORED_BYTES",
    "PROFILE_PHOTO_MAX_UPLOAD_BYTES",
    "REPORT_SCREENSHOT_MAX_BYTES",
    "REPORT_SCREENSHOT_MAX_PIXELS",
    "SCREENSHOT_FORMATS",
    "StoredImage",
    "detect_image",
    "normalize_profile_photo",
    "read_upload_limited",
    "validate_report_screenshot",
]
