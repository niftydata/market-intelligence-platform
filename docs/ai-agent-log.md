# AI Agent Development Log

This project uses an AI coding agent as an implementation assistant. Technical
decisions, source contracts, generated changes, and verification results remain
subject to human review.

## Source-selection review

The initial plan proposed Interactive Brokers for ASX market data. The agent
identified that an authenticated brokerage API and its market-data licensing
created avoidable tension with the case-study requirement to use publicly
available information. The developer accepted the recommendation to use the
explicitly permitted Yahoo Finance source instead.

Accepted contribution: source-risk analysis and recommendation.

Human decision: switch the assessed market source to Yahoo Finance while
retaining prior IBKR experience as background only.

## Incomplete generated abstraction corrected

During the first Yahoo implementation, the generated
`insert_rejected_records` database helper hardcoded the source name as
`yahoo_finance`. This worked for the first source but was incomplete as a shared
pipeline abstraction: using it for RBA would have incorrectly labelled RBA
quality failures as Yahoo records.

How the problem was identified: while implementing the second source, the
developer and agent reviewed the helper's assumptions against the RBA
requirements and found the source-specific constant.

Correction: the helper now requires an explicit `source_name`, and both Yahoo
and RBA pipelines pass their own value. Database verification confirmed that
RBA missing values are recorded as `reserve_bank_of_australia`.

Guardrail: shared infrastructure helpers must not infer source identity. Source
identity is explicit at each pipeline call site and is verified through tests
and persisted audit records.

## Source quality findings

The agent did not silently clean incomplete latest-period records:

- Yahoo returned a partial latest row without a closing value.
- RBA F1 returned a dated row without a cash-rate value.

Both were retained in `control.rejected_record`, their pipeline runs completed
with warnings, and only complete records entered raw tables.

## Dashboard iteration for the intended audience

The case study requires a single view for financially literate, non-technical
management. The agent's initial design space included additional navigation,
filters, and operational detail. These were deliberately excluded because they
would compete with the management question and increase demo risk.

Accepted contribution:

- a four-indicator executive summary;
- a visible, plain-language RAG interpretation;
- one combined market, rolling-average, and cash-rate chart;
- a separate volatility watch panel with the actual thresholds;
- a deterministic narrative that distinguishes correlation or divergence from
  causation;
- concise freshness and source disclosures.

Human guardrails:

- retain the required 90-day focus;
- use index price because index volume is not consistently reliable;
- keep transformations outside Streamlit;
- show no trading recommendation;
- expose the RAG methodology rather than presenting an unexplained colour.

Verification: the dashboard is executed against PostgreSQL with Streamlit's
testing framework, and the deployed process exposes a successful health
endpoint before release.

## Grounded AI assistant and numerical correction

The Microsoft Foundry prompt agent initially produced a directionally incorrect
statement: it described an ASX 200 move from 7,789.7 to 8,617.1 as a fall. The
human reviewer rejected that output rather than treating fluent text as valid
analysis.

Correction: deterministic tools were added for snapshots, period comparisons,
volatility relationships and cross-measure correlations. The tools calculate
dates, direction, absolute change, percentage change, sample size and caveats
from curated data. Agent instructions require these tools for quantitative
claims and prohibit treating correlation or event timing as causation.

Accepted contribution: conversational explanation and synthesis over governed
tool results.

Human override: ungrounded arithmetic and directional interpretation were not
accepted. The corrected agent definition was versioned and tested before use.

## Hosted-source constraint discovered through testing

The coding agent helped add an authenticated end-to-end refresh with stage-level
counts and concise failure reporting. Live testing then showed that the RBA
source returned HTTP 403 when called from the Singapore-hosted Render service.

Human decision: retain Singapore hosting for the dashboard and database, but run
scheduled RBA ingestion from an Australian always-on PC using the external
Render PostgreSQL connection. The web refresh remains isolated and a failed
source stage cannot replace the last validated curated dataset.

This was accepted as an operational constraint and documented as a design
trade-off rather than hidden with scraping workarounds or disabled validation.

## Context events and timezone review

The agent proposed source-cited market-context annotations and used authoritative
web sources to verify neutral event names and dates. The human accepted a sparse,
governed catalogue but required China-specific events because of Australia's
commodity and regional-market exposure.

The first implementation used calendar dates. Review identified that this was
insufficient for US announcements after the ASX close and for weekend events.
The design was corrected to store UTC timestamps where defensible, convert them
through `Australia/Sydney`, and map them to the first eligible ASX close. A
reviewed effective-market-date override is used when sources do not provide a
defensible timestamp. Tooltips disclose both the event time and plotted session.

Live database validation also showed that treating every change in the observed
RBA overnight cash-rate series as an event created noise. The rule was corrected
to annotate only movements of at least 0.10 percentage points.

Accepted contribution: candidate research, schema implementation, chart
annotation and automated tests.

Human guardrails: sources must be retained, no causal claim is inferred, display
count is capped, applied migrations are immutable, and ambiguous timing is made
explicit rather than assigned false precision.

## Verification and use boundaries

The coding agent was used to inspect the repository, edit Python/SQL/Markdown,
run linting and tests, validate migrations against PostgreSQL, and investigate
documented external APIs. Generated changes were reviewed against live data and
revised when tests exposed incorrect assumptions.

AI was not given authority to make investment recommendations, bypass source
controls, weaken quality rules, publish secrets, or grant itself production
access. Runtime AI is authenticated, tool-scoped and non-critical: if Foundry is
unavailable, the validated dashboard remains operational.
