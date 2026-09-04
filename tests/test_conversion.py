from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from foliocross.errors import FolioCrossError
from foliocross.infrastructure.formats import conversion


def test_package_kindleunpack_mobi7_output_as_epub(tmp_path: Path):
    extracted = tmp_path / "mobi7"
    extracted.mkdir()
    (extracted / "book.html").write_text(
        "<html><body><p>Readable content.</p></body></html>", encoding="utf-8"
    )
    (extracted / "content.opf").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>
<dc:title>Native</dc:title><dc:language>en</dc:language></metadata>
<manifest><item id="body" href="book.html" media-type="text/html"/></manifest>
<spine><itemref idref="body"/></spine></package>""",
        encoding="utf-8",
    )
    target = tmp_path / "normalized.epub"
    conversion.package_extracted_epub(str(extracted / "book.html"), str(target))
    with zipfile.ZipFile(target) as archive:
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "OEBPS/book.html" in archive.namelist()
        assert b"OEBPS/content.opf" in archive.read("META-INF/container.xml")


def test_kindleunpack_bridge_result_is_normalized(tmp_path: Path, monkeypatch):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"stub")
    source = tmp_path / "book.mobi"
    source.write_bytes(b"mobi")
    extracted = tmp_path / "out"
    extracted.mkdir()
    content = extracted / "book.html"
    content.write_text("<html><body><p>Body.</p></body></html>", encoding="utf-8")
    (extracted / "content.opf").write_text(
        """<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
<metadata/><manifest><item id="b" href="book.html" media-type="text/html"/></manifest>
<spine><itemref idref="b"/></spine></package>""",
        encoding="utf-8",
    )

    def run(*args, **kwargs):
        del args, kwargs
        payload = {"ok": True, "extraction_dir": str(extracted), "content_path": str(content)}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(conversion.subprocess, "run", run)
    target = tmp_path / "book.epub"
    result = conversion.convert_with_kindleunpack(
        str(source), str(target), python_executable=str(executable)
    )
    assert result == str(target)
    assert conversion.valid_epub(target)


def test_calibre_is_only_a_fallback(tmp_path: Path, monkeypatch):
    source = tmp_path / "book.azw3"
    target = tmp_path / "book.epub"
    source.write_bytes(b"test")
    monkeypatch.setattr(conversion, "find_kindleunpack_python", lambda configured=None: "ku")
    monkeypatch.setattr(
        conversion,
        "convert_with_kindleunpack",
        lambda *args, **kwargs: str(target),
    )
    monkeypatch.setattr(
        conversion,
        "find_ebook_convert",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Calibre should not run")),
    )
    result = conversion.convert_kindle_to_epub(str(source), str(target))
    assert result.backend == "kindleunpack"


def test_all_kindle_backends_fail_with_actionable_attempts(tmp_path: Path, monkeypatch):
    source = tmp_path / "broken.mobi"
    target = tmp_path / "broken.epub"
    source.write_bytes(b"broken")

    def fail_kindleunpack(configured=None):
        del configured
        raise FolioCrossError("kindleunpack_missing", "missing")

    def fail_calibre(configured=None):
        del configured
        raise FolioCrossError("calibre_missing", "missing")

    monkeypatch.setattr(conversion, "find_kindleunpack_python", fail_kindleunpack)
    monkeypatch.setattr(conversion, "find_ebook_convert", fail_calibre)
    with pytest.raises(FolioCrossError) as captured:
        conversion.convert_kindle_to_epub(str(source), str(target))
    assert captured.value.code == "kindle_conversion_unavailable"
    assert [item["backend"] for item in captured.value.details["attempts"]] == [
        "kindleunpack",
        "calibre",
    ]
