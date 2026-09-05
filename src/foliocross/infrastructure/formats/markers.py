"""Protected inline and annotation markers used during translation."""

from __future__ import annotations

import hashlib
import html
import re
from difflib import SequenceMatcher
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

MARKER_PATTERN = re.compile(r"⟦FC:[A-Z]+:[0-9a-f]{12}:[SEX]⟧")
INLINE_TAGS = {"a", "b", "cite", "code", "em", "i", "ruby", "span", "strong", "sub", "sup", "u"}
SELF_TAGS = {"br", "img", "svg"}


def _token(kind: str, identity: str, position: str) -> str:
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    return f"⟦FC:{kind.upper()}:{digest}:{position}⟧"


def serialize_block(block: Tag, *, identity: str) -> tuple[str, list[dict[str, Any]]]:
    markers: list[dict[str, Any]] = []
    visible_count = 0

    def walk(node: Any, path: str) -> str:
        nonlocal visible_count
        if isinstance(node, NavigableString):
            value = str(node)
            visible_count += len(value)
            return value
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        marker_identity = f"{identity}:{path}:{name}:{len(markers)}"
        epub_type = str(node.attrs.get("epub:type", ""))
        role = str(node.attrs.get("role", ""))
        classes = " ".join(node.get("class", []))
        is_noteref = name == "a" and (
            "noteref" in epub_type
            or "doc-noteref" in role
            or "noteref" in classes
            or "footnote" in classes
        )
        if name in SELF_TAGS or is_noteref:
            token = _token("NOTE" if is_noteref else "ATOM", marker_identity, "X")
            markers.append(
                {
                    "token": token,
                    "html": str(node),
                    "kind": "annotation" if is_noteref else "inline_atom",
                    "source_offset": visible_count,
                }
            )
            return token
        if name not in INLINE_TAGS:
            return "".join(
                walk(child, f"{path}.{index}") for index, child in enumerate(node.children)
            )
        insertion_index = len(markers)
        start = _token("TAG", marker_identity, "S")
        end = _token("TAG", marker_identity, "E")
        attrs = "".join(
            f' {key}="{html.escape(" ".join(value) if isinstance(value, list) else str(value), quote=True)}"'
            for key, value in node.attrs.items()
        )
        start_marker = {
            "token": start,
            "html": f"<{name}{attrs}>",
            "kind": "tag_start",
            "source_offset": visible_count,
        }
        inner = "".join(walk(child, f"{path}.{index}") for index, child in enumerate(node.children))
        markers.insert(insertion_index, start_marker)
        markers.append(
            {
                "token": end,
                "html": f"</{name}>",
                "kind": "tag_end",
                "source_offset": visible_count,
            }
        )
        return f"{start}{inner}{end}"

    text = "".join(walk(child, str(index)) for index, child in enumerate(block.children))
    text = re.sub(r"[\t\r\f\v ]+", " ", text).strip()
    return text, markers


def expected_tokens(markers: list[dict[str, Any]]) -> list[str]:
    return [str(marker["token"]) for marker in markers]


def validate_markers(text: str, markers: list[dict[str, Any]]) -> list[str]:
    actual = MARKER_PATTERN.findall(text)
    expected = expected_tokens(markers)
    issues: list[str] = []
    if actual != expected:
        missing = [token for token in expected if token not in actual]
        extra = [token for token in actual if token not in expected]
        if missing:
            issues.append(f"缺少 {len(missing)} 个格式或注释标记")
        if extra:
            issues.append(f"出现 {len(extra)} 个未知标记")
        if not missing and not extra:
            issues.append("格式或注释标记顺序发生变化")
    return issues


def strip_protected_markers(text: str) -> str:
    """Return reader-visible text without FolioCross's internal marker tokens."""
    return MARKER_PATTERN.sub("", text)


def restore_protected_markers(
    source: str,
    reference_target: str,
    edited_text: str,
    markers: list[dict[str, Any]],
) -> str:
    """Restore protected markers after a user edits only the visible translation."""
    visible_edit = strip_protected_markers(edited_text)
    if not markers:
        return visible_edit

    source_visible = strip_protected_markers(source)
    reference_visible = strip_protected_markers(reference_target)
    edits = SequenceMatcher(None, reference_visible, visible_edit, autojunk=False).get_opcodes()

    def mapped_offset(offset: int, kind: str) -> int:
        # At an insertion boundary, keep an opening tag with the following text
        # and a closing tag/note with the preceding text.
        for operation, old_start, old_end, new_start, new_end in edits:
            if operation == "insert" and offset == old_start:
                return new_end if kind == "tag_start" else new_start
        for operation, old_start, old_end, new_start, new_end in edits:
            if old_start <= offset <= old_end:
                if operation == "equal":
                    return new_start + offset - old_start
                ratio = (offset - old_start) / max(1, old_end - old_start)
                return new_start + round((new_end - new_start) * ratio)
        return len(visible_edit)

    placements: list[tuple[int, str]] = []
    previous_offset = 0
    for marker in markers:
        token = str(marker["token"])
        token_index = reference_target.find(token)
        if token_index >= 0 and reference_visible:
            visible_offset = len(strip_protected_markers(reference_target[:token_index]))
            edit_offset = mapped_offset(visible_offset, str(marker.get("kind", "")))
        else:
            ratio = float(marker.get("source_offset", 0)) / max(1, len(source_visible))
            edit_offset = round(len(visible_edit) * min(1.0, max(0.0, ratio)))
        edit_offset = max(previous_offset, edit_offset)
        placements.append((edit_offset, token))
        previous_offset = edit_offset

    chunks: list[str] = []
    cursor = 0
    for offset, token in placements:
        chunks.append(visible_edit[cursor:offset])
        chunks.append(token)
        cursor = offset
    chunks.append(visible_edit[cursor:])
    return "".join(chunks)


def repair_missing_markers(source: str, target: str, markers: list[dict[str, Any]]) -> str:
    """Restore missing or invalid tokens without changing the visible translation."""
    return restore_protected_markers(source, target, target, markers)


def render_fragment(target: str, markers: list[dict[str, Any]]) -> str:
    escaped = html.escape(target).replace("\n", "<br/>")
    for marker in markers:
        escaped = escaped.replace(html.escape(str(marker["token"])), str(marker["html"]))
    return escaped


def replace_block_contents(block: Tag, target: str, markers: list[dict[str, Any]]) -> None:
    fragment = BeautifulSoup(render_fragment(target, markers), "html.parser")
    block.clear()
    for child in list(fragment.contents):
        block.append(child)
