import re

from app.models.schemas import Clause

_NUMBERED_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]\s+\S")
_ARTICLE_RE = re.compile(r"^\s*(SECTION|ARTICLE)\s+[IVXLC\d]+\b", re.IGNORECASE)


def _is_boundary(line: str) -> bool:
    return bool(_NUMBERED_RE.match(line) or _ARTICLE_RE.match(line))


def split_clauses(text: str) -> list[Clause]:
    """Rule-based clause splitting: numbered clauses / section headings take
    priority; blank-line-separated paragraphs are the fallback for
    unnumbered documents.
    """
    lines = [line.rstrip() for line in text.strip().splitlines()]
    boundaries = [i for i, line in enumerate(lines) if _is_boundary(line)]

    if boundaries:
        clauses = []
        for idx, start in enumerate(boundaries):
            end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(lines)
            block = [line for line in lines[start:end] if line.strip()]
            if not block:
                continue
            clauses.append(
                Clause(
                    id=f"clause_{idx + 1}",
                    heading=block[0].strip(),
                    text="\n".join(block).strip(),
                )
            )
        return clauses

    paragraphs = re.split(r"\n\s*\n", text.strip())
    return [
        Clause(id=f"clause_{i + 1}", heading=None, text=paragraph.strip())
        for i, paragraph in enumerate(paragraphs)
        if paragraph.strip()
    ]
