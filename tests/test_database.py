from __future__ import annotations

from market_intelligence.database import create_database_engine


def test_render_postgres_url_uses_psycopg_driver() -> None:
    engine = create_database_engine(
        "postgresql://user:password@example.internal/database"
    )
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.pool.size() == 3
    finally:
        engine.dispose()
