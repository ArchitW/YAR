import re
from typing import Any

def split_text(text: str, target: int = 400, overlap: int = 50) -> list[str]:
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current.split()) + len(para.split()) <= target:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            if len(para.split()) > target:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                buf = ""
                for s in sentences:
                    if len(buf.split()) + len(s.split()) <= target:
                        buf = (buf + " " + s).strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = s
                if buf:
                    chunks.append(buf)
                current = ""
            else:
                current = para
    if current:
        chunks.append(current)
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_words = chunks[i-1].split()
            tail = " ".join(prev_words[-overlap:]) if len(prev_words) > overlap else chunks[i-1]
            overlapped.append((tail + "\n" + chunks[i]).strip())
        chunks = overlapped
    return chunks

def adaptive_chunk(text: str) -> list[str]:
    if re.search(r"^#{1,6}\s", text, re.M):
        sections = re.split(r"(?=^#{1,6}\s)", text, flags=re.M)
        out = []
        for s in sections:
            s = s.strip()
            if s:
                out.extend(split_text(s, target=400, overlap=50))
        return out if out else split_text(text)
    return split_text(text)

def late_chunk(text: str) -> list[str]:
    # Late chunking needs token-level embeddings; fall back to adaptive chunking.
    return adaptive_chunk(text)


def hierarchical_chunk(
    text: str,
    parent_target: int = 800,
    child_target: int = 150,
    child_overlap: int = 25,
) -> list[dict[str, Any]]:
    """Split text into parent section blocks and fine-grained child spans (TKT-019).

    Returns a list of dicts:
    [
        {
            "child_text": str,
            "child_index": int,
            "parent_id": str,
            "parent_index": int,
            "parent_text": str,
            "section": str | None,
        },
        ...
    ]
    """
    if not text or not text.strip():
        return []

    # 1. Identify parent sections based on headers or paragraph blocks
    if re.search(r"^#{1,6}\s", text, re.M):
        raw_sections = [s.strip() for s in re.split(r"(?=^#{1,6}\s)", text, flags=re.M) if s.strip()]
    else:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        raw_sections = []
        buf = []
        buf_words = 0
        for p in paras:
            p_words = len(p.split())
            if buf_words + p_words > parent_target and buf:
                raw_sections.append("\n\n".join(buf))
                buf = [p]
                buf_words = p_words
            else:
                buf.append(p)
                buf_words += p_words
        if buf:
            raw_sections.append("\n\n".join(buf))

    if not raw_sections:
        raw_sections = [text.strip()]

    # 2. Slice each parent into child spans
    results: list[dict[str, Any]] = []
    child_counter = 0

    for p_idx, parent_text in enumerate(raw_sections):
        parent_id = f"parent_{p_idx}"
        header_match = re.match(r"^#{1,6}\s+(.+)$", parent_text, re.M)
        section_name = header_match.group(1).strip() if header_match else None

        parent_words = len(parent_text.split())
        if parent_words <= child_target:
            children = [parent_text]
        else:
            children = split_text(parent_text, target=child_target, overlap=child_overlap)

        for child in children:
            if not child.strip():
                continue
            results.append({
                "child_text": child.strip(),
                "child_index": child_counter,
                "parent_id": parent_id,
                "parent_index": p_idx,
                "parent_text": parent_text.strip(),
                "section": section_name,
            })
            child_counter += 1

    return results
