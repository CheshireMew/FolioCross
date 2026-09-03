"""Shared segmentation helpers."""

from __future__ import annotations

import re
from dataclasses import replace

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft

SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\.])\s*")


def split_long_segments(book: ParsedBook, max_chars: int) -> ParsedBook:
    chapters: list[ChapterDraft] = []
    for chapter in book.chapters:
        segments: list[SegmentDraft] = []
        for segment in chapter.segments:
            if len(segment.source_text) <= max_chars or segment.markers:
                locator = dict(segment.locator)
                locator.setdefault("logical_part", 0)
                locator.setdefault("logical_parts", 1)
                segments.append(replace(segment, locator=locator))
                continue
            chunks: list[str] = []
            current = ""
            for sentence in filter(None, SENTENCE_BOUNDARY.split(segment.source_text)):
                if current and len(current) + len(sentence) > max_chars:
                    chunks.append(current)
                    current = ""
                if len(sentence) > max_chars:
                    if current:
                        chunks.append(current)
                        current = ""
                    chunks.extend(
                        sentence[index : index + max_chars]
                        for index in range(0, len(sentence), max_chars)
                    )
                else:
                    current += sentence
            if current:
                chunks.append(current)
            logical_id = f"{segment.locator.get('resource', '')}:{segment.locator.get('ordinal', len(segments))}"
            for part, chunk in enumerate(chunks):
                locator = dict(segment.locator)
                locator.update(
                    {"logical_id": logical_id, "logical_part": part, "logical_parts": len(chunks)}
                )
                segments.append(SegmentDraft(chunk, locator=locator))
        chapters.append(ChapterDraft(chapter.title, segments, dict(chapter.locator)))
    return replace(book, chapters=chapters)


def batches(segments: list[dict], max_chars: int) -> list[list[dict]]:
    result: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for segment in segments:
        length = len(segment["source_text"])
        if current and size + length > max_chars:
            result.append(current)
            current = []
            size = 0
        current.append(segment)
        size += length
    if current:
        result.append(current)
    return result
