"""DOCX parser and OOXML-package-preserving template fillback."""

from __future__ import annotations

import posixpath
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from lxml import etree

from ...domain.models import ChapterDraft, ParsedBook, SegmentDraft
from ...errors import FolioCrossError

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DC_NS = "http://purl.org/dc/elements/1.1/"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": WORD_NS, "dc": DC_NS, "cp": CP_NS}
DOCUMENT_XML = "word/document.xml"


def _parse_xml(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    return etree.fromstring(data, parser=parser)


def _has_ancestor(element: etree._Element, local_names: set[str]) -> bool:
    return any(
        etree.QName(ancestor).localname in local_names for ancestor in element.iterancestors()
    )


def _document_paragraphs(root: etree._Element) -> list[etree._Element]:
    return [
        paragraph
        for paragraph in root.xpath(".//w:p", namespaces=NS)
        if not _has_ancestor(paragraph, {"txbxContent", "del"})
    ]


def _visible_text_nodes(paragraph: etree._Element) -> list[etree._Element]:
    return [
        node
        for node in paragraph.xpath(".//w:t", namespaces=NS)
        if not _has_ancestor(node, {"txbxContent", "del"})
    ]


def _paragraph_text(paragraph: etree._Element) -> str:
    return "".join(node.text or "" for node in _visible_text_nodes(paragraph)).strip()


def _style_names(archive: zipfile.ZipFile) -> dict[str, tuple[str, bool]]:
    try:
        root = _parse_xml(archive.read("word/styles.xml"))
    except KeyError:
        return {}
    result: dict[str, tuple[str, bool]] = {}
    for style in root.xpath(".//w:style[@w:type='paragraph']", namespaces=NS):
        style_id = style.get(f"{{{WORD_NS}}}styleId", "")
        name = style.find("w:name", namespaces=NS)
        display_name = name.get(f"{{{WORD_NS}}}val", style_id) if name is not None else style_id
        result[style_id] = (
            display_name,
            style.find("w:pPr/w:outlineLvl", namespaces=NS) is not None,
        )
    return result


def _paragraph_style(
    paragraph: etree._Element, names: dict[str, tuple[str, bool]]
) -> tuple[str, bool]:
    style_node = paragraph.find("w:pPr/w:pStyle", namespaces=NS)
    style_id = style_node.get(f"{{{WORD_NS}}}val", "") if style_node is not None else ""
    name, style_is_heading = names.get(style_id, (style_id, False))
    outline = paragraph.find("w:pPr/w:outlineLvl", namespaces=NS)
    heading = name.casefold().startswith("heading") or style_is_heading or outline is not None
    return name, heading


def _core_property(archive: zipfile.ZipFile, expression: str) -> str:
    try:
        core = _parse_xml(archive.read("docProps/core.xml"))
    except KeyError:
        return ""
    value = core.xpath(expression, namespaces=NS)
    if isinstance(value, str):
        return value.strip()
    return str(value[0]).strip() if value else ""


def parse_docx(path: str, source_lang: str = "auto") -> ParsedBook:
    with zipfile.ZipFile(path) as archive:
        try:
            root = _parse_xml(archive.read(DOCUMENT_XML))
        except KeyError as exc:
            raise FolioCrossError("docx_document_missing", "DOCX 缺少 word/document.xml。") from exc
        title = _core_property(archive, "string(.//dc:title)") or Path(path).stem
        author = _core_property(archive, "string(.//dc:creator)")
        styles = _style_names(archive)

    chapters: list[ChapterDraft] = []
    current_title = title
    current: list[SegmentDraft] = []
    for ordinal, paragraph in enumerate(_document_paragraphs(root)):
        text = _paragraph_text(paragraph)
        if not text:
            continue
        style, is_heading = _paragraph_style(paragraph, styles)
        if is_heading and current:
            chapters.append(ChapterDraft(current_title, current, {"source": "docx"}))
            current = []
        if is_heading:
            current_title = text
        current.append(
            SegmentDraft(
                text,
                {
                    "kind": "docx_paragraph",
                    "document_paragraph": ordinal,
                    "style": style,
                },
            )
        )
    if current:
        chapters.append(ChapterDraft(current_title, current, {"source": "docx"}))
    if not chapters:
        raise FolioCrossError("docx_no_text", "DOCX 中没有可翻译正文。")

    warnings: list[str] = []
    if root.xpath(".//w:txbxContent", namespaces=NS):
        warnings.append("检测到文本框；首版不会翻译文本框内文字，原内容会完整保留。")
    if root.xpath(".//w:ins | .//w:del", namespaces=NS):
        warnings.append("检测到修订记录；删除内容不翻译，可见的新增正文会参与翻译。")
    return ParsedBook(
        title,
        author,
        "docx",
        source_lang,
        chapters,
        metadata={"template_path": str(Path(path).resolve()), "package_mode": "ooxml_in_place"},
        warnings=warnings,
    )


def _set_text_node(node: etree._Element, text: str) -> None:
    lines = text.split("\n")
    node.text = lines[0]
    if lines[0].startswith(" ") or lines[0].endswith(" "):
        node.set(f"{{{XML_NS}}}space", "preserve")
    else:
        node.attrib.pop(f"{{{XML_NS}}}space", None)
    parent = node.getparent()
    if parent is None:
        return
    insert_at = parent.index(node) + 1
    for line in lines[1:]:
        parent.insert(insert_at, etree.Element(f"{{{WORD_NS}}}br"))
        insert_at += 1
        extra = etree.Element(f"{{{WORD_NS}}}t")
        extra.text = line
        if line.startswith(" ") or line.endswith(" "):
            extra.set(f"{{{XML_NS}}}space", "preserve")
        parent.insert(insert_at, extra)
        insert_at += 1


def _replace_paragraph(paragraph: etree._Element, text: str) -> None:
    nodes = _visible_text_nodes(paragraph)
    if not nodes:
        raise FolioCrossError(
            "docx_mapping_incomplete", "DOCX 正文定位存在，但对应段落没有可回填的文本节点。"
        )
    source_lengths = [max(1, len(node.text or "")) for node in nodes]
    total = sum(source_lengths)
    cursor = 0
    cumulative = 0
    for index, node in enumerate(nodes):
        cumulative += source_lengths[index]
        end = len(text) if index == len(nodes) - 1 else round(len(text) * cumulative / total)
        _set_text_node(node, text[cursor:end])
        cursor = end


def export_docx_template(
    source_path: str, output_path: str, segments: Iterable[dict], *, bilingual: bool = False
) -> str:
    grouped: dict[int, list[dict]] = defaultdict(list)
    for segment in segments:
        locator = segment.get("locator") or {}
        if locator.get("kind") != "docx_paragraph" or "document_paragraph" not in locator:
            raise FolioCrossError("docx_mapping_incomplete", "有段落缺少有效的 DOCX 原位定位信息。")
        grouped[int(locator["document_paragraph"])].append(segment)

    with zipfile.ZipFile(source_path) as source:
        try:
            root = _parse_xml(source.read(DOCUMENT_XML))
        except KeyError as exc:
            raise FolioCrossError("docx_document_missing", "DOCX 缺少 word/document.xml。") from exc
        paragraphs = _document_paragraphs(root)
        for ordinal, parts in grouped.items():
            if ordinal < 0 or ordinal >= len(paragraphs):
                raise FolioCrossError(
                    "docx_mapping_incomplete",
                    f"DOCX 正文定位已失效：找不到第 {ordinal + 1} 个段落。",
                )
            parts.sort(key=lambda item: int(item["locator"].get("logical_part", 0)))
            stored_source = "".join(item["source_text"] for item in parts)
            if _paragraph_text(paragraphs[ordinal]) != stored_source.strip():
                raise FolioCrossError(
                    "docx_source_changed",
                    f"DOCX 第 {ordinal + 1} 个段落与导入时的原文不一致，已停止导出。",
                )
            target = "".join(item["target_text"] or item["source_text"] for item in parts)
            if bilingual:
                target = f"{target}\n{stored_source}"
            _replace_paragraph(paragraphs[ordinal], target)

        rendered_document = etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, standalone=True
        )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                data = (
                    rendered_document
                    if posixpath.normpath(info.filename) == DOCUMENT_XML
                    else source.read(info)
                )
                target.writestr(info, data)
    return str(Path(output_path))
