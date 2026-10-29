from pathlib import Path

import pytest

from foliocross.application.service import FolioCrossService
from foliocross.domain.models import JobConfig
from foliocross.infrastructure.formats import exporters
from foliocross.infrastructure.repository import sha256_file


def translated_book(workspace, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Paragraph", encoding="utf-8")
    service = FolioCrossService(workspace)
    job_id = service.import_book(str(source), JobConfig())["job_id"]
    chapter = service.repository.chapters_for_job(job_id)[0]
    segment = service.repository.segments_for_chapter(chapter["id"])[0]
    service.edit_segment(segment["id"], "Translation one")
    return service, job_id, segment["id"]


@pytest.mark.parametrize("format_name", ["txt", "markdown", "html", "epub", "docx"])
def test_reexport_keeps_artifact_content(workspace, tmp_path, format_name):
    service, job_id, segment_id = translated_book(workspace, tmp_path)
    service.export(job_id, format_name)
    service.edit_segment(segment_id, "Translation two")
    service.export(job_id, format_name)
    artifacts = [a for a in service.repository.list_artifacts(job_id) if a["kind"] == "translation"]
    assert len(artifacts) == 2
    assert len({a["path"] for a in artifacts}) == 2
    assert all(sha256_file(a["path"]) == a["sha256"] for a in artifacts)


@pytest.mark.parametrize(
    "format_name,renderer",
    [
        ("txt", "_write_txt"),
        ("markdown", "_write_txt"),
        ("html", "_write_html"),
        ("epub", "_write_generated_epub"),
        ("docx", "_write_docx"),
    ],
)
def test_failed_explicit_export_preserves_previous_output(
    workspace, tmp_path, monkeypatch, format_name, renderer
):
    service, job_id, _ = translated_book(workspace, tmp_path)
    target = tmp_path / ("chosen." + format_name)
    service.export(job_id, format_name, str(target))
    before = target.read_bytes()

    def interrupted(path, *args, **kwargs):
        Path(path).write_text("partial", encoding="utf-8")
        raise OSError("injected write failure")

    monkeypatch.setattr(exporters, renderer, interrupted)
    with pytest.raises(OSError, match="injected"):
        service.export(job_id, format_name, str(target))
    assert target.read_bytes() == before
    artifacts = [a for a in service.repository.list_artifacts(job_id) if a["kind"] == "translation"]
    assert len(artifacts) == 1
    assert sha256_file(artifacts[0]["path"]) == artifacts[0]["sha256"]


def test_publication_recovers_after_file_replace_before_database_commit(
    workspace, tmp_path, monkeypatch
):
    from foliocross.infrastructure.repository import Repository

    service, job_id, _ = translated_book(workspace, tmp_path)
    original_event = service.repository._insert_event

    def fail_receipt(connection, job, event, payload):
        if event == "artifact.published":
            raise RuntimeError("injected crash after file replacement")
        return original_event(connection, job, event, payload)

    monkeypatch.setattr(service.repository, "_insert_event", fail_receipt)
    target = tmp_path / "delivered.txt"
    with pytest.raises(RuntimeError, match="injected"):
        service.export(job_id, "txt", str(target))
    assert target.is_file()
    assert not [a for a in service.repository.list_artifacts(job_id) if a["kind"] == "translation"]
    reopened = Repository(workspace)
    artifacts = [a for a in reopened.list_artifacts(job_id) if a["kind"] == "translation"]
    assert len(artifacts) == 1
    assert Path(artifacts[0]["path"]).read_bytes() == target.read_bytes()
    assert sha256_file(artifacts[0]["path"]) == artifacts[0]["sha256"]
    Repository(workspace)
    assert len(reopened.list_artifacts(job_id)) == 2  # source plus one publication
