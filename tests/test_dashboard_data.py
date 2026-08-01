from __future__ import annotations

from datetime import date

import pandas as pd

from market_intelligence.dashboard import data


def test_market_events_are_bounded_and_dates_are_parsed(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_read_sql_query(query, engine, *, params, parse_dates):
        captured["query"] = str(query)
        captured["engine"] = engine
        captured["params"] = params
        captured["parse_dates"] = parse_dates
        return pd.DataFrame(
            {
                "event_date": pd.to_datetime(["2026-02-28"]),
                "plot_date": pd.to_datetime(["2026-03-02"]),
                "short_label": ["Operation Epic Fury begins"],
            }
        )

    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)
    engine = object()

    result = data.load_market_events(
        engine,
        window_start_date=date(2026, 1, 1),
        window_end_date=date(2026, 3, 13),
    )

    assert len(result) == 1
    assert captured["engine"] is engine
    assert captured["params"] == {
        "window_start_date": date(2026, 1, 1),
        "window_end_date": date(2026, 3, 13),
        "max_events": 5,
    }
    assert captured["parse_dates"] == [
        "event_date",
        "event_timestamp_utc",
        "plot_date",
    ]
    assert "event.is_approved" in captured["query"]
    assert "AT TIME ZONE 'Australia/Sydney'" in captured["query"]
    assert "event.effective_market_date" in captured["query"]
    assert "abs(rba_cash_rate_percent - previous_cash_rate) >= 0.10" in captured["query"]
    assert "LIMIT :max_events" in captured["query"]
