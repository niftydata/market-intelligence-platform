# Optional Foundry Data Assistant

## Decision

An ad-hoc question assistant is technically feasible as a Streamlit sidebar,
but it should remain an optional preview rather than part of the assessed core
path. The dashboard must remain useful when the model endpoint is unavailable.

The selected implementation invokes prompt agent `agent-req` version 3 through
its agent-scoped Microsoft Foundry Responses endpoint. The prompt agent uses the
`gpt-5.4-mini` deployment. Its allowlisted function definitions are persisted
in the Foundry agent version, while the functions themselves run inside the
Render application. Foundry agent endpoints reject function definitions passed
dynamically in an individual response request. The requirement is grounded
question answering, not autonomous multi-step action.

## Recommended architecture

```text
Dashboard user
    |
    v
Streamlit sidebar chat
    |
    v
Microsoft Foundry prompt agent
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

## Allowlisted tools

### `get_available_date_range`

Returns the complete curated date range and available metrics.

### `get_market_snapshot`

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

Returns at most 270 validated daily observations spanning no more than 366
calendar days. Longer historical questions use deterministic period-comparison
or extreme-observation tools.

### `compare_periods`

Inputs:

- two validated date ranges.

Returns deterministic summary statistics calculated by application code.

### `get_data_freshness`

Returns the latest market, macro, curated, pipeline-run, and quality status.

### `get_extreme_observations`

Returns up to ten highest or lowest observations for an allowlisted metric
within a validated date range.

## Agent version deployment

Generate the versioned agent definition from the same instructions and schemas
used by the application:

```powershell
$env:PYTHONPATH = "src"
python scripts/generate_foundry_agent_payload.py > foundry-agent.json
```

Create a new `agent-req` version through the Foundry project REST API. Do not
include a `tools` property in subsequent calls to the deployed agent endpoint;
the endpoint resolves the latest saved agent version and returns function-call
items for the application to execute.

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
