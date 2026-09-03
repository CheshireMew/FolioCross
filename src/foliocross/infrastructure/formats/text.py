"""Plain-text and Markdown parsing."""

from __future__ import annotations

import re
from pathlib import Path

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft

HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
CHAPTER_LINE = re.compile(
    r"^\s*(?:chapter\s+\d+|第[一二三四五六七八九十百千0-9]+[章节卷部]).*$", re.IGNORECASE
)


def parse_text(path: str, source_lang: str = "auto") -> ParsedBook:
    text = Path(path).read_text(encoding="utf-8-sig")
    chapters: list[ChapterDraft] = []
    title = Path(path).stem
    current_title = title
    current: list[SegmentDraft] = []
    ordinal = 0
    paragraphs = re.split(r"\n\s*\n", text)
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        first = paragraph.splitlines()[0].strip()
        heading = HEADING.match(first)
        is_heading = bool(heading or ("\n" not in paragraph and CHAPTER_LINE.match(first)))
        if is_heading and current:
            chapters.append(ChapterDraft(current_title, current, {"source": "text"}))
            current = []
        if is_heading:
            current_title = heading.group(2).strip() if heading else first
            if not chapters and title == Path(path).stem:
                title = current_title
        current.append(SegmentDraft(paragraph, {"resource": Path(path).name, "ordinal": ordinal}))
        ordinal += 1
    if current:
        chapters.append(ChapterDraft(current_title, current, {"source": "text"}))
    if not chapters:
        raise ValueError("文本文件中没有可翻译正文")
    return ParsedBook(
        title, "", Path(path).suffix.lower().lstrip(".") or "txt", source_lang, chapters
    )
