from __future__ import annotations

import pytest

from market_intelligence.assistant.tools import _date_range, _metric


def test_date_range_rejects_reverse_order() -> None:
    with pytest.raises(ValueError, match="start_date"):
        _date_range("2026-07-01", "2026-06-01")


def test_metric_rejects_non_allowlisted_column() -> None:
    with pytest.raises(ValueError, match="metric must be one of"):
        _metric("drop_table")
