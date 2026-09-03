"""Supported-format dispatch."""

from __future__ import annotations

from pathlib import Path

from ...domain.models import ParsedBook
from ...errors import FolioCrossError
from .calibre import is_convertible
from .docx import parse_docx
from .epub import parse_epub
from .fb2 import parse_fb2
from .htmlish import parse_html
from .text import parse_text

SUPPORTED_INPUTS = {".epub", ".fb2", ".html", ".htm", ".txt", ".md", ".markdown", ".docx"}


def parse_book(path: str, source_lang: str = "auto") -> ParsedBook:
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".epub":
            return parse_epub(path, source_lang)
        if suffix == ".fb2":
            return parse_fb2(path, source_lang)
        if suffix in {".html", ".htm"}:
            return parse_html(path, source_lang)
        if suffix in {".txt", ".md", ".markdown"}:
            return parse_text(path, source_lang)
        if suffix == ".docx":
            return parse_docx(path, source_lang)
        if is_convertible(path):
            raise FolioCrossError("conversion_required", "该格式需要先通过 Calibre 转换为 EPUB。")
    except FolioCrossError:
        raise
    except Exception as error:
        raise FolioCrossError("parse_failed", f"无法解析 {Path(path).name}：{error}") from error
    supported = ", ".join(sorted(SUPPORTED_INPUTS))
    raise FolioCrossError(
        "unsupported_format", f"不支持 {suffix or '无扩展名'} 文件。原生格式：{supported}"
    )
