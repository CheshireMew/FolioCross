"""External Calibre ebook-convert discovery and conversion."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from ...errors import FolioCrossError

CALIBRE_INPUT_EXTENSIONS = frozenset(
    {
        ".azw",
        ".azw1",
        ".azw3",
        ".azw4",
        ".chm",
        ".htmlz",
        ".lit",
        ".lrf",
        ".mobi",
        ".odt",
        ".pdb",
        ".pml",
        ".pmlz",
        ".prc",
        ".rb",
        ".rtf",
        ".snb",
        ".tcr",
        ".txtz",
    }
)


def is_convertible(path: str) -> bool:
    return Path(path).suffix.lower() in CALIBRE_INPUT_EXTENSIONS


def find_ebook_convert(configured_path: str | None = None) -> str:
    candidates: list[Path] = []
    for raw in (
        configured_path,
        os.environ.get("CALIBRE_EBOOK_CONVERT"),
        shutil.which("ebook-convert"),
        shutil.which("ebook-convert.exe"),
        r"D:\Tools\Calibre\ebook-convert.exe",
        r"D:\Tools\Calibre\Calibre\ebook-convert.exe",
        r"D:\Tools\Calibre\Calibre Portable\Calibre\ebook-convert.exe",
        r"D:\Tools\Calibre Portable\Calibre\ebook-convert.exe",
        r"C:\Program Files\Calibre2\ebook-convert.exe",
    ):
        if not raw:
            continue
        path = Path(os.path.expandvars(str(raw))).expanduser()
        if path.is_dir():
            path = path / ("ebook-convert.exe" if os.name == "nt" else "ebook-convert")
        candidates.append(path)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    raise FolioCrossError(
        "calibre_missing",
        "未找到 Calibre 的 ebook-convert。请把 Calibre 安装到 D:\\Tools\\Calibre，或在设置中指定路径。",
    )


def _valid_epub(path: Path) -> bool:
    if not path.is_file() or not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as archive:
        return "META-INF/container.xml" in archive.namelist()


def convert_to_epub(
    source_path: str,
    output_path: str,
    *,
    executable: str | None = None,
    timeout: float = 900,
) -> str:
    target = Path(output_path)
    if _valid_epub(target):
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part.epub")
    command = [find_ebook_convert(executable), str(Path(source_path).resolve()), str(partial)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
            shell=False,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired as error:
        raise FolioCrossError("calibre_timeout", f"电子书格式转换超过 {timeout:g} 秒。") from error
    output = (result.stdout or "").strip()
    if result.returncode != 0 or not _valid_epub(partial):
        detail = output[-2000:] or "未生成有效 EPUB"
        if re.search(r"\bdrm\b|encrypted|locked", detail, re.IGNORECASE):
            raise FolioCrossError(
                "ebook_drm", "Calibre 无法转换该文件；它可能受 DRM 保护。FolioCross 不移除 DRM。"
            )
        raise FolioCrossError("calibre_failed", f"Calibre 转换失败：{detail}")
    os.replace(partial, target)
    return str(target)
