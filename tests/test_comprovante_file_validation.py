from __future__ import annotations

import struct
import zlib
from io import BytesIO

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

import app.comprovante_file_validation as file_validation
from app.comprovantes import ComprovanteError, prepare_comprovante_batch
from tests.test_comprovantes_google_drive import JPEG, PDF, PNG, _png_chunk


INTERLACED_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 1))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    + _png_chunk(b"IEND", b"")
)
MALFORMED_ADAM7_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 1))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00"))
    + _png_chunk(b"IEND", b"")
)


def _amplification_png(width: int, height: int) -> bytes:
    row = b"\x00" + b"\x00" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        )
        + _png_chunk(b"IDAT", zlib.compress(row * height))
        + _png_chunk(b"IEND", b"")
    )


AMPLIFICATION_PNG = _amplification_png(1, 5_000_000)
REVERSE_AMPLIFICATION_PNG = _amplification_png(5_000_000, 1)
PORTRAIT_DOCUMENT_PNG = _amplification_png(1_200, 1_600)
LANDSCAPE_DOCUMENT_PNG = _amplification_png(1_600, 1_200)
NARROW_VALID_PNG = _amplification_png(1, file_validation.MAX_IMAGE_DIMENSION)
CATALOGLESS_PDF = PDF.replace(
    b"/Type /Catalog /Pages 2 0 R", b"/Type /Pages   /Pages 2 0 R"
)


def _file(content: bytes, filename: str) -> FileStorage:
    return FileStorage(stream=BytesIO(content), filename=filename)


@pytest.mark.parametrize(
    ("content", "filename", "mime"),
    [
        (PDF, "valid.pdf", "application/pdf"),
        (PNG, "normal.png", "image/png"),
        (INTERLACED_PNG, "interlaced.png", "image/png"),
        (PORTRAIT_DOCUMENT_PNG, "portrait.png", "image/png"),
        (LANDSCAPE_DOCUMENT_PNG, "landscape.png", "image/png"),
        (NARROW_VALID_PNG, "narrow.png", "image/png"),
        (JPEG, "valid.jpg", "image/jpeg"),
    ],
)
def test_decoder_accepts_valid_supported_files(content, filename, mime):
    item = prepare_comprovante_batch([_file(content, filename)], batch_key="valid")
    assert item[0].mime_type == mime


@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (MALFORMED_ADAM7_PNG, "adam7.png"),
        (CATALOGLESS_PDF, "catalogless.pdf"),
        (b"%PDF-1.4\n%%EOF", "marker.pdf"),
        (b"\x89PNG\r\n\x1a\n", "marker.png"),
        (b"\xff\xd8\xff\xd9", "marker.jpg"),
        (PDF[:-8], "truncated.pdf"),
        (PNG[:-6], "truncated.png"),
        (JPEG[:-2], "truncated.jpg"),
    ],
)
def test_decoder_rejects_malformed_supported_files(content, filename):
    with pytest.raises(ComprovanteError) as captured:
        prepare_comprovante_batch([_file(content, filename)], batch_key="invalid")
    assert captured.value.code == "MALFORMED_FILE"


@pytest.mark.parametrize(
    ("content", "dimensions"),
    [
        (AMPLIFICATION_PNG, (1, 5_000_000)),
        (REVERSE_AMPLIFICATION_PNG, (5_000_000, 1)),
    ],
    ids=["height", "width"],
)
def test_png_pathological_dimension_is_rejected_before_pixel_decode(
    monkeypatch, content, dimensions
):
    decode_calls = []
    monkeypatch.setattr(
        Image.Image,
        "load",
        lambda self, *args, **kwargs: decode_calls.append(self.size),
    )
    prepared = []
    with pytest.raises(ComprovanteError) as captured:
        prepared.extend(
            prepare_comprovante_batch(
                [_file(content, "amplification.png")],
                batch_key="amplification",
            )
        )
    assert captured.value.code == "MALFORMED_FILE"
    assert prepared == []
    assert decode_calls == []
    assert dimensions[0] * dimensions[1] < file_validation.MAX_IMAGE_PIXELS
    assert max(dimensions) > file_validation.MAX_IMAGE_DIMENSION


def test_exact_prior_amplification_fixture_has_reported_shape_and_scale():
    with Image.open(BytesIO(AMPLIFICATION_PNG)) as image:
        assert image.size == (1, 5_000_000)
    assert 9_000 < len(AMPLIFICATION_PNG) < 11_000
    assert 9_000_000 < 2 * 5_000_000 < 11_000_000
