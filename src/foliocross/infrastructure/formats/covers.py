"""Cover extraction from package formats without altering the source document."""

from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from .epub import OPF_NS, _package_info

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}


def _write_cover(archive: zipfile.ZipFile, member: str, output_dir: Path) -> str | None:
    suffix = PurePosixPath(member).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        return None
    target = output_dir / f"cover{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(archive.read(member))
    return str(target)


def _epub_cover(source: Path, output_dir: Path) -> str | None:
    with zipfile.ZipFile(source) as archive:
        _opf_path, package, base = _package_info(archive)
        manifest = {
            item.attrib.get("id", ""): item.attrib
            for item in package.findall(".//opf:manifest/opf:item", OPF_NS)
        }
        candidate = next(
            (
                item
                for item in manifest.values()
                if "cover-image" in item.get("properties", "").split()
            ),
            None,
        )
        if candidate is None:
            cover_id = ""
            for meta in package.findall(".//opf:metadata/opf:meta", OPF_NS):
                if meta.attrib.get("name", "").casefold() == "cover":
                    cover_id = meta.attrib.get("content", "")
                    break
            candidate = manifest.get(cover_id)
        if candidate is None:
            candidate = next(
                (
                    item
                    for item in manifest.values()
                    if item.get("media-type", "").startswith("image/")
                    and "cover" in item.get("href", "").casefold()
                ),
                None,
            )
        href = candidate.get("href") if candidate else None
        if not href:
            return None
        member = posixpath.normpath(posixpath.join(base, href))
        if member not in archive.namelist():
            return None
        return _write_cover(archive, member, output_dir)


def _docx_cover(source: Path, output_dir: Path) -> str | None:
    with zipfile.ZipFile(source) as archive:
        member = next(
            (
                name
                for name in archive.namelist()
                if name.startswith("word/media/")
                and PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES
            ),
            None,
        )
        return _write_cover(archive, member, output_dir) if member else None


def extract_cover(source_path: str, source_format: str, output_dir: str | Path) -> str | None:
    source = Path(source_path)
    try:
        if source_format == "epub":
            return _epub_cover(source, Path(output_dir))
        if source_format == "docx":
            return _docx_cover(source, Path(output_dir))
    except (ET.ParseError, KeyError, OSError, zipfile.BadZipFile):
        return None
    return None
