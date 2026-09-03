"""Versioned model pricing and conservative pre-run estimates."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Iterable

from ..domain.models import ModelProfile
from .llm import ModelUsage


def _parse_clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour, minute)


def is_peak(profile: ModelProfile, moment: datetime | None = None) -> bool:
    """Return whether the profile's documented peak multiplier applies."""

    if profile.peak_multiplier <= 1 or not profile.peak_windows_utc:
        return False
    current = moment or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if current.weekday() not in profile.peak_weekdays_utc:
        return False
    clock = current.time().replace(tzinfo=None)
    return any(
        _parse_clock(start) <= clock < _parse_clock(end) for start, end in profile.peak_windows_utc
    )


def price_multiplier(profile: ModelProfile, moment: datetime | None = None) -> float:
    return profile.peak_multiplier if is_peak(profile, moment) else 1.0


def calculate_cost(
    profile: ModelProfile,
    usage: ModelUsage,
    *,
    moment: datetime | None = None,
) -> float | None:
    """Calculate one request using actual cache-hit tokens and active time band."""

    if profile.input_price_per_million is None or profile.output_price_per_million is None:
        return None
    cached = min(max(0, usage.prompt_tokens), max(0, usage.cache_hit_tokens))
    uncached = max(0, usage.prompt_tokens - cached)
    cached_price = profile.cached_input_price_per_million
    if cached_price is None:
        cached_price = profile.input_price_per_million
    base = (
        uncached * profile.input_price_per_million
        + cached * cached_price
        + max(0, usage.completion_tokens) * profile.output_price_per_million
    ) / 1_000_000
    return base * price_multiplier(profile, moment)


def estimate_book_tokens(source_texts: Iterable[str]) -> tuple[int, int]:
    """Estimate the default pipeline, including prompts and preparation."""

    characters = sum(len(text) for text in source_texts)
    source_tokens = max(1, round(characters / 4))
    input_tokens = max(1, round(source_tokens * 1.35))
    output_tokens = max(1, round(characters * 0.75))
    return input_tokens, output_tokens


def estimate_cost(
    profile: ModelProfile,
    input_tokens: int,
    output_tokens: int,
    *,
    peak: bool = False,
) -> float | None:
    if profile.input_price_per_million is None or profile.output_price_per_million is None:
        return None
    base = (
        input_tokens * profile.input_price_per_million
        + output_tokens * profile.output_price_per_million
    ) / 1_000_000
    return base * (profile.peak_multiplier if peak else 1.0)
