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
from typing import Any, Optional

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


def extract_pdf_boxes(path: str) -> list[dict[str, Any]]:
    """Extract text runs with bounding boxes and page dimensions from a PDF (TKT-017).

    Returns a list of page blocks:
    [
        {
            "page": int,  # 1-indexed
            "text": str,
            "bbox": [x0, y0, x1, y1],  # PDF coordinates in points
            "page_width": float,
            "page_height": float,
            "runs": [
                {"text": str, "x0": float, "y0": float, "x1": float, "y1": float},
                ...
            ]
        },
        ...
    ]
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(path)
    except Exception as e:
        logger.warning("Failed to open PDF for bounding box extraction: %s", e)
        return []

    blocks: list[dict[str, Any]] = []
    for page_idx, page in enumerate(reader.pages):
        page_num = page_idx + 1
        try:
            page_w = float(page.mediabox.width)
            page_h = float(page.mediabox.height)
        except Exception:
            page_w, page_h = 612.0, 792.0

        runs: list[dict[str, Any]] = []

        def visitor(text: str, cm: Any, tm: Any, font_dict: Any, font_size: Any) -> None:
            if text and text.strip():
                try:
                    x = float(tm[4])
                    y = float(tm[5])
                    fs = float(font_size) if font_size else 10.0
                    w = len(text) * fs * 0.55
                    h = fs
                    runs.append({
                        "text": text,
                        "x0": round(x, 1),
                        "y0": round(y, 1),
                        "x1": round(x + w, 1),
                        "y1": round(y + h, 1),
                    })
                except Exception:
                    pass

        try:
            extracted = page.extract_text(visitor_text=visitor) or ""
        except Exception:
            extracted = ""

        if runs:
            min_x = min(r["x0"] for r in runs)
            min_y = min(r["y0"] for r in runs)
            max_x = max(r["x1"] for r in runs)
            max_y = max(r["y1"] for r in runs)
            blocks.append({
                "page": page_num,
                "text": extracted.strip(),
                "bbox": [round(min_x, 1), round(min_y, 1), round(max_x, 1), round(max_y, 1)],
                "page_width": round(page_w, 1),
                "page_height": round(page_h, 1),
                "runs": runs,
            })
    return blocks


def find_chunk_bbox(
    chunk_text: str,
    page_number: int | None,
    pdf_blocks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the best-fitting bounding box for a chunk of text within extracted PDF blocks."""
    if not pdf_blocks:
        return None

    # Filter candidate blocks by page if specified
    candidate_blocks = (
        [b for b in pdf_blocks if b.get("page") == page_number]
        if page_number is not None
        else pdf_blocks
    )
    if not candidate_blocks:
        candidate_blocks = pdf_blocks

    clean_chunk = "".join(chunk_text.split()).lower()
    if not clean_chunk:
        return None

    # Check for matched runs within candidate blocks
    best_match: dict[str, Any] | None = None
    best_overlap = 0

    for block in candidate_blocks:
        runs = block.get("runs", [])
        matched_runs = []
        for r in runs:
            rt = "".join(r["text"].split()).lower()
            if rt and (rt in clean_chunk or clean_chunk in rt):
                matched_runs.append(r)

        if matched_runs:
            min_x = min(r["x0"] for r in matched_runs)
            min_y = min(r["y0"] for r in matched_runs)
            max_x = max(r["x1"] for r in matched_runs)
            max_y = max(r["y1"] for r in matched_runs)
            overlap = len(matched_runs)
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = {
                    "page": block["page"],
                    "bbox": [round(min_x, 1), round(min_y, 1), round(max_x, 1), round(max_y, 1)],
                    "page_width": block["page_width"],
                    "page_height": block["page_height"],
                }

    if best_match:
        return best_match

    # Fallback to block enclosing bounds if chunk overlaps with block text
    for block in candidate_blocks:
        block_text = "".join(block.get("text", "").split()).lower()
        if clean_chunk in block_text or block_text in clean_chunk:
            return {
                "page": block["page"],
                "bbox": block["bbox"],
                "page_width": block["page_width"],
                "page_height": block["page_height"],
            }

    # Final fallback: use the first candidate block
    first = candidate_blocks[0]
    return {
        "page": first["page"],
        "bbox": first["bbox"],
        "page_width": first["page_width"],
        "page_height": first["page_height"],
    }


def rows_to_markdown_table(rows: list[Any], data_rows: list[list[str]] | None = None) -> str:
    """Format rows as a clean GitHub-flavored Markdown table (TKT-019).

    Accepts either:
    - rows: list of all rows where rows[0] is the header
    - or rows_to_markdown_table(headers, data_rows)
    """
    if data_rows is not None:
        if not rows and not data_rows:
            return ""
        valid_rows = [rows] + list(data_rows)
    else:
        if not rows:
            return ""
        valid_rows = list(rows)

    valid_rows = [r for r in valid_rows if any(str(cell).strip() for cell in r)]
    if not valid_rows:
        return ""

    header = [str(c).replace("\n", " ").strip() for c in valid_rows[0]]
    if not any(header):
        header = [f"Col {i+1}" for i in range(len(header))]

    num_cols = len(header)
    separator = ["---"] * num_cols
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in valid_rows[1:]:
        padded = [str(cell).replace("\n", " ").strip() for cell in row]
        if len(padded) < num_cols:
            padded += [""] * (num_cols - len(padded))
        lines.append("| " + " | ".join(padded[:num_cols]) + " |")

    return "\n".join(lines)


def extract_csv(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return ""
    return rows_to_markdown_table(rows)


def extract_xlsx(path: str) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    sheets: list[str] = []
    for ws in wb.worksheets:
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append(cells)
        if rows:
            table_md = rows_to_markdown_table(rows)
            if table_md:
                sheets.append(f"[Sheet: {ws.title}]\n{table_md}")
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
