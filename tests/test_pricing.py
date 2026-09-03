from datetime import datetime, timezone

import pytest

from foliocross.domain.models import ModelProfile
from foliocross.infrastructure.llm import ModelUsage
from foliocross.infrastructure.pricing import (
    calculate_cost,
    estimate_book_tokens,
    is_peak,
)


def test_deepseek_peak_windows_and_cache_pricing():
    profile = ModelProfile()
    peak = datetime(2026, 9, 2, 2, 0, tzinfo=timezone.utc)
    off_peak = datetime(2026, 9, 2, 5, 0, tzinfo=timezone.utc)
    weekend = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    assert is_peak(profile, peak)
    assert not is_peak(profile, off_peak)
    assert not is_peak(profile, weekend)
    usage = ModelUsage(
        prompt_tokens=1_000_000, completion_tokens=1_000_000, cache_hit_tokens=500_000
    )
    expected_off_peak = 0.5 * 0.22 + 0.5 * 0.007 + 0.66
    assert calculate_cost(profile, usage, moment=off_peak) == pytest.approx(expected_off_peak)
    assert calculate_cost(profile, usage, moment=peak) == pytest.approx(expected_off_peak * 2)


def test_book_estimate_is_not_raw_character_count():
    input_tokens, output_tokens = estimate_book_tokens(["a" * 4000])
    assert input_tokens == 1350
    assert output_tokens == 3000
