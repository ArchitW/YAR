"""Text cleaning and normalization pipeline for ingested documents and OCR outputs."""

import re
import unicodedata


def clean_text(text: str) -> str:
    """Normalize and clean raw extracted document or OCR text.

    Steps:
    1. Unicode NFKC normalization (combining accents, ligature resolution).
    2. Carriage return normalization (\r\n -> \n, \r -> \n).
    3. Removal of non-printable ASCII control characters (keeping \n and \t).
    4. Repair of line-break hyphenation (e.g. 'implemen-\\ntation' -> 'implementation').
    5. Per-line horizontal whitespace trimming and collapsing.
    6. Normalization of excessive paragraph breaks (max 2 consecutive newlines).
    """
    if not text:
        return ""

    # 1. Unicode NFKC normalization
    text = unicodedata.normalize("NFKC", text)

    # 2. Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Strip non-printable ASCII control characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 4. Repair line-break hyphenation (common in PDF / OCR columns)
    text = re.sub(r"(\b\w+)-\n(\w+\b)", r"\1\2", text)

    # 5. Clean up horizontal spaces per line
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]

    # 6. Collapse excessive vertical blank lines
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned
