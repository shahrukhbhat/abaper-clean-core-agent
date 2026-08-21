# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **ABAP Clean Core Compliance Agent** — a Python AI agent (A2A protocol) that classifies custom ABAP code against SAP Clean Core Levels A–D, delivers extensibility verdicts (Key User / On-Stack / Side-by-Side), and generates selectable-depth remediation guidance for S/4HANA migration teams.

The top-level `solution.yaml` declares the solution; `assets/abap-clean-core-agent/asset.yaml` declares the agent asset. All agent code lives under `assets/abap-clean-core-agent/app/`.

## Key Commands

All test and development commands are run from the **asset root** (`assets/abap-clean-core-agent/`), not the project root:

```bash
# Run the agent locally
python app/main.py

# Run all tests (always from asset root, no extra flags)
cd assets/abap-clean-core-agent && pytest

# Validate instrumentation
grep -r "M[0-9]\.achieved" assets/abap-clean-core-agent/app/

# Validate agent decorators (must return exactly 4)
grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/abap-clean-core-agent/app/agent.py

# Verify test report exists after pytest
ls assets/abap-clean-core-agent/test_report.json
```

## Developer Setup

The Claude Code skills under `.claude/skills/` are **not committed** — they are per-developer and initialized via the SAP Joule Studio `jl` CLI. A new contributor should install `jl` and run its skill-init command to populate `.claude/skills/` locally. Pinned CLI version: `jl v0.1.20-alpha.8`. Per-developer settings (`.claude/settings.local.json`) are covered by the global gitignore. See `specification/guidelines-agent.md` → "Skill Usage Policy" for how these skills relate to our canonical MTA deployment path.

## Architecture

The agent runs as an A2A Starlette HTTP server (port 5000) with these layers:

- **`main.py`** — entry point; initialises telemetry via `auto_instrument()` (must be first import), builds the A2A server with `AgentCard`/`AgentSkill`, adds `JWTContextMiddleware` to propagate bearer tokens per-request.
- **`agent_executor.py`** — `AgentExecutor` wired into the A2A `DefaultRequestHandler`; delegates to the agent graph.
- **`agent.py`** — LangGraph agent graph; exactly four decorated functions (`@agent_model`, `@agent_config` ×2, `@prompt_section`). Business logic is extracted into `_run_agent()` helpers — never inside `stream()` generators — to allow safe OpenTelemetry span instrumentation.
- **`mcp_tools.py`** — wraps MCP tool discovery; `get_mcp_tools()` is called lazily. MCP tool names are resolved dynamically at runtime — never hard-coded.
- **`mcp_auth.py`** — XSUAA service-to-service token manager; caches tokens with 3600 s TTL, proactively refreshes when < 60 s remain, retries once on HTTP 401.

Core processing pipeline modules under `app/`:

| Module | Responsibility |
|---|---|
| `scope_parser.py` | Parses package names, transport requests (`<SID>K<6-digit>`), or object lists into a normalised `Scope` dataclass |
| `tools/retrieve_objects.py` | Calls MCP `read`/`readcontent` tools; returns `ABAPObject` list with `retrieval_status` |
| `classification/engine.py` | Rule-based pre-classifier (regex patterns on ABAP source); only calls LLM for ambiguous cases |
| `classification/rules_config.py` | Loads versioned rules from `app/skills/clean-core-classification/references/clean-core-rules.md`; supports edition overrides |
| `extensibility/verdict.py` | Maps classified objects to `KEY_USER` / `ON_STACK` / `SIDE_BY_SIDE` using RICEFW decision logic |
| `remediation/generator.py` | Generates guidance at three depths: `principle` (doc link), `api` (replacement API), `code` (refactored snippet with disclaimer) |
| `output/views.py` | Renders Developer / Architect / Governance views from a single `AnalysisResult` object |
| `output/report_writer.py` | Writes `clean-core-<scope_id>-<timestamp>.json` and `.md` to `./reports/` |

Runtime skills (loaded on demand via `load(path)` tool):
- `app/skills/clean-core-classification/SKILL.md` + `references/clean-core-rules.md`
- `app/skills/extensibility-guidance/SKILL.md` + `references/ricefw-patterns.md`
- `app/skills/remediation-templates/SKILL.md`

## Critical Constraints

**SAP API access**: All ABAP system calls go through the `ai-abaper-mcp` MCP server. Never call SAP APIs directly via `requests`, `httpx`, or OData clients.

**Agent decorators**: `app/agent.py` must have exactly 4 decorator usages (`@agent_model`, `@agent_config` ×2, `@prompt_section`). Never add new decorated functions.

**LangGraph**: Do not use `create_react_agent` (deprecated in LangChain 1.0). Use `from langchain.agents import create_agent`.

**OpenTelemetry**: Never use `with tracer.start_as_current_span(...)` inside an async generator (any method with `yield`). Instrument `_run_agent()` helpers instead.

**Tests**: All LLM and MCP calls must be mocked. `conftest.py` sets `IBD_TESTING=true` and monkey-patches `mcp_tools.get_mcp_tools` — do not branch on this env var in application code. Run `pytest` from asset root with no extra flags; coverage must be ≥ 70%.

**No `.env` files**: Environment variables (`XSUAA_URL`, `XSUAA_CLIENT_ID`, `XSUAA_CLIENT_SECRET`, `XSUAA_XSAPPNAME`, `AGENT_PUBLIC_URL`) are supplied at deployment runtime.

## Business Milestones (M1–M6)

Every pipeline stage emits structured log lines and OpenTelemetry spans. The pattern for all modules:

```python
logger.info("M3.achieved: classification complete — %d objects classified; distribution: A=%d, B=%d, C=%d, D=%d", ...)
logger.warning("M3.missed: classification incomplete — %d objects could not be classified", ...)
```

Milestones: M1=Scope Defined, M2=Code Retrieved, M3=Classification Complete, M4=Extensibility Verdict, M5=Remediation Plan, M6=Report Saved.

## Specification Workflow

The `specification/` directory drives implementation:
- `specification/specification.md` — top-level checklist (mark `- [x]` when done)
- `specification/abap-clean-core-agent/specification.md` — per-asset checklist (source of truth visible to user)
- `specification/guidelines.md` — execution rules (sequential item execution, mandatory checkbox updates)
- `specification/guidelines-agent.md` — technical constraints (canonical patterns, testing rules, validation checklist)

Mark items complete with `- [x]` in **both** specification files after finishing each section.
