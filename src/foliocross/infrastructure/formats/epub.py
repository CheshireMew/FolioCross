"""EPUB parser and template-preserving exporter."""

from __future__ import annotations

import posixpath
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from ...domain.models import ParsedBook
from .htmlish import content_blocks, extract_html_chapter
from .markers import replace_block_contents

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}


def _package_info(archive: zipfile.ZipFile) -> tuple[str, ET.Element, str]:
    container = ET.fromstring(archive.read("META-INF/container.xml"))
    rootfile = container.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise ValueError("EPUB 缺少有效的 OPF 包路径")
    opf_path = rootfile.attrib["full-path"]
    return opf_path, ET.fromstring(archive.read(opf_path)), posixpath.dirname(opf_path)


def parse_epub(path: str, source_lang: str = "auto") -> ParsedBook:
    chapters = []
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
            except KeyError:
                continue
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
        {"template_path": str(Path(path).resolve())},
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
    for segment in segments:
        locator = segment["locator"]
        resource = str(locator.get("resource", ""))
        if resource:
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
                continue
            soup = BeautifulSoup(resource_path.read_bytes(), "lxml-xml")
            blocks = content_blocks(soup)
            for ordinal, parts in groups.items():
                if ordinal >= len(blocks):
                    continue
                parts.sort(key=lambda item: int(item["locator"].get("logical_part", 0)))
                target = "".join(item["target_text"] or item["source_text"] for item in parts)
                source_text = "".join(item["source_text"] for item in parts)
                if bilingual:
                    target = f"{target}\n{source_text}"
                markers = [marker for item in parts for marker in item["markers"]]
                replace_block_contents(blocks[ordinal], target, markers)
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
