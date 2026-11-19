"""Multi-format text extraction.

Each extractor takes a file path and returns extracted text.
Raises on failure — callers decide how to handle errors.
"""

import csv
import io
import logging
from pathlib import Path

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
    from ebooklib import epub
    from ebooklib import ITEM_DOCUMENT
    import re

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
}


def extract_text(path: str, content_type: str | None = None) -> str:
    """Extract text from a file. Returns empty string for unsupported formats.

    Raises on extraction *failure* (file matched a parser but parsing broke).
    Returns "" when no parser matches (unsupported format).
    """
    suffix = Path(path).suffix.lower()

    # Try suffix first
    extractor = _EXTRACTORS_BY_SUFFIX.get(suffix)

    # Fallback: treat anything with "text" in the content-type as plain text
    if extractor is None and content_type and "text" in content_type:
        extractor = extract_txt

    if extractor is None:
        return ""

    return extractor(path)
