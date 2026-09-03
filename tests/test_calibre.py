import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import write_sample_epub

from foliocross.errors import FolioCrossError
from foliocross.infrastructure.formats import calibre


def test_find_calibre_reports_a_clear_error_when_no_candidate_exists(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    with pytest.raises(FolioCrossError) as caught:
        calibre.find_ebook_convert(r"D:\missing\ebook-convert.exe")
    assert caught.value.code == "calibre_missing"


def test_convert_uses_valid_cache_without_starting_calibre(tmp_path: Path, monkeypatch):
    target = write_sample_epub(tmp_path / "cached.epub")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("should not run"))
    assert calibre.convert_to_epub(str(tmp_path / "book.mobi"), str(target)) == str(target)


def test_convert_accepts_a_valid_calibre_result(tmp_path: Path, monkeypatch):
    executable = tmp_path / "ebook-convert.exe"
    executable.write_bytes(b"test")
    source = tmp_path / "book.mobi"
    source.write_bytes(b"synthetic")
    target = tmp_path / "normalized.epub"

    def fake_run(command, **kwargs):
        del kwargs
        write_sample_epub(Path(command[2]))
        return SimpleNamespace(returncode=0, stdout="converted")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert calibre.convert_to_epub(str(source), str(target), executable=str(executable)) == str(
        target
    )
    assert target.is_file()


@pytest.mark.parametrize(
    ("runner", "expected_code"),
    [
        (
            lambda command, **kwargs: SimpleNamespace(
                returncode=1, stdout="Cannot convert: locked by DRM"
            ),
            "ebook_drm",
        ),
        (
            lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="bad output"),
            "calibre_failed",
        ),
    ],
)
def test_convert_reports_drm_and_invalid_output(
    tmp_path: Path, monkeypatch, runner, expected_code: str
):
    executable = tmp_path / "ebook-convert.exe"
    executable.write_bytes(b"test")
    source = tmp_path / "book.mobi"
    source.write_bytes(b"synthetic")
    monkeypatch.setattr(subprocess, "run", runner)
    with pytest.raises(FolioCrossError) as caught:
        calibre.convert_to_epub(
            str(source), str(tmp_path / "normalized.epub"), executable=str(executable)
        )
    assert caught.value.code == expected_code


def test_convert_reports_timeout(tmp_path: Path, monkeypatch):
    executable = tmp_path / "ebook-convert.exe"
    executable.write_bytes(b"test")
    source = tmp_path / "book.mobi"
    source.write_bytes(b"synthetic")

    def timeout(command, **kwargs):
        del kwargs
        raise subprocess.TimeoutExpired(command, 3)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(FolioCrossError) as caught:
        calibre.convert_to_epub(
            str(source), str(tmp_path / "normalized.epub"), executable=str(executable), timeout=3
        )
    assert caught.value.code == "calibre_timeout"
