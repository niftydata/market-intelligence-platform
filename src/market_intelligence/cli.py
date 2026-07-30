from __future__ import annotations

import argparse
from datetime import date

from market_intelligence.config import Settings
from market_intelligence.database import apply_migrations, create_database_engine
from market_intelligence.logging_config import configure_logging
from market_intelligence.pipeline import run_yahoo_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-intelligence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Apply outstanding database migrations.")

    ingest_parser = subparsers.add_parser(
        "ingest-yahoo", help="Ingest daily Yahoo Finance market-index data."
    )
    ingest_parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=date.today(),
        help="Inclusive extraction end date in YYYY-MM-DD format.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_environment()
    configure_logging(settings.log_level)

    if args.command == "init-db":
        engine = create_database_engine(settings.database_url)
        try:
            apply_migrations(engine)
        finally:
            engine.dispose()
        return

    if args.command == "ingest-yahoo":
        run_yahoo_pipeline(settings, as_of_date=args.as_of)
        return

    raise RuntimeError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
