"""Multi-format text extraction and cleaning pipeline.

Supports:
- Documents: TXT, Markdown, PDF, CSV, XLSX, EPUB
- Scanned documents / Images via OCR: PNG, JPG, JPEG, WEBP, TIFF, BMP
- Auto-cleaning: NFKC normalization, hyphenation repair, whitespace collapse
"""

import csv
import io
import logging
from pathlib import Path
from typing import Optional

from .cleaning import clean_text
from .ocr import ocr_image, ocr_image_bytes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------


def extract_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def extract_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages: list[str] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        # If no digital text layer is found, attempt OCR on embedded page images (scanned PDF)
        if not text.strip() and hasattr(page, "images"):
            ocr_fragments = []
            for img in page.images:
                ocr_out = ocr_image_bytes(img.data)
                if ocr_out.strip():
                    ocr_fragments.append(ocr_out)
            if ocr_fragments:
                text = "\n".join(ocr_fragments)

        if text.strip():
            pages.append(f"[Page {i + 1}]\n{text}")

    if not pages:
        raise ValueError(f"No text extracted from PDF: {path}")
    return "\n\n".join(pages)


def extract_csv(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return ""
    # Render as a readable table: header row + data rows
    header = rows[0]
    lines = [", ".join(header)]
    for row in rows[1:]:
        lines.append(", ".join(row))
    return "\n".join(lines)


def extract_xlsx(path: str) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    sheets: list[str] = []
    for ws in wb.worksheets:
        rows: list[str] = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append(", ".join(cells))
        if rows:
            sheets.append(f"[Sheet: {ws.title}]\n" + "\n".join(rows))
    wb.close()
    if not sheets:
        return ""
    return "\n\n".join(sheets)


def extract_epub(path: str) -> str:
    import re
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(path, options={"ignore_ncx": True})
    sections: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        html = item.get_body_content().decode("utf-8", errors="ignore")
        # Strip HTML tags — good enough for indexing
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            sections.append(text)
    if not sections:
        raise ValueError(f"No text extracted from EPUB: {path}")
    return "\n\n".join(sections)


def extract_markdown(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def extract_image(path: str) -> str:
    """Run OCR on image files."""
    text = ocr_image(path)
    if not text.strip():
        logger.info("OCR on %s yielded no detectable text", path)
    return text


# ---------------------------------------------------------------------------
# Registry — maps (suffix / content-type pattern) to extractor
# ---------------------------------------------------------------------------

_EXTRACTORS_BY_SUFFIX: dict[str, callable] = {
    ".txt": extract_txt,
    ".text": extract_txt,
    ".log": extract_txt,
    ".md": extract_markdown,
    ".markdown": extract_markdown,
    ".csv": extract_csv,
    ".tsv": extract_csv,
    ".pdf": extract_pdf,
    ".xlsx": extract_xlsx,
    ".xls": extract_xlsx,
    ".epub": extract_epub,
    # Image / OCR formats
    ".png": extract_image,
    ".jpg": extract_image,
    ".jpeg": extract_image,
    ".webp": extract_image,
    ".tiff": extract_image,
    ".tif": extract_image,
    ".bmp": extract_image,
}


def extract_text(path: str, content_type: str | None = None) -> str:
    """Extract and clean text from a file. Returns empty string for unsupported formats.

    Raises on extraction failure (file matched a parser but parsing broke).
    Applies text cleaning and normalization to all extracted output.
    """
    suffix = Path(path).suffix.lower()

    extractor = _EXTRACTORS_BY_SUFFIX.get(suffix)

    # Content-type fallbacks
    if extractor is None and content_type:
        if "text" in content_type:
            extractor = extract_txt
        elif content_type.startswith("image/"):
            extractor = extract_image

    if extractor is None:
        return ""

    raw_text = extractor(path)
    return clean_text(raw_text)


def is_supported(path: str, content_type: str | None = None) -> bool:
    """Return True if extract_text would attempt parsing for this file."""
    suffix = Path(path).suffix.lower()
    if suffix in _EXTRACTORS_BY_SUFFIX:
        return True
    if content_type:
        if "text" in content_type or content_type.startswith("image/"):
            return True
    return False
