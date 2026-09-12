"""Plain-text transcript → Markdown conversion.

Coursera's ``subtitlesTxt`` subtitle source returns plain text with one
sentence per line and no timestamps. This module reshapes that into a clean
Markdown document: an H1 title followed by subtitle lines joined into flowing
paragraphs, separated by blank lines.

Pure stdlib — no new dependencies.
"""

from __future__ import annotations

import re

# Paragraph shaping heuristics.
_MAX_SENTENCES = 5      # max sentences per paragraph
_MAX_CHARS = 500        # max paragraph length before forced break

# Sentences ending in these characters may start a new paragraph.
_SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")


def _clean_lines(text: str) -> list[str]:
    """Normalize the raw subtitle text into a list of non-empty lines.

    Collapses internal whitespace, drops blank lines and consecutive
    duplicates (Coursera repeats some lines across cues)."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return lines


def txt_to_markdown(text: str, title: str) -> str:
    """Convert a plain-text transcript into a Markdown document.

    The output is ``# {title}`` followed by the transcript grouped into
    readable paragraphs. Returns a document ending with a single newline.
    """
    body = ""
    lines = _clean_lines(text)
    if lines:
        paragraphs: list[str] = []
        current: list[str] = []
        sentences = 0

        def _flush() -> None:
            nonlocal current, sentences
            if current:
                paragraphs.append(" ".join(current))
                current = []
                sentences = 0

        for line in lines:
            current.append(line)
            if _SENTENCE_END.search(line):
                sentences += 1
            length = sum(len(part) for part in current) + len(current) - 1
            if sentences >= _MAX_SENTENCES or length >= _MAX_CHARS:
                _flush()
        _flush()
        body = "\n\n".join(paragraphs)

    if body:
        return f"# {title}\n\n{body}\n"
    return f"# {title}\n"