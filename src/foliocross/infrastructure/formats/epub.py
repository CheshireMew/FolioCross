"""EPUB parser and template-preserving exporter."""

from __future__ import annotations

import posixpath
import re
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from ...domain.models import ParsedBook
from ...errors import FolioCrossError
from .htmlish import content_blocks, extract_html_chapter, remove_internal_wrappers
from .markers import MARKER_PATTERN, replace_block_contents, serialize_block

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


def _navigation_label(parts: list[dict]) -> str:
    value = "".join(item["target_text"] or item["source_text"] for item in parts)
    return re.sub(r"\s+", " ", MARKER_PATTERN.sub("", value)).strip()


def _resolved_resource(owner: str, href: str) -> str:
    clean = href.split("#", 1)[0].split("?", 1)[0]
    if not clean:
        return owner
    return posixpath.normpath(posixpath.join(posixpath.dirname(owner), clean))


def _navigation_target(owner: str, href: str) -> str:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        return ""
    resource = _resolved_resource(owner, unquote(parsed.path))
    return f"{resource}#{unquote(parsed.fragment)}" if parsed.fragment else resource


def _linked_note_resources(data: bytes, owner: str) -> list[str]:
    soup = BeautifulSoup(data, "lxml-xml")
    result: list[str] = []
    for anchor in soup.find_all("a", href=True):
        epub_type = str(anchor.attrs.get("epub:type", ""))
        role = str(anchor.attrs.get("role", ""))
        classes = " ".join(anchor.attrs.get("class", []))
        if (
            "noteref" not in epub_type
            and "doc-noteref" not in role
            and "noteref" not in classes
            and "footnote" not in classes
        ):
            continue
        resource = _resolved_resource(owner, str(anchor["href"]))
        if resource != owner and resource not in result:
            result.append(resource)
    return result


def _update_navigation_documents(
    temp: Path,
    package: ET.Element,
    opf_path: str,
    labels: dict[str, str],
) -> None:
    base = posixpath.dirname(opf_path)
    for item in package.findall(".//opf:manifest/opf:item", OPF_NS):
        href = item.attrib.get("href", "")
        media_type = item.attrib.get("media-type", "")
        properties = item.attrib.get("properties", "").split()
        if not href or ("nav" not in properties and media_type != "application/x-dtbncx+xml"):
            continue
        owner = posixpath.normpath(posixpath.join(base, href))
        path = temp / Path(owner)
        if not path.is_file():
            continue
        soup = BeautifulSoup(path.read_bytes(), "lxml-xml")
        if "nav" in properties:
            for anchor in soup.find_all("a", href=True):
                label = labels.get(_navigation_target(owner, str(anchor["href"])))
                if label:
                    anchor.clear()
                    anchor.append(label)
        else:
            for point in soup.find_all("navPoint"):
                content = point.find("content", src=True, recursive=False)
                nav_label = point.find("navLabel", recursive=False)
                text = nav_label.find("text") if nav_label else None
                if content is None or text is None:
                    continue
                label = labels.get(_navigation_target(owner, str(content["src"])))
                if label:
                    text.string = label
        path.write_bytes(str(soup).encode("utf-8"))


def _package_info(archive: zipfile.ZipFile) -> tuple[str, ET.Element, str]:
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    rootfile = container.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise ValueError("EPUB 缺少有效的 OPF 包路径")
    opf_path = rootfile.attrib["full-path"]
    return opf_path, ET.fromstring(archive.read(opf_path)), posixpath.dirname(opf_path)


def parse_epub(path: str, source_lang: str = "auto") -> ParsedBook:
    chapters = []
    linked_notes: list[str] = []
    processed_resources: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        opf_path, package, base = _package_info(archive)
        del opf_path
        title_node = package.find(".//dc:title", OPF_NS)
        author_node = package.find(".//dc:creator", OPF_NS)
        language_node = package.find(".//dc:language", OPF_NS)
        title = (
            title_node.text.strip()
            if title_node is not None and title_node.text
            else Path(path).stem
        )
        author = author_node.text.strip() if author_node is not None and author_node.text else ""
        detected_lang = source_lang
        if source_lang == "auto" and language_node is not None and language_node.text:
            detected_lang = language_node.text.strip()
        manifest = {
            item.attrib.get("id", ""): item.attrib
            for item in package.findall(".//opf:manifest/opf:item", OPF_NS)
        }
        spine_ids = [
            item.attrib.get("idref", "")
            for item in package.findall(".//opf:spine/opf:itemref", OPF_NS)
        ]
        for chapter_index, item_id in enumerate(spine_ids):
            item = manifest.get(item_id, {})
            href = item.get("href")
            media = item.get("media-type", "")
            if not href or media not in {"application/xhtml+xml", "text/html"}:
                continue
            resource = posixpath.normpath(posixpath.join(base, href))
            try:
                data = archive.read(resource)
            except KeyError as exc:
                raise FolioCrossError(
                    "epub_spine_resource_missing", f"EPUB 书脊引用的正文不存在：{resource}"
                ) from exc
            processed_resources.add(resource)
            for note_resource in _linked_note_resources(data, resource):
                if note_resource not in linked_notes:
                    linked_notes.append(note_resource)
            chapter = extract_html_chapter(
                data, resource=resource, chapter_index=len(chapters), parser="lxml-xml"
            )
            if chapter:
                chapters.append(chapter)
        for resource in linked_notes:
            if resource in processed_resources:
                continue
            try:
                data = archive.read(resource)
            except KeyError as exc:
                raise FolioCrossError(
                    "epub_note_resource_missing", f"EPUB 脚注引用的正文不存在：{resource}"
                ) from exc
            processed_resources.add(resource)
            chapter = extract_html_chapter(
                data, resource=resource, chapter_index=len(chapters), parser="lxml-xml"
            )
            if chapter:
                chapters.append(chapter)
    if not chapters:
        raise ValueError("EPUB 中没有可翻译正文")
    return ParsedBook(
        title,
        author,
        "epub",
        detected_lang,
        chapters,
        {"template_path": str(Path(path).resolve()), "extraction_version": 2},
    )


def export_epub_template(
    source_path: str,
    output_path: str,
    segments: Iterable[dict],
    *,
    target_lang: str = "zh-CN",
    bilingual: bool = False,
) -> str:
    by_resource: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    navigation_labels: dict[str, str] = {}
    for segment in segments:
        locator = segment.get("locator") or {}
        resource = str(locator.get("resource", ""))
        if not resource or "ordinal" not in locator:
            raise FolioCrossError("epub_mapping_incomplete", "有段落缺少有效的 EPUB 原位定位信息。")
        by_resource[resource][int(locator["ordinal"])].append(segment)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with (
        zipfile.ZipFile(source_path) as source,
        tempfile.TemporaryDirectory(prefix="foliocross-epub-") as temp_dir,
    ):
        temp = Path(temp_dir)
        source.extractall(temp)
        for resource, groups in by_resource.items():
            resource_path = temp / Path(resource)
            if not resource_path.is_file():
                raise FolioCrossError("epub_mapping_incomplete", f"EPUB 正文资源已丢失：{resource}")
            soup = BeautifulSoup(resource_path.read_bytes(), "lxml-xml")
            blocks = content_blocks(soup)
            for ordinal, parts in sorted(groups.items()):
                if ordinal < 0 or ordinal >= len(blocks):
                    raise FolioCrossError(
                        "epub_mapping_incomplete",
                        f"EPUB 正文定位已失效：{resource} 中没有第 {ordinal + 1} 个段落。",
                    )
                parts.sort(key=lambda item: int(item["locator"].get("logical_part", 0)))
                target = "".join(item["target_text"] or item["source_text"] for item in parts)
                source_text = "".join(item["source_text"] for item in parts)
                fresh_source, _ = serialize_block(
                    blocks[ordinal],
                    identity=parts[0]["locator"].get("marker_identity", f"{resource}:{ordinal}"),
                )
                if fresh_source != source_text:
                    raise FolioCrossError(
                        "epub_source_changed",
                        f"EPUB 正文与导入状态不一致：{resource} 第 {ordinal + 1} 个段落已变化。",
                    )
                if bilingual:
                    target = f"{target}\n{source_text}"
                markers = [marker for item in parts for marker in item["markers"]]
                block = blocks[ordinal]
                label = _navigation_label(parts)
                # IDs may be on a heading, an inline anchor or its containing
                # section. The first translated block owns a container label.
                for node in [block, *block.find_all(True), *block.parents]:
                    anchor_id = node.get("id") or node.get("name")
                    if anchor_id:
                        navigation_labels.setdefault(f"{resource}#{anchor_id}", label)
                replace_block_contents(blocks[ordinal], target, markers)
                if (
                    block.name in {"h1", "h2", "h3", "h4", "h5", "h6"}
                    and resource not in navigation_labels
                ):
                    navigation_labels[resource] = label
                    title = soup.find("title")
                    if title is not None:
                        title.string = navigation_labels[resource]
            remove_internal_wrappers(soup)
            resource_path.write_bytes(str(soup).encode("utf-8"))

        container_path = temp / "META-INF" / "container.xml"
        if container_path.is_file():
            container = ET.parse(container_path)
            rootfile = container.getroot().find(".//c:rootfile", CONTAINER_NS)
            if rootfile is not None:
                opf = temp / Path(rootfile.attrib["full-path"])
                if opf.is_file():
                    tree = ET.parse(opf)
                    language = tree.getroot().find(".//dc:language", OPF_NS)
                    if language is not None:
                        language.text = target_lang
                    _update_navigation_documents(
                        temp,
                        tree.getroot(),
                        rootfile.attrib["full-path"],
                        navigation_labels,
                    )
                    tree.write(opf, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(output_path, "w") as target:
            mimetype = temp / "mimetype"
            if mimetype.is_file():
                target.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
            for file in sorted(temp.rglob("*")):
                if not file.is_file() or file == mimetype:
                    continue
                target.write(
                    file, file.relative_to(temp).as_posix(), compress_type=zipfile.ZIP_DEFLATED
                )
    return output_path
