"""Pluggable Kindle conversion with KindleUnpack first and Calibre fallback."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ...errors import FolioCrossError
from .calibre import convert_to_epub, find_ebook_convert, valid_epub

KINDLE_FORMATS = {".mobi", ".azw", ".azw3", ".azw4", ".prc"}
KINDLEUNPACK_ENV = "FOLIOCROSS_KINDLEUNPACK_PYTHON"


@dataclass(slots=True)
class ConversionResult:
    path: str
    backend: str
    backend_path: str
    attempts: list[dict[str, str]]


def is_kindle_format(path: str) -> bool:
    return Path(path).suffix.lower() in KINDLE_FORMATS


def find_kindleunpack_python(configured: str | None = None) -> str:
    candidates = [
        configured,
        os.environ.get(KINDLEUNPACK_ENV),
        r"D:\Tools\venvs\FolioCross-KindleUnpack\Scripts\python.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FolioCrossError(
        "kindleunpack_missing",
        "没有找到独立 KindleUnpack 环境；仍可安装 Calibre 作为 Kindle 格式转换后端。",
    )


def package_extracted_epub(content_path: str, target_path: str) -> str:
    content = Path(content_path).resolve()
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if content.suffix.lower() == ".epub" and valid_epub(content):
        shutil.copy2(content, target)
        return str(target)
    if content.suffix.lower() not in {".html", ".htm", ".xhtml"}:
        raise FolioCrossError(
            "kindleunpack_output_unsupported",
            f"KindleUnpack 生成了暂不支持的内容：{content.suffix or content.name}",
        )
    root = content.parent
    opf = root / "content.opf"
    if not opf.is_file():
        candidates = list(root.glob("*.opf"))
        opf = candidates[0] if candidates else opf
    if not opf.is_file():
        raise FolioCrossError("kindleunpack_output_invalid", "KindleUnpack 输出缺少 OPF 包文件。")
    container = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        f'<rootfiles><rootfile full-path="OEBPS/{opf.name}" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        for file in sorted(root.rglob("*")):
            if file.is_file():
                archive.write(
                    file,
                    f"OEBPS/{file.relative_to(root).as_posix()}",
                    compress_type=zipfile.ZIP_DEFLATED,
                )
    if not valid_epub(target):
        raise FolioCrossError(
            "kindleunpack_output_invalid", "KindleUnpack 输出未能规范化为有效 EPUB。"
        )
    return str(target)


def convert_with_kindleunpack(
    source_path: str,
    target_path: str,
    *,
    python_executable: str | None = None,
    timeout: int = 600,
) -> str:
    if valid_epub(Path(target_path)):
        return target_path
    executable = find_kindleunpack_python(python_executable)
    bridge = Path(__file__).with_name("kindleunpack_bridge.py")
    scratch = Path(target_path).parent / "kindleunpack-cache"
    scratch.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["TEMP"] = str(scratch)
    environment["TMP"] = str(scratch)
    try:
        process = subprocess.run(
            [executable, str(bridge), str(Path(source_path).resolve())],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise FolioCrossError(
            "kindleunpack_timeout", f"KindleUnpack 转换超过 {timeout} 秒。"
        ) from error
    output = process.stdout.strip()
    if process.returncode != 0:
        is_drm = "drm" in output.lower() or "encrypted" in output.lower()
        code = "ebook_drm" if is_drm else "kindleunpack_failed"
        message = (
            "文件可能带有 DRM，FolioCross 不支持移除 DRM。"
            if is_drm
            else f"KindleUnpack 转换失败：{output[-1600:]}"
        )
        raise FolioCrossError(code, message)
    try:
        payload = json.loads(output.splitlines()[-1])
        content_path = str(payload["content_path"])
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise FolioCrossError(
            "kindleunpack_output_invalid", "KindleUnpack 没有返回可识别的转换结果。"
        ) from error
    return package_extracted_epub(content_path, target_path)


def convert_kindle_to_epub(
    source_path: str,
    target_path: str,
    *,
    kindleunpack_python: str | None = None,
    calibre_executable: str | None = None,
    timeout: int = 600,
) -> ConversionResult:
    """Try independent KindleUnpack first, then optional Calibre compatibility fallback."""

    if valid_epub(Path(target_path)):
        return ConversionResult(target_path, "cache", "", [])
    attempts: list[dict[str, str]] = []
    try:
        executable = find_kindleunpack_python(kindleunpack_python)
        path = convert_with_kindleunpack(
            source_path, target_path, python_executable=executable, timeout=timeout
        )
        return ConversionResult(path, "kindleunpack", executable, attempts)
    except FolioCrossError as error:
        if error.code == "ebook_drm":
            raise
        attempts.append({"backend": "kindleunpack", "code": error.code, "message": error.message})
    try:
        executable = find_ebook_convert(calibre_executable)
        path = convert_to_epub(source_path, target_path, executable=executable, timeout=timeout)
        return ConversionResult(path, "calibre", executable, attempts)
    except FolioCrossError as error:
        if error.code == "ebook_drm":
            raise
        attempts.append({"backend": "calibre", "code": error.code, "message": error.message})
    raise FolioCrossError(
        "kindle_conversion_unavailable",
        "没有可用的 Kindle 格式转换后端，或所有后端均转换失败。可安装独立 KindleUnpack 或 Calibre。",
        details={"attempts": attempts},
    )
