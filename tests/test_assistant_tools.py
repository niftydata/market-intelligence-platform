from __future__ import annotations

import pytest

from market_intelligence.assistant.tools import (
    MarketDataTools,
    _correlation_summary,
    _date_range,
    _metric,
)


def test_date_range_rejects_reverse_order() -> None:
    with pytest.raises(ValueError, match="start_date"):
        _date_range("2026-07-01", "2026-06-01")


def test_metric_rejects_non_allowlisted_column() -> None:
    with pytest.raises(ValueError, match="metric must be one of"):
        _metric("drop_table")


def test_correlation_summary_handles_constant_values() -> None:
    summary = _correlation_summary(
        [(1.0, 2.0), (1.0, 3.0)],
        definition="test",
    )

    assert summary["coefficient"] is None
    assert summary["direction"] == "unavailable"


def test_correlation_summary_labels_zero_as_neutral() -> None:
    summary = _correlation_summary(
        [(-1.0, 1.0), (0.0, 0.0), (1.0, 1.0)],
        definition="test",
    )

    assert summary["coefficient"] == pytest.approx(0.0)
    assert summary["direction"] == "neutral"
    assert summary["strength"] == "negligible"


def test_metric_correlation_rejects_the_same_metric() -> None:
    tools = MarketDataTools(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="must be different"):
        tools.analyse_metric_correlation(
            "return_20d_percent",
            "return_20d_percent",
            "2026-01-01",
            "2026-03-31",
        )
