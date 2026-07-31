from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any

import market_intelligence.pipeline as pipeline


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _run(
    pipeline_run_id: int,
    *,
    status: str = "succeeded",
    received: int = 10,
    accepted: int = 9,
    rejected: int = 1,
) -> dict[str, Any]:
    return {
        "pipeline_run_id": pipeline_run_id,
        "status": status,
        "records_received": received,
        "records_accepted": accepted,
        "records_rejected": rejected,
    }


def test_full_refresh_runs_sources_then_curated(
    monkeypatch,
) -> None:
    engine = FakeEngine()
    calls: list[str] = []
    runs = {
        11: _run(11),
        12: _run(12, received=3, accepted=3, rejected=0),
        13: _run(13, received=1_200, accepted=1_200, rejected=0),
    }
    monkeypatch.setattr(pipeline, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(pipeline, "data_refresh_lock", lambda _: nullcontext())
    monkeypatch.setattr(
        pipeline,
        "run_yahoo_pipeline",
        lambda *_args, **_kwargs: calls.append("yahoo") or 11,
    )
    monkeypatch.setattr(
        pipeline,
        "run_rba_pipeline",
        lambda *_args, **_kwargs: calls.append("rba") or 12,
    )
    monkeypatch.setattr(
        pipeline,
        "run_curated_pipeline",
        lambda *_args, **_kwargs: calls.append("curated") or 13,
    )
    monkeypatch.setattr(
        pipeline,
        "pipeline_run_result",
        lambda _engine, run_id: runs[run_id],
    )

    result = pipeline.run_full_refresh(
        SimpleNamespace(database_url="postgresql://example"),  # type: ignore[arg-type]
        as_of_date=date(2026, 7, 31),
    )

    assert calls == ["yahoo", "rba", "curated"]
    assert result.succeeded
    assert [stage.stage for stage in result.stages] == [
        "Yahoo Finance",
        "RBA cash rate",
        "Curated analytics",
    ]
    assert result.stages[0].records_rejected == 1
    assert engine.disposed


def test_full_refresh_reports_source_failure_and_skips_curated(
    monkeypatch,
) -> None:
    engine = FakeEngine()
    curated_called = False
    runs = {
        21: _run(21, status="failed", received=4, accepted=0, rejected=0),
        22: _run(22, received=2, accepted=2, rejected=0),
    }

    def fail_yahoo(*_args, **_kwargs) -> int:
        raise pipeline.PipelineExecutionError(pipeline.PIPELINE_NAME, 21)

    def curated(*_args, **_kwargs) -> int:
        nonlocal curated_called
        curated_called = True
        return 23

    monkeypatch.setattr(pipeline, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(pipeline, "data_refresh_lock", lambda _: nullcontext())
    monkeypatch.setattr(pipeline, "run_yahoo_pipeline", fail_yahoo)
    monkeypatch.setattr(pipeline, "run_rba_pipeline", lambda *_args, **_kwargs: 22)
    monkeypatch.setattr(pipeline, "run_curated_pipeline", curated)
    monkeypatch.setattr(
        pipeline,
        "pipeline_run_result",
        lambda _engine, run_id: runs[run_id],
    )

    result = pipeline.run_full_refresh(
        SimpleNamespace(database_url="postgresql://example"),  # type: ignore[arg-type]
        as_of_date=date(2026, 7, 31),
    )

    assert not result.succeeded
    assert [stage.status for stage in result.stages] == [
        "failed",
        "succeeded",
        "skipped",
    ]
    assert not curated_called
    assert engine.disposed
