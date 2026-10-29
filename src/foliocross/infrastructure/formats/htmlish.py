"""HTML/XHTML block extraction and in-place translation fillback."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft
from ...errors import FolioCrossError
from .markers import MARKER_PATTERN, replace_block_contents, serialize_block

BLOCK_SELECTOR = (
    "h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,td,th,pre,"
    "div,section,article,main,aside,header,footer,nav,figure,body,details,summary"
)
BLOCK_NAMES = set(BLOCK_SELECTOR.split(","))
DIRECT_BLOCK_ATTR = "data-foliocross-direct"


def _non_prose(node) -> bool:
    return isinstance(node, Comment) or (
        isinstance(node, Tag)
        and (node.name in {"script", "style", "template"} or node.has_attr("hidden"))
    )


def _wrap_direct_content(soup: BeautifulSoup, candidates: list[Tag]) -> None:
    """Expose prose beside nested blocks without flattening or duplicating child blocks."""

    for parent in candidates:
        if not parent.select_one(BLOCK_SELECTOR):
            continue
        group: list[Tag | NavigableString] = []

        def flush() -> None:
            nonlocal group
            if not group:
                return
            visible = BeautifulSoup("".join(str(item) for item in group), "html.parser").get_text(
                " ", strip=True
            )
            if visible:
                wrapper = soup.new_tag("span")
                wrapper[DIRECT_BLOCK_ATTR] = "1"
                group[0].insert_before(wrapper)
                for node in group:
                    wrapper.append(node.extract())
            group = []

        for child in list(parent.contents):
            contains_block = isinstance(child, Tag) and (
                child.name in BLOCK_NAMES or child.select_one(BLOCK_SELECTOR)
            )
            if contains_block or _non_prose(child):
                flush()
            else:
                group.append(child)
        flush()


def content_blocks(soup: BeautifulSoup) -> list[Tag]:
    candidates = [
        item
        for item in soup.select(BLOCK_SELECTOR)
        if isinstance(item, Tag) and not any(_non_prose(node) for node in [item, *item.parents])
    ]
    _wrap_direct_content(soup, candidates)
    candidates = [
        item
        for item in soup.select(f"{BLOCK_SELECTOR},span[{DIRECT_BLOCK_ATTR}]")
        if isinstance(item, Tag) and not any(_non_prose(node) for node in [item, *item.parents])
    ]
    # A blockquote, list item or table cell often contains paragraph blocks. Translating
    # both the parent and the child duplicates the same prose and breaks template mapping.
    blocks = [item for item in candidates if not item.select_one(BLOCK_SELECTOR)]
    return blocks


def remove_internal_wrappers(soup: BeautifulSoup) -> None:
    for wrapper in list(soup.select(f"span[{DIRECT_BLOCK_ATTR}]")):
        wrapper.unwrap()


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
        visible = MARKER_PATTERN.sub("", text).strip()
        if not visible:
            continue
        if not title and block.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            title = block.get_text(" ", strip=True)
        segments.append(
            SegmentDraft(
                source_text=text,
                locator={
                    "resource": resource,
                    "ordinal": ordinal,
                    "tag": block.name,
                    "extraction_version": 2,
                },
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
    return ParsedBook(
        title,
        "",
        "html",
        source_lang,
        [chapter],
        {"html_resource": Path(path).name, "extraction_version": 2},
    )


def fill_html_template(
    source_path: str, output_path: str, segments: Iterable[dict], *, bilingual: bool = False
) -> str:
    soup = BeautifulSoup(Path(source_path).read_bytes(), "lxml")
    blocks = content_blocks(soup)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for segment in segments:
        locator = segment.get("locator") or {}
        if "ordinal" not in locator:
            raise FolioCrossError("html_mapping_incomplete", "有段落缺少有效的 HTML 原位定位信息。")
        grouped[int(locator["ordinal"])].append(segment)
    for ordinal, parts in grouped.items():
        if ordinal < 0 or ordinal >= len(blocks):
            raise FolioCrossError(
                "html_mapping_incomplete", f"HTML 正文定位已失效：找不到第 {ordinal + 1} 个段落。"
            )
        parts.sort(key=lambda item: int(item["locator"].get("logical_part", 0)))
        target = "".join(item["target_text"] or item["source_text"] for item in parts)
        source = "".join(item["source_text"] for item in parts)
        fresh_source, _ = serialize_block(
            blocks[ordinal],
            identity=parts[0]["locator"].get(
                "marker_identity", f"{Path(source_path).name}:{ordinal}"
            ),
        )
        if fresh_source != source:
            raise FolioCrossError(
                "html_source_changed",
                f"HTML 第 {ordinal + 1} 个段落与导入时的原文不一致，已停止导出。",
            )
        markers = [marker for item in parts for marker in item["markers"]]
        if bilingual:
            target = f"{target}\n{source}"
        replace_block_contents(blocks[ordinal], target, markers)
    remove_internal_wrappers(soup)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(str(soup), encoding="utf-8")
    return output_path
