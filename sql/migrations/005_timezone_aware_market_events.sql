ALTER TABLE reference.market_event
    ADD COLUMN IF NOT EXISTS event_timestamp_utc timestamptz,
    ADD COLUMN IF NOT EXISTS effective_market_date date,
    ADD COLUMN IF NOT EXISTS country_code text,
    ADD COLUMN IF NOT EXISTS transmission_channel text,
    ADD COLUMN IF NOT EXISTS event_scope text;

ALTER TABLE reference.market_event
    DROP CONSTRAINT IF EXISTS market_event_category_check;

ALTER TABLE reference.market_event
    ADD CONSTRAINT market_event_category_check CHECK (
        category IN (
            'geopolitical',
            'monetary_policy',
            'market_shock',
            'economic_policy',
            'public_health',
            'other'
        )
    ),
    ADD CONSTRAINT ck_market_event_country_code CHECK (
        country_code IS NULL OR country_code ~ '^[A-Z]{2}$'
    ),
    ADD CONSTRAINT ck_market_event_scope CHECK (
        event_scope IS NULL OR event_scope IN ('domestic', 'regional', 'global')
    );

UPDATE reference.market_event
SET
    effective_market_date = DATE '2026-03-02',
    country_code = 'US',
    transmission_channel = 'geopolitical risk and energy markets',
    event_scope = 'global',
    updated_at = now()
WHERE event_date = DATE '2026-02-28'
    AND short_label = 'Operation Epic Fury begins';

INSERT INTO reference.market_event (
    event_date,
    event_timestamp_utc,
    effective_market_date,
    short_label,
    description,
    category,
    country_code,
    transmission_channel,
    event_scope,
    source_name,
    source_url,
    display_priority,
    is_approved
)
VALUES
    (
        DATE '2021-09-20',
        NULL,
        DATE '2021-09-20',
        'Evergrande contagion concerns intensify',
        'Concerns about Evergrande and wider Chinese property-sector stress weighed on global risk sentiment.',
        'market_shock',
        'CN',
        'property, credit and commodity demand',
        'global',
        'Reserve Bank of Australia',
        'https://www.rba.gov.au/publications/smp/2021/nov/box-a-stress-in-the-chinese-property-development-sector.html',
        85,
        true
    ),
    (
        DATE '2022-02-24',
        NULL,
        DATE '2022-02-24',
        'Russia invades Ukraine',
        'Russian troops entered Ukraine and major attacks were reported across the country.',
        'geopolitical',
        'UA',
        'geopolitical risk, energy and commodities',
        'global',
        'United Nations',
        'https://ukraine.un.org/en/184851-statement-amin-awad-assistant-secretary-general-and-united-nations-crisis-coordinator',
        100,
        true
    ),
    (
        DATE '2022-03-28',
        TIMESTAMPTZ '2022-03-27 21:00:00+00',
        NULL,
        'Shanghai phased lockdown begins',
        'Shanghai began phased restrictions affecting mobility, transport and most business operations.',
        'public_health',
        'CN',
        'supply chains, production and commodity demand',
        'global',
        'Shanghai Municipal Government',
        'https://www.shanghai.gov.cn/sjzccs/20220327/613eda924f814a4ab4b25642f0e668c5.html',
        75,
        true
    ),
    (
        DATE '2022-12-07',
        NULL,
        DATE '2022-12-07',
        'China eases zero-COVID controls',
        'China announced ten measures that materially eased movement, testing and operating restrictions.',
        'public_health',
        'CN',
        'reopening, consumption and commodity demand',
        'global',
        'State Council of the People''s Republic of China',
        'https://english.www.gov.cn/statecouncil/ministries/202212/07/content_WS63909eb2c6d0a757729e4112.html',
        80,
        true
    ),
    (
        DATE '2023-03-10',
        TIMESTAMPTZ '2023-03-10 16:15:00+00',
        NULL,
        'US regional banking stress',
        'Silicon Valley Bank was closed and the FDIC was appointed as receiver.',
        'market_shock',
        'US',
        'banking liquidity, credit and global risk sentiment',
        'global',
        'Federal Deposit Insurance Corporation',
        'https://www.fdic.gov/resources/resolutions/bank-failures/failed-bank-list/silicon-valley.html',
        90,
        true
    ),
    (
        DATE '2024-08-05',
        TIMESTAMPTZ '2024-08-05 00:00:00+00',
        NULL,
        'Global carry-trade unwind',
        'Global equity volatility rose as weaker US data and an unwinding of yen-funded carry trades affected risk assets.',
        'market_shock',
        NULL,
        'leveraged positioning, currencies and global equities',
        'global',
        'Reserve Bank of Australia',
        'https://www.rba.gov.au/monetary-policy/rba-board-minutes/2024/2024-08-06.html',
        95,
        true
    ),
    (
        DATE '2024-09-24',
        NULL,
        DATE '2024-09-24',
        'China announces broad stimulus package',
        'Chinese authorities announced monetary, financial-market and property-sector support measures.',
        'economic_policy',
        'CN',
        'policy stimulus, property and commodity demand',
        'global',
        'Reserve Bank of Australia',
        'https://www.rba.gov.au/publications/smp/2024/nov/box-b-economic-policy-developments-in-china.html',
        85,
        true
    ),
    (
        DATE '2025-04-02',
        TIMESTAMPTZ '2025-04-02 20:00:00+00',
        NULL,
        'US reciprocal tariffs announced',
        'The United States announced additional tariffs applying broadly across trading partners.',
        'economic_policy',
        'US',
        'global trade, China exposure and commodities',
        'global',
        'The White House',
        'https://www.whitehouse.gov/presidential-actions/2025/04/regulating-imports-with-a-reciprocal-tariff-to-rectify-trade-practices-that-contribute-to-large-and-persistent-annual-united-states-goods-trade-deficits/',
        95,
        true
    )
ON CONFLICT (event_date, short_label) DO UPDATE
SET
    event_timestamp_utc = EXCLUDED.event_timestamp_utc,
    effective_market_date = EXCLUDED.effective_market_date,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    country_code = EXCLUDED.country_code,
    transmission_channel = EXCLUDED.transmission_channel,
    event_scope = EXCLUDED.event_scope,
    source_name = EXCLUDED.source_name,
    source_url = EXCLUDED.source_url,
    display_priority = EXCLUDED.display_priority,
    is_approved = EXCLUDED.is_approved,
    updated_at = now();
