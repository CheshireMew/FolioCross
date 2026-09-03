from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from foliocross.infrastructure.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    value = Workspace(tmp_path / "workspace")
    value.initialize()
    return value


def write_sample_epub(path: Path) -> Path:
    container = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">sample</dc:identifier>
<dc:title>Sample Book</dc:title><dc:creator>Tester</dc:creator><dc:language>en</dc:language></metadata>
<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>
<item id="css" href="style.css" media-type="text/css"/><item id="img" href="cover.png" media-type="image/png"/></manifest>
<spine><itemref idref="c1"/></spine></package>"""
    chapter = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head>
<title>One</title><link rel="stylesheet" href="style.css"/></head><body>
<h1 id="chapter-one">Chapter One</h1><p>This is <em>important</em> text<a epub:type="noteref" href="#n1">1</a>.</p>
<aside id="n1" epub:type="footnote"><p>A useful note.</p></aside><p><img src="cover.png" alt="cover"/>After image.</p>
</body></html>"""
    nav = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<nav epub:type="toc"><ol><li><a href="chapter.xhtml#chapter-one">One</a></li></ol></nav></body></html>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/chapter.xhtml", chapter)
        archive.writestr("OEBPS/nav.xhtml", nav)
        archive.writestr("OEBPS/style.css", "p { color: #222; }")
        archive.writestr("OEBPS/cover.png", b"not-a-real-png")
    return path
