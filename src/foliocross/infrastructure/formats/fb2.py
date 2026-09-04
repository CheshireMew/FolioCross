"""FictionBook 2 parser."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _section_content(section: ET.Element):
    """Yield this section's content while leaving child sections to their own chapters."""

    for child in section:
        if _local(child.tag) == "section":
            continue
        yield from child.iter()


def parse_fb2(path: str, source_lang: str = "auto") -> ParsedBook:
    root = ET.parse(path).getroot()
    title = Path(path).stem
    author = ""
    for node in root.iter():
        name = _local(node.tag)
        if name == "book-title" and node.text and node.text.strip():
            title = node.text.strip()
        elif name == "author" and not author:
            parts = [child.text.strip() for child in node if child.text and child.text.strip()]
            author = " ".join(parts)
    chapters: list[ChapterDraft] = []
    ordinal = 0
    sections = [node for node in root.iter() if _local(node.tag) == "section"]
    for section in sections:
        paragraphs = []
        chapter_title = ""
        local_nodes = list(_section_content(section))
        title_paragraphs = {
            id(child)
            for title_node in local_nodes
            if _local(title_node.tag) == "title"
            for child in title_node.iter()
            if _local(child.tag) == "p"
        }
        for node in local_nodes:
            name = _local(node.tag)
            text = "".join(node.itertext()).strip()
            if not text:
                continue
            if name == "title" and not chapter_title:
                chapter_title = text
            elif name in {"p", "subtitle", "text-author"} and id(node) not in title_paragraphs:
                paragraphs.append(
                    SegmentDraft(text, {"resource": Path(path).name, "ordinal": ordinal})
                )
                ordinal += 1
        if paragraphs:
            chapters.append(
                ChapterDraft(
                    chapter_title or f"第 {len(chapters) + 1} 章",
                    paragraphs,
                    {"section": len(chapters)},
                )
            )
    if not chapters:
        raise ValueError("FB2 中没有可翻译正文")
    return ParsedBook(title, author, "fb2", source_lang, chapters)
