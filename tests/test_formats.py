from __future__ import annotations

import zipfile
from pathlib import Path

from conftest import write_sample_epub
from docx import Document

from foliocross.infrastructure.formats.docx import export_docx_template, parse_docx
from foliocross.infrastructure.formats.epub import export_epub_template, parse_epub
from foliocross.infrastructure.formats.fb2 import parse_fb2
from foliocross.infrastructure.formats.htmlish import parse_html
from foliocross.infrastructure.formats.markers import validate_markers
from foliocross.infrastructure.formats.text import parse_text


def test_epub_parser_preserves_inline_and_note_markers(tmp_path: Path):
    source = write_sample_epub(tmp_path / "book.epub")
    book = parse_epub(str(source))
    assert book.title == "Sample Book"
    assert book.author == "Tester"
    assert book.source_lang == "en"
    marker_segments = [
        segment for chapter in book.chapters for segment in chapter.segments if segment.markers
    ]
    assert marker_segments
    kinds = {marker["kind"] for segment in marker_segments for marker in segment.markers}
    assert {"annotation", "tag_start", "tag_end", "inline_atom"} <= kinds


def test_epub_template_export_keeps_resources_and_restores_markup(tmp_path: Path):
    source = write_sample_epub(tmp_path / "book.epub")
    book = parse_epub(str(source))
    segments = []
    for chapter in book.chapters:
        for index, draft in enumerate(chapter.segments):
            segments.append(
                {
                    "source_text": draft.source_text,
                    "target_text": "译文" + draft.source_text,
                    "locator": draft.locator,
                    "markers": draft.markers,
                    "segment_index": index,
                }
            )
    output = tmp_path / "translated.epub"
    export_epub_template(str(source), str(output), segments)
    with zipfile.ZipFile(output) as archive:
        assert "OEBPS/style.css" in archive.namelist()
        assert "OEBPS/cover.png" in archive.namelist()
        content = archive.read("OEBPS/chapter.xhtml").decode("utf-8")
        assert "⟦FC:" not in content
        assert 'href="#n1"' in content
        assert "<em>important</em>" in content
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert "zh-CN" in opf


def test_marker_validator_detects_loss(tmp_path: Path):
    source = write_sample_epub(tmp_path / "book.epub")
    book = parse_epub(str(source))
    segment = next(s for c in book.chapters for s in c.segments if s.markers)
    assert validate_markers(segment.source_text, segment.markers) == []
    missing = segment.source_text.replace(segment.markers[0]["token"], "")
    assert validate_markers(missing, segment.markers)


def test_text_parser_splits_headings(tmp_path: Path):
    path = tmp_path / "book.md"
    path.write_text("# One\n\nFirst.\n\n# Two\n\nSecond.", encoding="utf-8")
    book = parse_text(str(path))
    assert [chapter.title for chapter in book.chapters] == ["One", "Two"]


def test_html_and_fb2_are_mapped_to_chapters_and_segments(tmp_path: Path):
    html_path = tmp_path / "book.html"
    html_path.write_text(
        "<html><head><title>HTML Book</title></head><body><h1>One</h1><p>Paragraph.</p></body></html>",
        encoding="utf-8",
    )
    html_book = parse_html(str(html_path))
    assert html_book.title == "HTML Book"
    assert any(segment.source_text == "Paragraph." for segment in html_book.chapters[0].segments)

    fb2_path = tmp_path / "book.fb2"
    fb2_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
        <FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
        <description><title-info><book-title>FB2 Book</book-title><author><first-name>A</first-name>
        <last-name>Writer</last-name></author></title-info></description>
        <body><section><title><p>Chapter</p></title><p>First text.</p><p>Second text.</p></section></body>
        </FictionBook>""",
        encoding="utf-8",
    )
    fb2_book = parse_fb2(str(fb2_path))
    assert fb2_book.title == "FB2 Book"
    assert fb2_book.chapters[0].title == "Chapter"
    assert len(fb2_book.chapters[0].segments) == 2


def test_docx_template_keeps_structure_and_replaces_text(tmp_path: Path):
    source = tmp_path / "book.docx"
    document = Document()
    document.add_heading("Heading", 1)
    paragraph = document.add_paragraph()
    bold = paragraph.add_run("Bold")
    bold.bold = True
    paragraph.add_run(" normal")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Cell text"
    document.save(source)
    book = parse_docx(str(source))
    drafts = [segment for chapter in book.chapters for segment in chapter.segments]
    rows = [
        {"source_text": item.source_text, "target_text": f"译文{index}", "locator": item.locator}
        for index, item in enumerate(drafts)
    ]
    output = tmp_path / "translated.docx"
    export_docx_template(str(source), str(output), rows)
    translated = Document(output)
    assert translated.paragraphs[0].text == "译文0"
    assert translated.paragraphs[1].text == "译文1"
    assert translated.paragraphs[1].runs[0].bold is True
    assert translated.tables[0].cell(0, 0).text == "译文2"
