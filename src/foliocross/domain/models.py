"""Stable domain models shared by importers, storage, workers, and exporters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    TRANSLATING = "translating"
    QUALITY_CHECK = "quality_check"
    READY = "ready"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DesiredState(str, Enum):
    RUN = "run"
    PAUSE = "pause"
    CANCEL = "cancel"


class SegmentStatus(str, Enum):
    PENDING = "pending"
    TRANSLATED = "translated"
    NEEDS_REVIEW = "needs_review"


@dataclass(slots=True)
class SegmentDraft:
    source_text: str
    locator: dict[str, Any] = field(default_factory=dict)
    markers: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ChapterDraft:
    title: str
    segments: list[SegmentDraft]
    locator: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedBook:
    title: str
    author: str
    source_format: str
    source_lang: str
    chapters: list[ChapterDraft]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ModelProfile:
    id: str = "deepseek-default"
    name: str = "DeepSeek Flash"
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    translation_model: str = "deepseek-v4-flash"
    analysis_model: str = "deepseek-v4-flash"
    repair_model: str = "deepseek-v4-flash"
    review_model: str = "deepseek-v4-flash"
    thinking: bool = False
    input_price_per_million: float | None = 0.22
    cached_input_price_per_million: float | None = 0.007
    output_price_per_million: float | None = 0.66
    currency: str = "USD"
    price_effective_date: str | None = "2026-08-16"
    price_source: str | None = "https://api-docs.deepseek.com/quick_start/pricing/"
    peak_multiplier: float = 2.0
    peak_weekdays_utc: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    peak_windows_utc: list[list[str]] = field(
        default_factory=lambda: [["01:00", "04:00"], ["06:00", "10:00"]]
    )


@dataclass(slots=True)
class JobConfig:
    source_lang: str = "auto"
    target_lang: str = "zh-CN"
    preset: str = "steady"
    output_format: str = "epub"
    bilingual: bool = False
    max_chars_per_batch: int = 5000
    max_chars_per_segment: int = 1200
    rolling_context_segments: int = 6
    prescan_concurrency: int = 4
    translation_start_concurrency: int = 2
    translation_max_concurrency: int = 4
    max_retries: int = 4
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    soft_budget: float | None = None
    hard_budget: float | None = None
    deep_review: bool = False
    prompt_set_version: str = "2026-09-03.1"
    profile: ModelProfile = field(default_factory=ModelProfile)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "JobConfig":
        raw = dict(value)
        profile = raw.get("profile")
        if isinstance(profile, dict):
            raw["profile"] = ModelProfile(**profile)
        return cls(**raw)
