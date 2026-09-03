"""HTML/XHTML block extraction and in-place translation fillback."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft
from .markers import replace_block_contents, serialize_block

BLOCK_SELECTOR = "h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,td,th"


def content_blocks(soup: BeautifulSoup) -> list[Tag]:
    blocks = [item for item in soup.select(BLOCK_SELECTOR) if isinstance(item, Tag)]
    if blocks:
        return blocks
    return [
        item
        for item in soup.find_all(["div", "section"])
        if isinstance(item, Tag) and not item.find(["div", "section", "p"])
    ]


def extract_html_chapter(
    data: bytes | str,
    *,
    resource: str,
    chapter_index: int,
    parser: str = "lxml",
) -> ChapterDraft | None:
    soup = BeautifulSoup(data, parser)
    segments: list[SegmentDraft] = []
    title = ""
    for ordinal, block in enumerate(content_blocks(soup)):
        text, markers = serialize_block(block, identity=f"{resource}:{ordinal}")
        visible = text.strip()
        if not visible:
            continue
        if not title and block.name and block.name.lower().startswith("h"):
            title = block.get_text(" ", strip=True)
        segments.append(
            SegmentDraft(
                source_text=text,
                locator={"resource": resource, "ordinal": ordinal, "tag": block.name},
                markers=markers,
            )
        )
    if not segments:
        return None
    return ChapterDraft(title or f"第 {chapter_index + 1} 章", segments, {"resource": resource})


def parse_html(path: str, source_lang: str = "auto") -> ParsedBook:
    raw = Path(path).read_bytes()
    soup = BeautifulSoup(raw, "lxml")
    chapter = extract_html_chapter(raw, resource=Path(path).name, chapter_index=0)
    if chapter is None:
        raise ValueError("HTML 中没有可翻译正文")
    title_node = soup.find("title") or soup.find("h1")
    title = title_node.get_text(" ", strip=True) if title_node else Path(path).stem
    return ParsedBook(title, "", "html", source_lang, [chapter], {"html_resource": Path(path).name})


def fill_html_template(
    source_path: str, output_path: str, segments: Iterable[dict], *, bilingual: bool = False
) -> str:
    soup = BeautifulSoup(Path(source_path).read_bytes(), "lxml")
    blocks = content_blocks(soup)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for segment in segments:
        grouped[int(segment["locator"]["ordinal"])].append(segment)
    for ordinal, parts in grouped.items():
        if ordinal >= len(blocks):
            continue
        parts.sort(key=lambda item: int(item["locator"].get("logical_part", 0)))
        target = "".join(item["target_text"] or item["source_text"] for item in parts)
        source = "".join(item["source_text"] for item in parts)
        markers = [marker for item in parts for marker in item["markers"]]
        if bilingual:
            target = f"{target}\n{source}"
        replace_block_contents(blocks[ordinal], target, markers)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(str(soup), encoding="utf-8")
    return output_path
