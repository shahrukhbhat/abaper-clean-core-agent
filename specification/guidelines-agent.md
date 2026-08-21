# Agent Guidelines

Technical constraints and patterns for building Pro-Code AI Agents. Follow these throughout specification execution.

## Tech Stack

- Python 3.13
- Agent framework defined in the `sap-agent-bootstrap` skill
- Agent2Agent (A2A) protocol
- Local execution for development/tests (in-memory storage). **Canonical deployment target: self-managed Cloud Foundry MTA + SAP AI Core / Gen AI Hub** — see the Deployment section of `specification/abap-clean-core-agent/specification.md` and `specification/plans/cf-aicore-deployment-plan.md`. The Joule Studio / Marketplace path (`solution.yaml` + `asset.yaml`) is legacy/parallel; when the two diverge, the MTA path wins.

## Project Structure

- Asset root: `assets/<asset-name>/`
- Required structure: `asset.yaml`, `app/`
- Full layout from project root: `solution.yaml`, `assets/<asset-name>/asset.yaml`, `assets/<asset-name>/app/`
- `asset.yaml` must use `buildPath: .` and `/.well-known/agent.json` for all health probes
- Follow the `sap-agent-bootstrap` skill for project scaffolding — invoke directly from `assets/<asset-name>/`, use copy commands

## Key Constraints

- When working with LangChain or LangGraph, you MUST NEVER use the `create_react_agent` function (`from langgraph.prebuilt import create_react_agent`) as it has been deprecated in LangChain 1.0. Instead, you should use the `from langchain.agents import create_agent` function. If the pinned release does not export `create_agent`, resolve the correct import (`StateGraph` from `langgraph`) and pin the matching package version — never leave a non-existent import in the code.
- **NEVER call SAP APIs directly** (no `requests`, `httpx`, or hand-rolled OData clients). All SAP API consumption MUST go through MCP servers. The agent consumes them as tools, never as raw HTTP calls.
- Only use public APIs; mock any private systems (like S/4HANA) with minimal mock data
- AI Core is available at **runtime** via LiteLLM / `set_aicore_config()` reading the bound `aicore` credentials from `VCAP_SERVICES`, but is **NOT available during tests** — all LLM calls must be mocked
- No Git operations, no documentation/READMEs
- Update `requirements.txt` for any new dependencies. `requirements.txt` is required both locally and for the CF buildpack; it MUST include everything `main.py` imports (`starlette`, `opentelemetry-instrumentation-starlette`, etc.). `sap_cloud_sdk.*` is not on public PyPI — document the private-index requirement.
- Never modify `sys.path`
- No `.env` files (environment variables supplied at runtime)

## MCP Authentication (decoupled user-identity propagation)

- The agent authenticates to the MCP via **user-identity propagation**, NOT a shared service identity. It forwards the end-user's JWT; the MCP's own XSUAA resolves the user's scopes from role-collection assignments and issues a scoped token.
- **NEVER** reintroduce the superseded client-credentials design: no `XSUAA_CLIENT_ID`/`XSUAA_CLIENT_SECRET`/`XSUAA_XSAPPNAME` env vars, no `grant_type=client_credentials`, no explicit `scope=...read ...readcontent` requests, no runtime-qualified `!t<nnn>` xsappname.
- Token exchange goes through a bound BTP **Destination service** (`Authentication: OAuth2UserTokenExchange`); `mcp_auth.py` forwards the user JWT via `X-user-token` and injects the exchanged Bearer token. Cache per-user (keyed by `sub`).
- No user JWT on the inbound request → **reject with HTTP 401** (never fall back to a service identity). MCP **403** → raise `InsufficientScopeError`, do not retry with elevated credentials, surface a user-facing message, and continue with the data the user's scopes allow.
- The agent's `xs-security.json` is minimal: its own `invoke` scope only, **no `foreign-scope-references`, no MCP scope references**.

## Deployment Constraints (CF + AI Core)

- Deliver CF buildpack artifacts: `requirements.txt`, `Procfile` (`web: python app/main.py`), `runtime.txt` (Python 3.13). `Procfile` defines the entrypoint; `runtime.txt` only sets the Python version.
- Deliver `mta.yaml` (modules + `aicore`/`xsuaa`/`destination` resources) and the agent `xs-security.json`.
- **Pin `instances: 1`** in the MTA module — `main.py` uses `InMemoryTaskStore()`, which is not shared across instances. A persistent store (Redis/HANA) is required before horizontal scaling.
- The app must start (serve `/.well-known/agent.json` → 200) before real agent logic exists — stub `agent_executor.py` / `mcp_tools.py` for a deploy-skeleton milestone if needed, since `main.py` imports them at startup.

## Skill Usage Policy (jl CLI / Joule Studio skills)

The `.claude/skills/` skills (authored by `sap-joule-studio`) assume the **Joule Studio runtime** deployment path. Use them for scaffolding and structure, but our canonical deployment and auth model **override** their Joule-runtime assumptions. Apply this policy wherever a spec item invokes one of these skills.

**Use as-is (aligned — no override needed):**
- `sap-agent-bootstrap` — for scaffolding the agent code (`main.py`, `agent.py`, `mcp_tools.py` indirection layer, decorator template). Its "Known Deployment Gotchas" (`set_aicore_config()` + `auto_instrument()` first; async-lazy `get_mcp_tools()`; peer-level imports) apply to our CF path too.
- `setup-solution` — for the `solution.yaml` + `asset.yaml` structure and asset naming/ORD-ID rules (still needed; A2A health probes at `/.well-known/agent.json` match our `asset.yaml`).
- `mcp-mock-config`, `sap-agent-instrumentation`, `mcp-translation-file`, `product-requirements-document`, `intent-analysis`, `sap-aeval-*`, `specification` — orthogonal to deployment/auth; use normally.

**Override after use (Joule assumptions must NOT leak in):**
- **`sap-agent-bootstrap` auth wiring** — the template scaffolds a Joule-runtime agent whose MCP/token wiring assumes the platform's identity handling. After scaffolding, **replace it with our decoupled Destination / JWT-bearer model** (see the MCP Authentication section and the `mcp_auth.py` items in the asset spec). Do not keep any client-credentials / service-identity token logic the template may imply. This is a required post-bootstrap step.
- **`sap-agent-bootstrap` dependency note** — the skill says deps are installed "in the cluster via CI/CD" and not locally. For our path, `requirements.txt` is a real deliverable that must be complete for both the CF buildpack and local test runs (`pip install -r requirements.txt`).

**Do NOT use for deployment (conflicts with canonical MTA path):**
- **`deploy-solution` and `joule-studio-cli`** — these deploy via the `deploy_solution` tool / `jl` CLI to Joule runtime. Our **canonical deployment is `mbt build` + `cf deploy`** per the asset spec's Deployment section. Do NOT invoke `deploy-solution`/`jl` for the canonical path. They remain available **only** for the legacy/parallel Joule Studio path, if that path is ever exercised. When following the canonical path, do not reference `jl`/`deploy_solution` in commands or summaries.

## Code Quality

- All Python code must compile with valid imports
- No `src.` import patterns
- All function parameters must be used in function body

## Agent Decorators

- The bootstrap template already includes decorator scaffolding — no separate skill invocation needed
- **NEVER add new decorated functions to `app/agent.py`** — the four from the bootstrap template (`@agent_model`, `@agent_config` for temperature and agent memory ttl, `@prompt_section`) are the complete and final set.
- Never mark decorator tasks complete until `sap_cloud_sdk.agent_decorators` imports exist in `app/agent.py`

## Agent Instrumentation

- ALL business logic steps MUST be instrumented with proper logging and OpenTelemetry spans
- Use milestones from the PRD's "Milestones" section for business step instrumentation
- Each milestone must emit structured log statements on achievement and miss
- Log pattern: `[MILESTONE_ID].[achieved|missed]: [description]`
- Add OpenTelemetry custom spans for each business step using `tracer.start_as_current_span`
- **NEVER use `with tracer.start_as_current_span(...)` as a context manager inside an async generator** (any method containing `yield`). Extract all business logic into a plain async helper method (e.g. `_run_agent()`) and instrument that helper, then call it from `stream()` and yield the result outside any span context.
- Ensure `auto_instrument()` is called at top of `main.py` before any AI framework imports

## MCP Tool Integration

All SAP API integrations MUST use this pattern.

MCP tool names are prefixed with an MCP server identifier at runtime. **Never hard-code tool names in code.** Retrieve tools dynamically via `get_mcp_tools()` and let the agent resolve them by capability, not by name.

### Canonical Pattern

```python
from mcp_tools import get_mcp_tools

async def _load_tools() -> list:
    return await get_mcp_tools()
```

Call `_load_tools()` lazily (not in `__init__`). Wire the result into the agent graph:

```python
class MyAgent:
    def __init__(self):
        self._tools = None

    async def _get_tools(self) -> list:
        if self._tools is None:
            self._tools = await _load_tools()
        return self._tools

    async def stream(self, query, context_id, ext_impl=None):
        tools = await self._get_tools()
        graph = self._build_graph(tools, system_prompt=get_system_prompt())
        ...
```

### Local Testing (IBD_TESTING)

**Do NOT branch on `IBD_TESTING` in application code.** The `conftest.py` monkey-patches `mcp_tools.get_mcp_tools` before any agent code runs.

## Runtime Skills

If the agent requires complex task-specific instructions or reference material that doesn't belong in the system prompt, create them as runtime skills under `app/skills/<skill-name>/SKILL.md`. Skills can also ship companion asset files alongside `SKILL.md`. The agent loads all runtime skills on demand via the `load(path)` tool.

## Testing

Working directory for all test operations: `assets/<asset-name>/` (asset root).

- All generated tests go in `assets/<asset-name>/tests/` (NOT inside `app/`)
- Unit tests: exactly one per tool; run each immediately after writing
- Integration test: one end-to-end test exercising the full agent graph
- **AI Core / LLM calls MUST be mocked in all tests.**
- Mock all external systems (S/4HANA, MCP servers, AI Core) — tests must run offline
- ALWAYS invoke as just `pytest` from asset root — no paths, no `--cov`, no `--json-report`, no extra flags
- Coverage must be ≥ 70%
- Final `pytest` run (no args) MUST produce `test_report.json`

## Validation Checklist

```bash
# Instrumentation
grep -r "M[0-9]\.achieved" assets/abap-clean-core-agent/app/     # must return results

# Decorators
grep -r "sap_cloud_sdk.agent_decorators" assets/abap-clean-core-agent/app/  # must return results
grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/abap-clean-core-agent/app/agent.py  # must return 4

# Test report
ls assets/abap-clean-core-agent/test_report.json                  # must exist
```
