# coding: utf-8
"""STORAGE S1: content validation and normalization of database-backed images.

Nothing trusts a filename, an extension or a browser Content-Type: the bytes
are decoded by Pillow.  Profile photos are decoded, oriented, shrunk to at
most 512 px and re-encoded (metadata gone; JPEG unless real transparency);
report screenshots are verified PNG/JPEG/WEBP stills stored as uploaded.
Every limit is exercised at its boundary, and the result always fits the
v13 schema constraints.
"""
from __future__ import annotations

import io
import sqlite3

import pytest
from PIL import Image, PngImagePlugin

from app.image_validation import (
    MAX_SOURCE_EDGE,
    PROFILE_PHOTO_MAX_EDGE,
    PROFILE_PHOTO_MAX_STORED_BYTES,
    PROFILE_PHOTO_MAX_UPLOAD_BYTES,
    REPORT_SCREENSHOT_MAX_BYTES,
    ImageRejected,
    ImageTooLarge,
    normalize_profile_photo,
    read_upload_limited,
    validate_report_screenshot,
)
from app.prod1_schema import PROD1_SCHEMA_SQL


def _encode(image, fmt, **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def _jpeg(size=(800, 600), *, exif=None) -> bytes:
    image = Image.effect_noise(size, 40).convert("RGB")
    return _encode(image, "JPEG", quality=90, **({"exif": exif} if exif is not None else {}))


def _png(size=(300, 200), mode="RGB", color=(10, 120, 200)) -> bytes:
    return _encode(Image.new(mode, size, color), "PNG")


def _decoded(content: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(content))
    image.load()
    return image


def _reject(code, func, *args, **kwargs):
    with pytest.raises(ImageRejected) as caught:
        func(*args, **kwargs)
    assert caught.value.code == code
    assert str(caught.value) == code  # never a filename or a byte
    return caught.value


# --- profile photos ---------------------------------------------------------------


def test_valid_jpeg_profile_photo_is_reencoded_as_baseline_jpeg():
    stored = normalize_profile_photo(_jpeg((640, 480)))
    assert stored.mime_type == "image/jpeg"
    assert (stored.width, stored.height) == (512, 384)
    image = _decoded(stored.content)
    assert image.format == "JPEG" and image.size == (512, 384) and image.mode == "RGB"
    assert stored.size_bytes == len(stored.content) <= PROFILE_PHOTO_MAX_STORED_BYTES
    assert len(stored.sha256) == 64 and stored.version == stored.sha256[:16]


def test_profile_photo_exif_orientation_is_applied_and_metadata_stripped():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    exif[0x010F] = "CameraMaker"
    exif[0x8825] = {2: (1.0, 2.0, 3.0)}  # GPSInfo
    source = _jpeg((600, 300), exif=exif)
    assert _decoded(source).getexif()  # the upload carries EXIF
    stored = normalize_profile_photo(source)
    assert (stored.width, stored.height) == (256, 512)  # upright, then shrunk
    image = _decoded(stored.content)
    assert not image.getexif()
    assert "exif" not in image.info and "icc_profile" not in image.info
    assert b"CameraMaker" not in stored.content


def test_profile_photo_png_text_and_icc_are_dropped():
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "SECRET-AUTHOR")
    source = _encode(Image.new("RGB", (64, 64), (1, 2, 3)), "PNG", pnginfo=info, icc_profile=b"fake-icc")
    stored = normalize_profile_photo(source)
    assert b"SECRET-AUTHOR" not in stored.content and b"fake-icc" not in stored.content
    assert stored.mime_type == "image/jpeg"  # opaque -> JPEG


def test_profile_photo_is_resized_to_at_most_512_on_the_longest_side():
    stored = normalize_profile_photo(_png((2000, 1000)))
    assert (stored.width, stored.height) == (512, 256)
    small = normalize_profile_photo(_png((100, 40)))
    assert (small.width, small.height) == (100, 40)  # never upscaled
    tall = normalize_profile_photo(_png((513, 4000)))
    assert max(tall.width, tall.height) == PROFILE_PHOTO_MAX_EDGE


def test_transparency_policy_png_only_when_alpha_is_really_used():
    translucent = normalize_profile_photo(_png((100, 100), "RGBA", (10, 20, 30, 128)))
    assert translucent.mime_type == "image/png"
    assert _decoded(translucent.content).mode == "RGBA"
    opaque_rgba = normalize_profile_photo(_png((100, 100), "RGBA", (10, 20, 30, 255)))
    assert opaque_rgba.mime_type == "image/jpeg"
    palette = Image.new("P", (50, 50), 0)
    palette.putpalette([255, 0, 0, 0, 0, 255])
    palette.paste(1, (0, 0, 25, 50))  # left half uses the transparent index
    assert normalize_profile_photo(_encode(palette, "PNG", transparency=1)).mime_type == "image/png"


def test_profile_normalization_is_deterministic():
    source = _png((700, 500), "RGBA", (9, 8, 7, 100))
    assert normalize_profile_photo(source) == normalize_profile_photo(source)
    jpeg = _jpeg((900, 700))
    assert normalize_profile_photo(jpeg).sha256 == normalize_profile_photo(jpeg).sha256


def test_worst_case_noise_still_fits_the_stored_cap():
    noise = Image.effect_noise((2048, 2048), 128)
    rgba = Image.merge("RGBA", [noise, noise.rotate(90), noise.rotate(180), noise.rotate(270)])
    stored = normalize_profile_photo(_encode(rgba, "PNG"), max_input_bytes=64 * 1024 * 1024)
    assert stored.size_bytes <= PROFILE_PHOTO_MAX_STORED_BYTES
    opaque = normalize_profile_photo(_encode(noise.convert("RGB"), "PNG"), max_input_bytes=64 * 1024 * 1024)
    assert opaque.mime_type == "image/jpeg" and opaque.size_bytes <= PROFILE_PHOTO_MAX_STORED_BYTES


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"just some text pretending to be foto.png", "UNSUPPORTED_FORMAT"),
        (b"GIF89a" + b"\x00" * 64, "UNSUPPORTED_FORMAT"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "UNSUPPORTED_FORMAT"),
        (b"\x89PNG\r\n\x1a\n" + b"not really a png", "INVALID_IMAGE"),
        (b"\xff\xd8\xff" + b"not really a jpeg", "INVALID_IMAGE"),
    ],
)
def test_profile_extension_and_content_type_spoofs_are_refused(content, code):
    _reject(code, normalize_profile_photo, content)


def test_webp_is_not_a_profile_photo_format():
    _reject("UNSUPPORTED_FORMAT", normalize_profile_photo, _encode(Image.new("RGB", (20, 20)), "WEBP"))


@pytest.mark.parametrize("cut", [30, 200])
def test_truncated_profile_images_are_refused(cut):
    png = _png((400, 400))
    _reject("INVALID_IMAGE", normalize_profile_photo, png[:-cut])
    jpeg = _jpeg((400, 400))
    _reject("INVALID_IMAGE", normalize_profile_photo, jpeg[: len(jpeg) // 2])


def test_decompression_bombs_are_refused_before_decoding():
    bomb = _encode(Image.new("1", (19_000, 19_000)), "PNG")
    assert len(bomb) < PROFILE_PHOTO_MAX_UPLOAD_BYTES  # tiny on the wire
    _reject("TOO_MANY_PIXELS", normalize_profile_photo, bomb)
    _reject("TOO_MANY_PIXELS", validate_report_screenshot, bomb)
    wide = _encode(Image.new("1", (MAX_SOURCE_EDGE + 1, 1)), "PNG")
    _reject("TOO_MANY_PIXELS", validate_report_screenshot, wide)


def test_profile_upload_size_limit_is_exact():
    limit = PROFILE_PHOTO_MAX_UPLOAD_BYTES
    assert limit == 2 * 1024 * 1024
    assert read_upload_limited(io.BytesIO(b"x" * limit), limit) == b"x" * limit
    with pytest.raises(ImageTooLarge):
        read_upload_limited(io.BytesIO(b"x" * (limit + 1)), limit)
    with pytest.raises(ImageTooLarge):
        normalize_profile_photo(b"\x89PNG\r\n\x1a\n" + b"\x00" * limit)
    _reject("EMPTY", read_upload_limited, io.BytesIO(b""), limit)


# --- report screenshots ------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "mime"),
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")],
)
def test_valid_screenshots_are_kept_byte_for_byte(fmt, mime):
    content = _encode(Image.new("RGB", (1280, 720), (40, 50, 60)), fmt)
    stored = validate_report_screenshot(content)
    assert stored.mime_type == mime
    assert stored.content == content
    assert (stored.width, stored.height) == (1280, 720)


def test_tall_full_page_screenshot_is_accepted():
    content = _encode(Image.new("RGB", (1920, 18_000), (255, 255, 255)), "PNG")
    assert validate_report_screenshot(content).height == 18_000


def test_animated_screenshots_are_refused():
    frames = [Image.new("RGB", (40, 40), color) for color in ((255, 0, 0), (0, 255, 0))]
    buffer = io.BytesIO()
    frames[0].save(buffer, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    _reject("ANIMATED", validate_report_screenshot, buffer.getvalue())


def test_screenshot_spoofs_and_truncation_are_refused():
    _reject("UNSUPPORTED_FORMAT", validate_report_screenshot, b"GIF89a" + b"\x00" * 40)
    _reject("UNSUPPORTED_FORMAT", validate_report_screenshot, b"%PDF-1.4 not an image")
    _reject("INVALID_IMAGE", validate_report_screenshot, b"\x89PNG\r\n\x1a\nadmin")
    webp = _encode(Image.new("RGB", (300, 300), (1, 2, 3)), "WEBP")
    _reject("INVALID_IMAGE", validate_report_screenshot, webp[: len(webp) // 2])
    _reject("EMPTY", validate_report_screenshot, b"")


def test_screenshot_size_limit_is_exact():
    assert REPORT_SCREENSHOT_MAX_BYTES == 4 * 1024 * 1024
    with pytest.raises(ImageTooLarge):
        validate_report_screenshot(b"\x89PNG\r\n\x1a\n" + b"\x00" * REPORT_SCREENSHOT_MAX_BYTES)
    with pytest.raises(ImageTooLarge):
        read_upload_limited(io.BytesIO(b"x" * (REPORT_SCREENSHOT_MAX_BYTES + 1)), REPORT_SCREENSHOT_MAX_BYTES)


def test_screenshot_limit_leaves_room_below_the_vercel_request_cap():
    """The complete aluno report form with a maximal screenshot stays below 4.5 MB."""
    from werkzeug.test import EnvironBuilder

    builder = EnvironBuilder(
        method="POST",
        data={
            "csrf_token": "t" * 120,
            "categoria": "Dificuldade de uso",
            "titulo": "ã" * 120,
            "descricao": "ç" * 10_000,
            "captura_tela": (
                io.BytesIO(b"x" * REPORT_SCREENSHOT_MAX_BYTES),
                "Captura de tela 2026-10-07 às 14.32.55 (versão final).png",
                "image/png",
            ),
        },
    )
    length = int(builder.get_environ()["CONTENT_LENGTH"])
    assert length - REPORT_SCREENSHOT_MAX_BYTES < 32 * 1024
    assert 4_500_000 - length > 250_000


# --- the results always fit the schema ------------------------------------------------


def test_validator_outputs_satisfy_the_v13_sqlite_constraints():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(PROD1_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO usuarios(id,nome,email,senha,tipo,nivel_acesso) VALUES(1,'A','a@x.test','x','admin','admin_total')"
    )
    conn.execute("INSERT INTO alunos(id,usuario_id,nome,matricula) VALUES(1,1,'B','M1')")
    conn.execute("INSERT INTO reportes(id,aluno_id,titulo,descricao) VALUES(1,1,'t','d')")
    photo = normalize_profile_photo(_png((900, 900), "RGBA", (1, 2, 3, 90)))
    shot = validate_report_screenshot(_encode(Image.new("RGB", (64, 64)), "WEBP"))
    for table, column, image in (
        ("usuarios_foto", "usuario_id", photo),
        ("alunos_foto", "aluno_id", photo),
        ("reportes_captura", "reporte_id", shot),
    ):
        conn.execute(
            f"INSERT INTO {table}({column},mime_type,size_bytes,sha256,width,height,conteudo)"
            " VALUES(1,?,?,?,?,?,?)",
            (image.mime_type, image.size_bytes, image.sha256, image.width, image.height, image.content),
        )
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
