import zipfile
from dataclasses import asdict

from bs4 import BeautifulSoup
from conftest import write_sample_epub

from foliocross.infrastructure.formats.epub import export_epub_template, parse_epub
from foliocross.infrastructure.formats.htmlish import fill_html_template, parse_html


def test_existing_book_adds_omitted_prose_without_changing_manual_revision(
    workspace, tmp_path, monkeypatch
):
    import json

    from foliocross.application.service import FolioCrossService
    from foliocross.domain.models import JobConfig, ModelProfile
    from foliocross.infrastructure.formats import htmlish
    from foliocross.worker.engine import WorkerEngine

    source = tmp_path / "legacy.html"
    source.write_text(
        "<html><body><h1>Title</h1><div>Previously omitted.</div><p>Keep <em>my</em> edit.</p></body></html>",
        encoding="utf-8",
    )
    service = FolioCrossService(workspace)
    old_selector = "h1,h2,h3,h4,h5,h6,p,li,blockquote,figcaption,td,th"
    with monkeypatch.context() as patch:
        patch.setattr(htmlish, "BLOCK_SELECTOR", old_selector)
        patch.setattr(htmlish, "BLOCK_NAMES", set(old_selector.split(",")))
        imported = service.import_book(
            str(source), JobConfig(profile=ModelProfile(provider="fake"))
        )
    job_id = imported["job_id"]
    chapter = service.repository.chapters_for_job(job_id)[0]
    original = service.repository.segments_for_chapter(chapter["id"])[1]
    service.edit_segment(original["id"], original["source_text"].replace("Keep", "Preserve"))
    revision = service.repository.segment_revisions(original["id"])
    with workspace.transaction(immediate=True) as connection:
        metadata = service.repository.get_book(imported["book_id"])["metadata"]
        metadata.pop("extraction_version")
        connection.execute(
            "UPDATE books SET metadata_json=? WHERE id=?",
            (json.dumps(metadata), imported["book_id"]),
        )
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    assert service.repository.get_job(job_id)["total_segments"] == 3
    assert service.repository.segment_revisions(original["id"]) == revision
    rows = service.repository.segments_for_chapter(chapter["id"])
    assert rows[2]["id"] == original["id"]
    assert rows[2]["locked"]
    exported = service.export(job_id, "html")
    from pathlib import Path

    result = BeautifulSoup(Path(exported["path"]).read_text(encoding="utf-8"), "html.parser")
    assert "Preserve" in result.p.get_text()
    assert result.p.em.get_text() == "my"
    assert result.div.get_text() != "Previously omitted."


def test_mixed_html_prose_round_trip(tmp_path):
    source = tmp_path / "mixed.html"
    source.write_text(
        "<html><body><h1>Title</h1><div>Outside <em>text</em>."
        "<section>Nested.</section>Tail.</div><p>Paragraph.</p>Body tail.</body></html>",
        encoding="utf-8",
    )
    parsed = parse_html(str(source))
    rows = [
        asdict(segment) | {"target_text": segment.source_text.replace("Outside", "Translated")}
        for segment in parsed.chapters[0].segments
    ]
    visible = [
        BeautifulSoup(s.source_text, "html.parser").get_text() for s in parsed.chapters[0].segments
    ]
    assert len(rows) == 6
    assert sum("Nested." in text for text in visible) == 1
    assert sum("Tail." in text for text in visible) == 1
    target = tmp_path / "result.html"
    fill_html_template(str(source), str(target), rows)
    soup = BeautifulSoup(target.read_text(encoding="utf-8"), "html.parser")
    assert "Translated" in soup.get_text()
    assert soup.em.get_text() == "text"
    assert "data-foliocross-direct" not in str(soup)


def test_mixed_epub_completes_through_worker_and_both_exports(workspace, tmp_path):
    from pathlib import Path

    from foliocross.application.service import FolioCrossService
    from foliocross.domain.models import JobConfig, ModelProfile
    from foliocross.worker.engine import WorkerEngine

    original = write_sample_epub(tmp_path / "original.epub")
    source = tmp_path / "mixed.epub"
    with zipfile.ZipFile(original) as archive, zipfile.ZipFile(source, "w") as output:
        for info in archive.infolist():
            data = archive.read(info)
            if info.filename.endswith("chapter.xhtml"):
                data = data.replace(
                    b"</body>",
                    b"<div>Extra prose.</div><section>Final prose.</section><script>not_prose()</script></body>",
                )
            output.writestr(info, data)
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), JobConfig(profile=ModelProfile(provider="fake")))[
        "job_id"
    ]
    WorkerEngine(workspace).run(job_id, export_when_done=False)
    exported = service.export(job_id, "epub")
    text = service.export(job_id, "txt")
    with zipfile.ZipFile(exported["path"]) as archive:
        chapter = BeautifulSoup(archive.read("OEBPS/chapter.xhtml"), "xml")
        assert chapter.div.get_text() != "Extra prose."
        assert chapter.section.get_text() != "Final prose."
        assert chapter.script.get_text() == "not_prose()"
    visible = Path(text["path"]).read_text(encoding="utf-8")
    assert chapter.div.get_text() in visible and chapter.section.get_text() in visible
    assert "not_prose()" not in visible


def test_epub_distinct_fragment_labels_and_document_title(tmp_path):
    original = write_sample_epub(tmp_path / "original.epub")
    source = tmp_path / "headings.epub"
    with zipfile.ZipFile(original) as archive, zipfile.ZipFile(source, "w") as output:
        for info in archive.infolist():
            data = archive.read(info)
            if info.filename.endswith("chapter.xhtml"):
                data = data.replace(
                    b"</body>", b'<h2 id="second">Second</h2><div>Extra prose</div></body>'
                )
            if info.filename.endswith("nav.xhtml"):
                data = data.replace(
                    b"</ol>", b'<li><a href="chapter.xhtml#second">Second</a></li></ol>'
                )
            if info.filename.endswith("content.opf"):
                data = data.replace(
                    b"</manifest>",
                    b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
                )
            output.writestr(info, data)
        output.writestr(
            "OEBPS/toc.ncx",
            '<ncx><navMap><navPoint><navLabel><text>One</text></navLabel><content src="chapter.xhtml#chapter-one"/><navPoint><navLabel><text>Second</text></navLabel><content src="chapter.xhtml#second"/></navPoint></navPoint></navMap></ncx>',
        )
    parsed = parse_epub(str(source))
    rows = [
        asdict(s)
        | {
            "target_text": {
                "Chapter One": "First translated",
                "Second": "Second translated",
                "Extra prose": "Extra translated",
            }.get(s.source_text, s.source_text)
        }
        for ch in parsed.chapters
        for s in ch.segments
    ]
    target = tmp_path / "result.epub"
    export_epub_template(str(source), str(target), rows)
    with zipfile.ZipFile(target) as archive:
        nav = BeautifulSoup(archive.read("OEBPS/nav.xhtml"), "xml")
        assert [a.get_text() for a in nav.find_all("a")] == [
            "First translated",
            "Second translated",
        ]
        ncx = BeautifulSoup(archive.read("OEBPS/toc.ncx"), "xml")
        assert [a.get_text() for a in ncx.find_all("text")] == [
            "First translated",
            "Second translated",
        ]
        chapter = BeautifulSoup(archive.read("OEBPS/chapter.xhtml"), "xml")
        assert chapter.title.get_text() == "First translated"
        assert chapter.find("div").get_text() == "Extra translated"
        assert chapter.find(id="second") is not None
