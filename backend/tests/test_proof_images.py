"""Bounded real image parsing tests, no provider or database calls."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.exceptions import DomainError
from app.features.proofs.service import MAX_PROOF_BYTES, validate_image


def image_bytes(format_name="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (4, 4), color="white").save(output, format=format_name)
    return output.getvalue()


@pytest.mark.parametrize("format_name,mime,extension", [("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpg")])
def test_valid_proof_images_are_fully_parsed(format_name, mime, extension):
    assert validate_image(image_bytes(format_name)) == (mime, extension)


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\n<html>fake proof</html>", b"\xff\xd8\xffbroken"])
def test_invalid_or_truncated_images_are_not_proof(data):
    with pytest.raises(DomainError):
        validate_image(data)


def test_oversize_image_input_is_rejected_before_parsing():
    with pytest.raises(DomainError, match="at most 5 MiB"):
        validate_image(b"x" * (MAX_PROOF_BYTES + 1))


def test_unsupported_image_format_is_rejected():
    with pytest.raises(DomainError):
        validate_image(image_bytes("GIF"))


def test_corrupt_png_checksum_is_an_invalid_proof_not_a_server_error():
    data = bytearray(image_bytes())
    chunk = data.index(b"IDAT")
    length = int.from_bytes(data[chunk - 4:chunk], "big")
    data[chunk + 4 + length] ^= 1
    with pytest.raises(DomainError, match="Proof image is invalid"):
        validate_image(bytes(data))
