CREATE SCHEMA IF NOT EXISTS reference;

CREATE TABLE IF NOT EXISTS reference.market_event (
    market_event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_date date NOT NULL,
    short_label text NOT NULL,
    description text NOT NULL,
    category text NOT NULL CHECK (
        category IN ('geopolitical', 'monetary_policy', 'market_shock', 'other')
    ),
    source_name text NOT NULL,
    source_url text NOT NULL,
    display_priority integer NOT NULL DEFAULT 50 CHECK (
        display_priority BETWEEN 1 AND 100
    ),
    is_approved boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_market_event_date_label UNIQUE (event_date, short_label),
    CONSTRAINT ck_market_event_source_url CHECK (source_url ~ '^https://')
);

CREATE INDEX IF NOT EXISTS ix_market_event_approved_date
    ON reference.market_event (event_date, display_priority DESC)
    WHERE is_approved;

INSERT INTO reference.market_event (
    event_date,
    short_label,
    description,
    category,
    source_name,
    source_url,
    display_priority,
    is_approved
)
VALUES (
    DATE '2026-02-28',
    'Operation Epic Fury begins',
    'US Central Command commenced Operation Epic Fury against Iran.',
    'geopolitical',
    'US Department of Defense',
    'https://media.defense.gov/2026/Mar/29/2003904283/-1/-1/1/OPERATION-EPIC-FURY-FACT-SHEET-THE-FIRST-29-DAYS.PDF',
    100,
    true
)
ON CONFLICT (event_date, short_label) DO NOTHING;
