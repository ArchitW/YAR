"""Tests for backend.app.services.extraction."""

import csv
import os
import tempfile

import pytest

from app.services.extraction import extract_text, is_supported


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp(tmp_path):
    """Return a helper that writes a temp file and returns its path."""

    def _write(name: str, content: bytes | str, mode: str = "w") -> str:
        p = tmp_path / name
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        return str(p)

    return _write


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------


class TestTxt:
    def test_plain_text(self, tmp):
        path = tmp("hello.txt", "Hello, world!")
        assert extract_text(path) == "Hello, world!"

    def test_content_type_fallback(self, tmp):
        path = tmp("data.bin", "some text")
        assert extract_text(path, "text/plain") == "some text"


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


class TestCsv:
    def test_basic_csv(self, tmp):
        path = tmp("data.csv", "name,age\nAlice,30\nBob,25\n")
        result = extract_text(path)
        assert "Alice" in result
        assert "Bob" in result
        assert "name" in result

    def test_empty_csv(self, tmp):
        path = tmp("empty.csv", "")
        assert extract_text(path) == ""


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


class TestMarkdown:
    def test_md_preserved(self, tmp):
        md = "# Title\n\nSome **bold** text."
        path = tmp("readme.md", md)
        assert extract_text(path) == md


# ---------------------------------------------------------------------------
# Unsupported
# ---------------------------------------------------------------------------


class TestUnsupported:
    def test_unknown_extension_returns_empty(self, tmp):
        path = tmp("file.xyz", "binary stuff")
        assert extract_text(path) == ""

    def test_is_supported_true(self, tmp):
        path = tmp("doc.pdf", b"%PDF-1.4")
        assert is_supported(path) is True

    def test_is_supported_false(self, tmp):
        path = tmp("file.xyz", "nope")
        assert is_supported(path) is False

    def test_is_supported_content_type(self, tmp):
        path = tmp("file.xyz", "nope")
        assert is_supported(path, "text/plain") is True

    def test_is_supported_image(self, tmp):
        path = tmp("receipt.png", b"fake-png-bytes")
        assert is_supported(path) is True
        assert is_supported("random.bin", "image/png") is True


class TestCleaning:
    def test_clean_text_normalizes_unicode_and_hyphenation(self):
        from app.services.cleaning import clean_text

        raw = "This is a demon-\nstration of the clean-\ning pipeline.\x00\r\n\n\nNew paragraph."
        cleaned = clean_text(raw)
        assert "demonstration" in cleaned
        assert "cleaning" in cleaned
        assert "\x00" not in cleaned
        assert "\r" not in cleaned
        assert "\n\n\n" not in cleaned

    def test_clean_text_empty(self):
        from app.services.cleaning import clean_text

        assert clean_text("") == ""


class TestOcr:
    def test_ocr_extracts_text_from_image(self, tmp_path):
        from PIL import Image, ImageDraw
        from app.services.ocr import ocr_image

        img_path = str(tmp_path / "test_ocr.png")
        img = Image.new("RGB", (250, 80), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 30), "ORDER 12345", fill=(0, 0, 0))
        img.save(img_path)

        extracted = ocr_image(img_path)
        assert "ORDER" in extracted or "12345" in extracted

    def test_extract_text_supports_png(self, tmp_path):
        from PIL import Image, ImageDraw

        img_path = str(tmp_path / "invoice.png")
        img = Image.new("RGB", (250, 80), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 30), "PAID IN FULL", fill=(0, 0, 0))
        img.save(img_path)

        text = extract_text(img_path)
        assert "PAID" in text or "FULL" in text


# ---------------------------------------------------------------------------
# PDF (requires pypdf — test only if available)
# ---------------------------------------------------------------------------


class TestPdf:
    @pytest.fixture(autouse=True)
    def _skip_without_pypdf(self):
        pytest.importorskip("pypdf")

    def test_pdf_no_text_raises(self, tmp):
        # Minimal valid PDF with no text content
        path = tmp("empty.pdf", b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\nxref\n0 3\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \ntrailer<</Root 1 0 R/Size 3>>\nstartxref\n101\n%%EOF")
        with pytest.raises(ValueError, match="No text extracted"):
            extract_text(path)
