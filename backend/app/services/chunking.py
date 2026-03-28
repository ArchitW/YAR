import re

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

