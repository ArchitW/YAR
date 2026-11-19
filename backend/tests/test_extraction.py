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
