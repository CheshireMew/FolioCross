"""Deterministic translation checks that do not spend model tokens."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from ..infrastructure.formats.markers import validate_markers

MOJIBAKE = ("ï¿½", "â€™", "â€œ", "â€", "�")


def check_translation(
    source: str, target: str, markers: list[dict[str, Any]], terms: list[dict[str, Any]]
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not target.strip():
        return [{"category": "empty", "severity": "error", "message": "模型返回了空译文。"}]
    source_plain = re.sub(r"⟦FC:[^⟧]+⟧", "", source).strip()
    target_plain = re.sub(r"⟦FC:[^⟧]+⟧", "", target).strip()
    if len(source_plain) >= 20 and SequenceMatcher(None, source_plain, target_plain).ratio() > 0.96:
        issues.append(
            {"category": "untranslated", "severity": "error", "message": "译文与原文几乎完全相同。"}
        )
    source_words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", source_plain)
    if len(source_words) >= 6:
        retained = sum(
            1 for word in source_words if re.search(rf"\b{re.escape(word)}\b", target_plain)
        )
        if retained / len(source_words) >= 0.5:
            issues.append(
                {
                    "category": "source_residue",
                    "severity": "error",
                    "message": "译文中保留了大量原文单词，可能存在局部漏译。",
                }
            )
    ratio = len(target_plain) / max(1, len(source_plain))
    if len(source_plain) >= 40 and ratio < 0.16:
        issues.append(
            {
                "category": "too_short",
                "severity": "error",
                "message": "译文相对原文明显过短，可能漏译。",
            }
        )
    if ratio > 4.5:
        issues.append(
            {
                "category": "too_long",
                "severity": "warning",
                "message": "译文长度异常，可能出现重复或扩写。",
            }
        )
    for message in validate_markers(target, markers):
        issues.append({"category": "marker", "severity": "error", "message": message})
    for term in terms:
        if term["source"] in source and term["target"] not in target:
            issues.append(
                {
                    "category": "terminology",
                    "severity": "warning",
                    "message": f"未发现约定译名：{term['source']} → {term['target']}",
                }
            )
    if any(token in target for token in MOJIBAKE):
        issues.append(
            {"category": "mojibake", "severity": "error", "message": "译文中出现疑似乱码。"}
        )
    if re.search(r"(.{12,80}?)(?:\s*\1)", target_plain):
        issues.append(
            {
                "category": "repetition",
                "severity": "warning",
                "message": "译文中出现疑似重复内容。",
            }
        )
    pairs = (("（", "）"), ("【", "】"), ("《", "》"), ("“", "”"))
    if any(target_plain.count(left) != target_plain.count(right) for left, right in pairs):
        issues.append(
            {
                "category": "punctuation",
                "severity": "warning",
                "message": "译文中有未配对的中文括号或引号。",
            }
        )
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", target):
        issues.append(
            {
                "category": "control_character",
                "severity": "error",
                "message": "译文中出现不可见控制字符。",
            }
        )
    return issues
