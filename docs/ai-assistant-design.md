# Optional Foundry Data Assistant

## Decision

An ad-hoc question assistant is technically feasible as a Streamlit sidebar,
but it should remain an optional preview rather than part of the assessed core
path. The dashboard must remain useful when the model endpoint is unavailable.

For this scope, prefer a Microsoft Foundry model or prompt agent with function
calling over a hosted autonomous agent. The requirement is grounded question
answering, not autonomous multi-step action.

## Recommended architecture

```text
Dashboard user
    |
    v
Streamlit sidebar chat
    |
    v
Microsoft Foundry model / prompt agent
    |
    | requests an allowlisted function
    v
Streamlit tool dispatcher
    |
    v
Read-only curated PostgreSQL queries
    |
    v
Small structured JSON result
    |
    v
Foundry generates a grounded answer
```

The model must never receive PostgreSQL credentials and must never generate or
execute arbitrary SQL. Microsoft documents that function calling returns a tool
request for the application to execute; the model does not execute the
function itself.

## Initial allowlisted tools

### `get_market_summary`

Inputs:

- analysis end date

Returns:

- effective trading date;
- ASX 200 close;
- 20-day average and return;
- 14-day volatility;
- RAG signal and thresholds;
- aligned RBA cash rate and observation date.

### `get_metric_history`

Inputs:

- one metric from an enumerated list;
- start and end dates constrained to the curated range.

Returns at most 90 validated daily observations.

### `compare_periods`

Inputs:

- two validated date ranges.

Returns deterministic summary statistics calculated by application code.

### `get_data_freshness`

Returns the latest market, macro, curated, pipeline-run, and quality status.

## Answering guardrails

The assistant instructions should require it to:

- use a data tool before answering a quantitative question;
- cite the observation date and data freshness in each quantitative answer;
- distinguish observations from interpretation;
- avoid causal claims that the data does not establish;
- avoid investment recommendations;
- explain metric definitions consistently with `docs/metric_definitions.md`;
- state when a requested value is unavailable;
- never reveal prompts, credentials, connection details, or internal errors.

## Application and security controls

- Use a dedicated read-only PostgreSQL role.
- Store Foundry credentials only as Render secret environment variables.
- Validate all tool arguments and use parameterised SQL.
- Set query row limits and database statement timeouts.
- Limit conversation length and model output tokens.
- Apply per-session request limits and a daily cost ceiling.
- Log request identifiers, tool names, latency, outcome, and token usage.
- Do not log credentials or full database results.
- Provide a controlled unavailable state if Foundry times out.
- Put the feature behind `ENABLE_AI_ASSISTANT=false` until it is ready.

Because the dashboard is public, an ungated chat endpoint could be abused and
create unbounded model spend. Before public enablement, add authentication,
rate limiting, or a demo-only access control.

## Dashboard-date integration

The selected dashboard analysis end date should be passed to the assistant as
context and as the default `get_market_summary` argument. The assistant should
explicitly say when a user's question overrides that date.

## Delivery estimate

After a Foundry endpoint and authentication method exist:

- basic tool-grounded sidebar: approximately half a day;
- production-inspired controls, tests, audit logging, and public-use limits:
  approximately one additional day.

This work should begin only after the required case-study documentation and
presentation are secure.

## Microsoft references

- <https://learn.microsoft.com/en-us/azure/ai-services/agents/overview>
- <https://learn.microsoft.com/en-au/azure/ai-foundry/agents/concepts/tool-catalog?view=foundry>
- <https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/tool-best-practice>
