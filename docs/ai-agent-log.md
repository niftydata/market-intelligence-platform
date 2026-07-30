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
