"""High-level import, edit, query, export, and environment use cases."""

from __future__ import annotations

import importlib.util
import math
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..domain.models import DesiredState, JobConfig, ModelProfile
from ..errors import FolioCrossError
from ..infrastructure.credentials import CredentialStore
from ..infrastructure.formats.calibre import find_ebook_convert
from ..infrastructure.formats.common import split_long_segments
from ..infrastructure.formats.conversion import (
    convert_kindle_to_epub,
    find_kindleunpack_python,
    is_kindle_format,
)
from ..infrastructure.formats.covers import extract_cover
from ..infrastructure.formats.exporters import export_job
from ..infrastructure.formats.markers import restore_protected_markers, validate_markers
from ..infrastructure.formats.registry import parse_book
from ..infrastructure.llm import OpenAICompatibleClient, parse_json_content
from ..infrastructure.pricing import calculate_cost, estimate_cost
from ..infrastructure.repository import Repository, new_id, sha256_file
from ..infrastructure.workspace import Workspace


class FolioCrossService:
    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace or Workspace.default()
        self.repository = Repository(self.workspace)
        self.repository.recover_interrupted_jobs()
        self.credentials = CredentialStore()

    def default_job_config(self) -> JobConfig:
        saved = self.repository.get_setting("model_profile")
        profile = ModelProfile(**saved) if isinstance(saved, dict) else ModelProfile()
        return JobConfig(profile=profile)

    def save_model_profile(self, values: dict[str, Any]) -> dict[str, Any]:
        current = self.default_job_config().profile
        provider = str(values.get("provider", current.provider)).strip().lower()
        if provider not in {"deepseek", "openai", "ollama", "vllm"}:
            raise FolioCrossError("invalid_provider", f"不支持的模型服务类型：{provider}")

        def optional_price(key: str) -> float | None:
            raw = str(values.get(key, "")).strip()
            return float(raw) if raw else None

        data = {
            "provider": provider,
            "base_url": str(values.get("base_url", current.base_url)).strip().rstrip("/"),
            "api_key_env": str(
                values.get(
                    "api_key_env",
                    {
                        "deepseek": "DEEPSEEK_API_KEY",
                        "openai": "OPENAI_API_KEY",
                        "ollama": "",
                        "vllm": "",
                    }[provider],
                )
            ).strip(),
            "translation_model": str(values.get("model", current.translation_model)).strip(),
            "analysis_model": str(values.get("model", current.analysis_model)).strip(),
            "repair_model": str(values.get("model", current.repair_model)).strip(),
            "review_model": str(values.get("model", current.review_model)).strip(),
            "input_price_per_million": optional_price("input_price"),
            "cached_input_price_per_million": optional_price("cached_input_price"),
            "output_price_per_million": optional_price("output_price"),
            "currency": str(values.get("currency", current.currency)).strip().upper(),
            "price_effective_date": str(
                values.get("effective_date", current.price_effective_date or "")
            ).strip(),
            "price_source": (
                str(values.get("price_source", current.price_source or "")).strip() or None
                if provider == "deepseek"
                else None
            ),
            "peak_multiplier": current.peak_multiplier if provider == "deepseek" else 1.0,
            "peak_weekdays_utc": current.peak_weekdays_utc if provider == "deepseek" else [],
            "peak_windows_utc": current.peak_windows_utc if provider == "deepseek" else [],
        }
        if not data["base_url"] or not data["translation_model"]:
            raise FolioCrossError("invalid_model_profile", "模型名称和接口地址都不能为空。")
        profile = ModelProfile(**{**asdict(current), **data})
        serialized = asdict(profile)
        self.repository.set_setting("model_profile", serialized)
        return serialized

    def import_book(
        self,
        path: str,
        config: JobConfig | None = None,
        *,
        working_source_override: str | None = None,
    ) -> dict[str, Any]:
        config = config or self.default_job_config()
        output = config.output_format.lower()
        if output not in {"epub", "docx", "html", "txt", "md", "markdown"}:
            raise FolioCrossError("unsupported_output", f"不支持的输出格式：{config.output_format}")
        config.output_format = "md" if output == "markdown" else output
        if config.profile.provider not in {"deepseek", "openai", "ollama", "vllm", "fake"}:
            raise FolioCrossError(
                "invalid_provider", f"不支持的模型服务类型：{config.profile.provider}"
            )
        if config.soft_budget is not None and config.soft_budget <= 0:
            raise FolioCrossError("invalid_budget", "费用提醒值必须大于 0。")
        if config.hard_budget is not None and config.hard_budget < 0:
            raise FolioCrossError("invalid_budget", "费用上限不能为负数。")
        if (
            config.soft_budget is not None
            and config.hard_budget is not None
            and config.soft_budget > config.hard_budget
        ):
            raise FolioCrossError("invalid_budget", "费用提醒值不能高于硬预算上限。")
        config.translation_max_concurrency = max(1, min(4, int(config.translation_max_concurrency)))
        config.translation_start_concurrency = min(
            config.translation_start_concurrency, config.translation_max_concurrency
        )
        source = Path(path).resolve()
        if not source.is_file():
            raise FolioCrossError("file_not_found", f"找不到文件：{source}")
        source_hash = sha256_file(source)
        existing = self.repository.find_book_by_hash(source_hash)
        if existing:
            previous_job = self.repository.latest_job_for_book(existing["id"])
            if previous_job:
                self.repository.unarchive_job(previous_job["id"])
                return {
                    "ok": True,
                    "book_id": existing["id"],
                    "job_id": previous_job["id"],
                    "title": previous_job["title"],
                    "chapters": len(self.repository.chapters_for_job(previous_job["id"])),
                    "segments": previous_job["total_segments"],
                    "warnings": previous_job.get("warnings", []),
                    "reused": True,
                }
        book_id = existing["id"] if existing else new_id()
        source_dir = self.workspace.book_source_dir(book_id)
        source_dir.mkdir(parents=True, exist_ok=True)
        stored_source = (
            Path(existing["stored_source_path"]) if existing else source_dir / source.name
        )
        if not stored_source.is_file():
            shutil.copy2(source, stored_source)
        working_source = Path(existing["working_source_path"]) if existing else stored_source
        original_format = source.suffix.lower().lstrip(".")
        conversion_info: dict[str, Any] | None = None
        if working_source_override:
            override = Path(working_source_override).resolve()
            if not override.is_file():
                raise FolioCrossError("working_source_missing", f"找不到规范化源文件：{override}")
            working_source = source_dir / "normalized" / f"{source_hash}{override.suffix.lower()}"
            working_source.parent.mkdir(parents=True, exist_ok=True)
            if not working_source.is_file():
                shutil.copy2(override, working_source)
        elif is_kindle_format(str(source)):
            calibre_path = self.repository.get_setting("calibre_path")
            kindleunpack_python = self.repository.get_setting("kindleunpack_python")
            working_source = source_dir / "normalized" / f"{source_hash}.epub"
            converted = convert_kindle_to_epub(
                str(stored_source),
                str(working_source),
                kindleunpack_python=kindleunpack_python,
                calibre_executable=calibre_path,
            )
            conversion_info = {
                "backend": converted.backend,
                "backend_path": converted.backend_path,
                "fallback_attempts": converted.attempts,
            }
        parsed = parse_book(str(working_source), config.source_lang)
        parsed.source_format = original_format
        if conversion_info:
            parsed.metadata["source_conversion"] = conversion_info
        parsed = split_long_segments(parsed, config.max_chars_per_segment)
        job_id = new_id()
        actual_book_id, job_id = self.repository.create_book_and_job(
            book_id=book_id,
            job_id=job_id,
            parsed=parsed,
            source_hash=source_hash,
            original_path=str(source),
            stored_source_path=str(stored_source),
            working_source_path=str(working_source),
            config=config,
        )
        job = self.repository.get_job(job_id)
        self.repository.add_artifact(
            job_id,
            kind="source",
            format_name=original_format,
            path=str(stored_source),
            metadata={"sha256": source_hash},
        )
        if Path(working_source) != Path(stored_source):
            self.repository.add_artifact(
                job_id,
                kind="normalized_source",
                format_name=Path(working_source).suffix.lstrip("."),
                path=str(working_source),
                metadata=conversion_info or {"source": "migration_override"},
            )
        cover = extract_cover(
            str(working_source),
            Path(working_source).suffix.lower().lstrip("."),
            self.workspace.job_artifact_dir(job_id),
        )
        if cover:
            self.repository.add_artifact(
                job_id,
                kind="cover",
                format_name=Path(cover).suffix.lstrip("."),
                path=cover,
            )
        return {
            "ok": True,
            "book_id": actual_book_id,
            "job_id": job_id,
            "title": job["title"],
            "chapters": len(self.repository.chapters_for_job(job_id)),
            "segments": job["total_segments"],
            "warnings": job.get("warnings", []),
        }

    def export(
        self, job_id: str, format_name: str | None = None, output_path: str | None = None
    ) -> dict[str, Any]:
        path = export_job(self.repository, job_id, format_name, output_path)
        artifact_id = self.repository.add_artifact(
            job_id,
            kind="translation",
            format_name=(format_name or Path(path).suffix.lstrip(".")),
            path=path,
        )
        return {"ok": True, "artifact_id": artifact_id, "path": path}

    def edit_segment(
        self,
        segment_id: str,
        text: str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not text.strip():
            raise FolioCrossError("empty_edit", "译文不能为空。")
        version = self.repository.save_segment_revision(
            segment_id,
            text,
            origin="manual",
            lock=True,
            expected_version=expected_version,
        )
        return {"ok": True, "segment_id": segment_id, "version": version, "locked": True}

    def restore_revision(
        self, revision_id: str, *, expected_version: int | None = None
    ) -> dict[str, Any]:
        revision = self.repository.revision(revision_id)
        version = self.repository.save_segment_revision(
            revision["segment_id"],
            revision["text"],
            origin="history_restore",
            expected_version=expected_version,
            instruction=f"恢复到版本 {revision['version']}",
            lock=True,
            allow_locked=True,
        )
        return {
            "ok": True,
            "segment_id": revision["segment_id"],
            "version": version,
            "restored_from": revision["version"],
        }

    def update_glossary(
        self,
        job_id: str,
        source: str,
        target: str,
        *,
        apply_existing: bool = False,
    ) -> dict[str, Any]:
        result = self.repository.update_glossary_term(job_id, source, target)
        snapshot = self.repository.glossary_snapshot(job_id)
        result["snapshot_stale"] = bool(snapshot["version"])
        result["snapshot_version"] = snapshot["version"]
        result["applied_segments"] = 0
        previous = result["previous_target"]
        if not apply_existing or not previous or previous == target:
            return {"ok": True, **result}
        for segment in self.repository.segments_containing_source(job_id, source):
            if previous not in segment["target_text"]:
                continue
            revised = segment["target_text"].replace(previous, target)
            if revised == segment["target_text"]:
                continue
            self.repository.save_segment_revision(
                segment["id"],
                revised,
                origin="glossary_apply",
                instruction=f"术语：{source}，{previous} → {target}",
                lock=True,
                allow_locked=True,
            )
            result["applied_segments"] += 1
        return {"ok": True, **result}

    def refresh_glossary_snapshot(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        if job["status"] in {"preparing", "translating", "quality_check", "exporting"}:
            raise FolioCrossError(
                "job_is_running", "任务运行期间不能更换已冻结的术语版本，请先安全暂停。"
            )
        snapshot = self.repository.freeze_glossary(job_id)
        return {"ok": True, **snapshot}

    def apply_issue_suggestion(
        self,
        issue_id: str,
        edited_suggestion: str | None = None,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        issue = self.repository.issue(issue_id)
        suggestion = (
            edited_suggestion.strip()
            if edited_suggestion is not None
            else str(issue["suggestion"]).strip()
        )
        if not issue["segment_id"] or not suggestion:
            raise FolioCrossError("issue_has_no_suggestion", "这个问题没有可直接应用的修改建议。")
        segment = self.repository.segment(issue["segment_id"])
        if validate_markers(suggestion, segment["markers"]):
            suggestion = restore_protected_markers(
                segment["source_text"], segment["target_text"], suggestion, segment["markers"]
            )
        version = self.repository.save_segment_revision(
            issue["segment_id"],
            suggestion,
            origin="review_accept",
            accepted_issue_id=issue_id,
            expected_version=expected_version,
            instruction=issue["message"],
            lock=True,
            allow_locked=True,
        )
        return {
            "ok": True,
            "issue_id": issue_id,
            "segment_id": issue["segment_id"],
            "version": version,
        }

    def estimate_deep_review(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        config = JobConfig.from_dict(job["config"])
        segments = [
            segment
            for chapter in self.repository.chapters_for_job(job_id)
            for segment in self.repository.segments_for_chapter(chapter["id"])
            if segment["target_text"]
        ]
        if not segments:
            raise FolioCrossError("review_not_ready", "还没有可审校的译文。")
        combined_chars = sum(
            len(item["source_text"]) + len(item["target_text"]) for item in segments
        )
        input_tokens = max(1, round(combined_chars / 3.5 * 1.2))
        output_tokens = max(1, round(input_tokens * 0.12))
        batch_chars = max(1, config.max_chars_per_batch * 2)
        calls = max(1, math.ceil(combined_chars / batch_chars))
        off_peak = estimate_cost(config.profile, input_tokens, output_tokens, peak=False)
        peak = estimate_cost(config.profile, input_tokens, output_tokens, peak=True)
        return {
            "ok": True,
            "job_id": job_id,
            "model": config.profile.review_model,
            "estimated_calls": calls,
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "estimated_cost_min": off_peak,
            "estimated_cost_max": peak,
            "currency": config.profile.currency,
            "price_effective_date": config.profile.price_effective_date,
        }

    def control_job(self, job_id: str, action: str) -> dict[str, Any]:
        mapping = {
            "run": DesiredState.RUN,
            "resume": DesiredState.RUN,
            "pause": DesiredState.PAUSE,
            "cancel": DesiredState.CANCEL,
        }
        if action not in mapping:
            raise FolioCrossError("invalid_action", f"不支持的任务操作：{action}")
        self.repository.set_desired_state(job_id, mapping[action])
        return {"ok": True, "job_id": job_id, "desired_state": mapping[action].value}

    def archive_job(self, job_id: str) -> dict[str, Any]:
        status = self.repository.get_job(job_id)["status"]
        if status in {
            "preparing",
            "translating",
            "quality_check",
            "exporting",
        }:
            raise FolioCrossError("job_is_running", "请先暂停任务，再将它归档。")
        self.repository.archive_job(job_id)
        return {"ok": True, "job_id": job_id, "archived": True}

    def configure_job(
        self,
        job_id: str,
        *,
        source_lang: str,
        output_format: str,
        bilingual: bool,
        soft_budget: float | None,
        hard_budget: float | None,
        max_concurrency: int = 4,
        requests_per_minute: int | None = None,
        tokens_per_minute: int | None = None,
    ) -> dict[str, Any]:
        output = output_format.lower()
        if output not in {"epub", "docx", "html", "txt", "md", "markdown"}:
            raise FolioCrossError("unsupported_output", f"不支持的输出格式：{output_format}")
        job = self.repository.get_job(job_id)
        config = JobConfig.from_dict(job["config"])
        config.source_lang = source_lang or "auto"
        config.target_lang = "zh-CN"
        config.output_format = "md" if output == "markdown" else output
        config.bilingual = bilingual
        config.soft_budget = soft_budget
        config.hard_budget = hard_budget
        config.translation_max_concurrency = max(1, min(4, int(max_concurrency)))
        config.translation_start_concurrency = min(
            config.translation_start_concurrency, config.translation_max_concurrency
        )
        config.requests_per_minute = requests_per_minute
        config.tokens_per_minute = tokens_per_minute
        self.repository.update_job_config(job_id, config)
        return {"ok": True, "job_id": job_id, "config": config.to_dict()}

    def save_api_key(self, profile_id: str, api_key: str) -> dict[str, Any]:
        self.credentials.set(profile_id, api_key)
        return {"ok": True, "profile_id": profile_id}

    def doctor(self) -> dict[str, Any]:
        dependencies = {
            name: importlib.util.find_spec(module) is not None
            for name, module in {
                "PySide6": "PySide6",
                "OpenAI SDK": "openai",
                "BeautifulSoup": "bs4",
                "lxml": "lxml",
                "python-docx": "docx",
                "keyring": "keyring",
            }.items()
        }
        configured_calibre = self.repository.get_setting("calibre_path")
        try:
            calibre = find_ebook_convert(configured_calibre)
        except FolioCrossError:
            calibre = None
        configured_kindleunpack = self.repository.get_setting("kindleunpack_python")
        try:
            kindleunpack = find_kindleunpack_python(configured_kindleunpack)
        except FolioCrossError:
            kindleunpack = None
        profile = self.default_job_config().profile
        key_available = bool(self.credentials.get(profile.id, profile.api_key_env))
        return {
            "ok": all(dependencies.values()),
            "workspace": str(self.workspace.root),
            "database": str(self.workspace.db_path),
            "dependencies": dependencies,
            "kindleunpack": {"available": bool(kindleunpack), "path": kindleunpack},
            "calibre": {"available": bool(calibre), "path": calibre},
            "kindle_conversion": {
                "available": bool(kindleunpack or calibre),
                "preferred_backend": (
                    "kindleunpack" if kindleunpack else ("calibre" if calibre else None)
                ),
                "calibre_optional": True,
            },
            "model_api_key": {
                "available": key_available,
                "provider": profile.provider,
                "source": "credential-or-environment",
            },
            "deepseek_api_key": {"available": key_available, "source": "credential-or-environment"},
            "platform": os.name,
            "model_profile": asdict(profile),
            "active_task_limit": int(self.repository.get_setting("active_task_limit", 1) or 1),
        }

    def test_model_connection(self) -> dict[str, Any]:
        profile = self.default_job_config().profile
        response = OpenAICompatibleClient(profile, self.credentials).complete(
            model=profile.translation_model,
            system='这是连接检查。返回 JSON：{"ok":true}。',
            user="{}",
            json_mode=True,
            max_tokens=16,
        )
        result = parse_json_content(response.content)
        if result.get("ok") is not True:
            raise FolioCrossError("model_connection_invalid", "模型已响应，但没有返回预期结果。")
        return {
            "ok": True,
            "connected": True,
            "provider": profile.provider,
            "model": profile.translation_model,
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "cost": calculate_cost(profile, response.usage),
            "currency": profile.currency,
        }
