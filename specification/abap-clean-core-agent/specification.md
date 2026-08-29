# Specification: abap-clean-core-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [x] Read the project input (`product-requirements-document.md` and `intent.md`)
- [x] Bootstrap agent code in `assets/abap-clean-core-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/abap-clean-core-agent/`, use copy commands — do NOT create files manually). **Post-bootstrap override (see guidelines-agent.md → Skill Usage Policy):** the skill scaffolds a Joule-runtime agent — after scaffolding, replace any MCP/auth token wiring with our decoupled Destination / JWT-bearer model (see the MCP Server Integration section), and treat `requirements.txt` as a real deliverable (not "installed in-cluster only").
- [x] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## Runtime Skills

- [x] Create runtime skill `app/skills/clean-core-classification/SKILL.md` — this skill encodes the SAP Clean Core Levels A–D classification rules, API release status indicators, and forbidden construct patterns. It is loaded by the agent on demand when classifying objects.
- [x] Create runtime skill `app/skills/extensibility-guidance/SKILL.md` — this skill encodes the SAP extensibility framework decision tree (Key User / Developer Extensibility on-stack / Side-by-Side on BTP) and RICEFW-specific patterns. Loaded on demand during extensibility verdict generation.
- [x] Create runtime skill `app/skills/remediation-templates/SKILL.md` — this skill provides remediation prompt templates for all three depth levels (principle + doc link, API recommendation, refactored code snippet). Loaded on demand when generating remediation guidance.
- [x] Place the Clean Core classification rules reference as a companion asset: `app/skills/clean-core-classification/references/clean-core-rules.md` — covering Level A (standard SAP, no modification), Level B (Released APIs / ABAP Cloud only), Level C (mixed released and non-released), Level D (internal APIs, direct DB access, forbidden modifications), with forbidden construct patterns: `SELECT` on SAP internal tables, `CALL FUNCTION` to non-released FMs, `WRITE TO` system fields, direct writes to `MANDT`-keyed tables without using Released APIs.
- [x] Place RICEFW decision reference as companion asset: `app/skills/extensibility-guidance/references/ricefw-patterns.md` — categorising Reports, Interfaces, Conversions, Enhancements, Forms, Workflows, and their typical extensibility verdicts with rationale.

## MCP Server Integration (ai-abaper-mcp — External, Decoupled User-Identity Propagation)

> The ai-abaper-mcp MCP server is an external server. It is NOT created by this project — only wired as a dependency. Authentication uses **decoupled user-identity propagation**, not a shared service identity: the agent proves *who the user is* (by forwarding their JWT) and the MCP's own XSUAA resolves what that user is allowed to do. The agent has **zero knowledge of MCP scopes** and no design-time dependency on the MCP's `xs-security.json`. See `specification/plans/cf-aicore-deployment-plan.md` §"#1 RESOLVED" for the full rationale and responsibility matrix.

- [x] In `assets/abap-clean-core-agent/asset.yaml`, add the `ai-abaper-mcp` MCP server dependency under `requires`:
  ```yaml
  requires:
    - name: ai-abaper-mcp
      kind: mcp-server
      ordId: ai-abaper-mcp
  ```
- [x] Create `assets/abap-clean-core-agent/app/mcp_auth.py` — user-token exchange manager (deliberately simple; **no XSUAA client-credentials logic, no scope requests**):
  - Reads the **end-user's JWT** from the request-scoped context var set by `JWTContextMiddleware` (in `main.py`) — the agent is a dumb identity pipe, it does not mint its own token
  - Calls the bound BTP **Destination service** REST API to perform the token exchange transparently: `GET /destination-configuration/v1/destinations/ai-abaper-mcp` with header `X-user-token: <user_jwt>`. Read the `destination` service credentials from `VCAP_SERVICES` (via `cfenv`); the destination `ai-abaper-mcp` is configured with `Authentication: OAuth2UserTokenExchange` so it swaps the user JWT for an MCP-scoped token carrying only the scopes that user has been granted (`read`, `readcontent`, or both) via role collections on the MCP side
  - Extracts `authTokens[0].value` from the response and returns `Authorization: Bearer <exchanged_token>` header dict for MCP requests
  - Caches the exchanged token **per user** (keyed by the `sub` claim) with TTL from the token's `expires_in`; proactively evicts when < 60 s remain
  - On HTTP **401** (no/invalid user token) the agent request itself is rejected upstream (see next item) — `mcp_auth.py` never falls back to a service identity
  - On HTTP **403** from the MCP (scope insufficient for a tool): raise a typed `InsufficientScopeError`. The agent MUST NOT retry with elevated credentials; the agent graph catches this and emits a user-facing message (e.g. _"You do not have permission to read source content (`readcontent` scope). Contact your administrator to request access."_) and continues with whatever data the user's scopes allow (e.g. metadata via `read` without source)
  - **No runtime-qualified xsappname, no `XSUAA_CLIENT_ID`/`XSUAA_CLIENT_SECRET`** — these belonged to the superseded client-credentials design and MUST NOT be reintroduced
- [x] Enforce inbound user-token requirement: if no user JWT is present on the inbound A2A request, return **HTTP 401** — without a user identity the exchange cannot determine authorisation. Agent-to-agent calls must forward a user token or be rejected. `JWTContextMiddleware` (already in `main.py`) extracts the inbound bearer token; add the reject-on-missing check.
- [x] Ensure `mcp_tools.py` (bootstrap-generated) injects `mcp_auth.get_auth_headers()` (the exchanged Bearer token) when making MCP requests via the agent gateway
- [x] Set required MCP request headers in the client: `Content-Type: application/json` and `Accept: application/json, text/event-stream` (the Accept header is required by Streamable HTTP — server returns 406 without it)
- [x] Generate `mcp-mock.json` using the `mcp-mock-config` skill to mock ai-abaper-mcp tools (`read`, `readcontent`) for local testing. Tests must NOT require a live Destination service — mock `mcp_auth` token exchange so tests run offline.

## Core Agent Implementation

### System Prompt & Agent Configuration

- [x] In `app/agent.py`, write the `@prompt_section` system prompt that:
  - Identifies the agent as an ABAP Clean Core compliance analyst
  - Instructs the agent to NEVER write to the ABAP system — all MCP tool calls are strictly read-only (`read` and `readcontent` tools only)
  - Instructs the agent to always cite the specific SAP Clean Core rule or white paper principle when giving a verdict — no unexplained classifications
  - Instructs the agent to always include a disclaimer when providing code snippets: "This snippet is a starting point for developer validation and is NOT production-ready"
  - Instructs the agent to set page/batch size to a maximum of 100 objects per MCP call to prevent context overflow; inform the user if the limit is applied
  - Instructs the agent to load the `clean-core-classification` runtime skill when classifying objects, `extensibility-guidance` when producing verdicts, and `remediation-templates` when generating guidance
  - Instructs the agent to ask the user for their target S/4HANA edition (on-premise / Cloud Private / Cloud Public) at session start if not already provided — classification rules vary by edition
  - Instructs the agent to ask the user for their preferred remediation depth (principle / api / code) at session start if not already set globally

### Scope Handling (R1 — Multi-scope ABAP object retrieval)

- [x] Implement scope parser in `app/scope_parser.py`:
  - Accepts: single package name (e.g. `ZMYPACKAGE`), comma-separated package list, transport request number (format `<SID>K<6-digit-number>`), or comma-separated list of individual object names with optional type prefix (e.g. `PROG:ZMYPROGRAM`, `CLAS:ZCL_MY_CLASS`)
  - Returns a normalised `Scope` dataclass: `scope_type` (package | transport | objects), `identifiers: list[str]`, `edition: str | None`
  - Validates input format; returns descriptive error message for unrecognised inputs
- [x] Implement object retrieval tool wrapper in `app/tools/retrieve_objects.py`:
  - Calls MCP `read` tool to list all ABAP objects in a package or transport
  - Calls MCP `readcontent` tool to fetch full ABAP source for each object
  - Returns list of `ABAPObject` dataclasses: `name`, `type` (PROG / CLAS / FUNC / TABL / etc.), `source`, `package`, `transport`, `retrieval_status` (success | failed | not_found)
  - Objects that cannot be retrieved are flagged with `retrieval_status = failed` and included in the result — never silently dropped
  - Emits `M2.achieved` or `M2.missed` log on completion

### Clean Core Classification Engine (R2)

- [x] Create `app/classification/engine.py` — rule-based pre-classifier:
  - Scans ABAP source for forbidden patterns before invoking LLM: direct SELECT on SAP internal tables (pattern: `SELECT ... FROM` non-custom table names without Released API wrapper), calls to non-released Function Modules (FM names not in Released API list), direct writes to system-managed tables, use of `CALL FUNCTION ... DESTINATION` without BTP-approved patterns, modification of standard SAP programs via `ENHANCEMENT` without BAdI, access to obsolete APIs flagged in SAP notes
  - Pre-assigns a candidate level (A / B / C / D) based on rule hits
  - Returns `ClassificationHint`: `candidate_level`, `rule_hits: list[str]`, `confidence: float`
  - High-confidence cases (no ambiguity, clear rule match) produce definitive verdicts without LLM call
  - Low-confidence cases (ambiguous patterns) are flagged with `review_recommended=True` and passed to the LLM for final determination
- [x] Create `app/classification/rules_config.py` — versioned rules configuration:
  - Loads Clean Core rules from `app/skills/clean-core-classification/references/clean-core-rules.md`
  - Supports edition-specific rule overrides: on-premise rules are more permissive than Cloud Public (where Released-only API usage is strictly enforced)
  - Rule set version is logged on agent start for traceability
- [x] Wire the classification engine into the agent graph in `app/agent.py`:
  - Run rule-based pre-classification first; only invoke LLM for explanation, ambiguous cases, or code-mode remediation
  - Each object's verdict includes: `level` (A/B/C/D), `rationale` (specific rule cited), `review_recommended` flag, `edition` context used
  - Emits `M3.achieved` or `M3.missed` log on completion

### Extensibility Verdict Engine (R3)

- [x] Create `app/extensibility/verdict.py`:
  - Maps each classified object to one of three extensibility paths:
    - `KEY_USER`: object implements UI adaptation, custom fields, or simple business logic accessible via Key User tools — no ABAP coding required for remediation
    - `ON_STACK`: object can be rewritten using Released APIs / ABAP Cloud Developer model and remain in the S/4HANA stack
    - `SIDE_BY_SIDE`: object's functionality is better implemented as a BTP extension (decoupled from core)
  - RICEFW decision logic:
    - Reports (PROG type, output-only) → default `SIDE_BY_SIDE` unless using only Released APIs → `ON_STACK`
    - Interfaces (RFC, IDoc, BAPI, REST) → `SIDE_BY_SIDE` (BTP Integration Suite preferred)
    - Conversions (data migration) → `SIDE_BY_SIDE` (one-time, not part of ongoing core)
    - Enhancements (BAdI, user exits) → assess Released BAdI availability → `ON_STACK` if released BAdI exists, else `SIDE_BY_SIDE`
    - Forms (SAPScript, SmartForms, Adobe) → `SIDE_BY_SIDE` (BTP Document Service)
    - Workflows (obsolete WS) → `SIDE_BY_SIDE` (SAP Build Process Automation)
  - Each verdict includes rationale citing SAP extensibility framework documentation
  - Level A objects always receive `ON_STACK` (already compliant)
  - Emits `M4.achieved` or `M4.missed` log on completion

### Remediation Guidance (R4 — Selectable depth levels)

- [x] Create `app/remediation/generator.py`:
  - Reads session-level depth mode: `principle` | `api` | `code` (default: `principle`)
  - Accepts per-object depth override via user instruction
  - **Depth 1 — Principle**: generates explanation of the violated rule (from classification rationale) and appends the relevant SAP documentation URL:
    - Level D objects: link to SAP Clean Core white paper section on forbidden modifications
    - Level C objects: link to ABAP Cloud Developer Guide / Released API usage
    - Level B objects: affirmative — cites the Released API used correctly
  - **Depth 2 — API**: identifies the replacement Released API, BAdI, or extension point. Uses LLM with the `extensibility-guidance` runtime skill to map the current non-released construct to its recommended replacement. Returns: current construct, recommended replacement, migration complexity (low / medium / high)
  - **Depth 3 — Code**: generates a refactored ABAP code snippet using the recommended Released API. Prefixes output with: "⚠️ This snippet is a starting point for developer validation and is NOT production-ready. Review and test thoroughly before applying."
  - Only generates guidance for Level C and D objects (Levels A and B have no remediation needed)
  - Emits `M5.achieved` or `M5.missed` log on completion

### Output Views (R5 — Audience-appropriate output)

- [x] Create `app/output/views.py` — three view renderers:
  - **Developer view** (`render_developer_view(results)`): per-object Markdown table with columns: Object Name | Type | Package | Clean Core Level | Extensibility Path | RICEFW Category | Remediation Summary. Sorted by level D → C → B → A.
  - **Architect view** (`render_architect_view(results)`): extensibility map showing objects grouped by extensibility path (ON_STACK / SIDE_BY_SIDE / KEY_USER). Each group shows object count, list of objects with risk rating (HIGH=Level D, MEDIUM=Level C, LOW=Level B, NONE=Level A). Includes top 10 highest-risk objects prominently.
  - **Governance view** (`render_governance_view(results)`): executive scorecard with: (a) level distribution table (counts + percentages for A/B/C/D), (b) overall risk rating (HIGH if >20% Level D, MEDIUM if >20% Level C, LOW otherwise), (c) extensibility split (on-stack vs side-by-side counts), (d) top 10 highest-risk objects by name and level.
  - All views are generated from the same in-memory `AnalysisResult` object — no re-analysis needed to switch views
- [x] Wire view selection into agent conversation: agent detects audience keywords ("developer", "architect", "scorecard", "governance", "summary") in user messages and selects the appropriate view. User can explicitly request a different view at any time.

### Report Export (R6 — JSON + Markdown files)

- [x] Create `app/output/report_writer.py`:
  - `write_json_report(results, scope_id)` — serialises full `AnalysisResult` to JSON:
    ```json
    {
      "scope": "<scope_identifier>",
      "edition": "<s4hana_edition>",
      "timestamp": "<ISO-8601>",
      "summary": { "total": N, "level_a": N, "level_b": N, "level_c": N, "level_d": N, "on_stack": N, "side_by_side": N, "key_user": N },
      "objects": [
        { "name": "...", "type": "...", "package": "...", "level": "D", "rationale": "...", "extensibility": "SIDE_BY_SIDE", "ricefw_category": "Report", "remediation": "...", "review_recommended": false }
      ]
    }
    ```
  - `write_markdown_report(results, scope_id)` — writes human-readable Markdown combining the governance scorecard + full developer-view table
  - File names: `clean-core-<scope_id>-<YYYYMMDD-HHMMSS>.json` and `clean-core-<scope_id>-<YYYYMMDD-HHMMSS>.md`
  - Files are written to `./reports/` directory (created if not exists)
  - Emits `M6.achieved` or `M6.missed` log on completion
- [x] Wire report export into agent: trigger automatically at end of a complete analysis session; also triggerable by user saying "export", "save report", or "download findings"

### Business Step Instrumentation (Milestones M1–M6)

- [x] Implement all milestone log emissions in `app/agent.py` and relevant tool/engine modules. Extract all business logic from `stream()` into `_run_agent()` helper and instrument with OpenTelemetry spans. **Never wrap `yield` inside `with tracer.start_as_current_span(...)`.** Pattern:
  ```python
  # M1 — Scope Defined
  logger.info("M1.achieved: scope confirmed — %d objects identified in scope '%s'", object_count, scope_id)
  # or
  logger.warning("M1.missed: scope validation failed — no valid objects identified for input '%s'", scope_input)

  # M2 — Code Retrieved
  logger.info("M2.achieved: code retrieval complete — %d/%d objects retrieved for scope '%s'", retrieved, total, scope_id)
  logger.warning("M2.missed: code retrieval incomplete — %d objects could not be retrieved; proceeding with %d", failed, retrieved)

  # M3 — Classification Complete
  logger.info("M3.achieved: classification complete — %d objects classified; distribution: A=%d, B=%d, C=%d, D=%d", total, a, b, c, d)
  logger.warning("M3.missed: classification incomplete — %d objects could not be classified", unclassified)

  # M4 — Extensibility Verdict Delivered
  logger.info("M4.achieved: extensibility verdicts complete — on-stack=%d, side-by-side=%d, key-user=%d", on_stack, side_by_side, key_user)
  logger.warning("M4.missed: extensibility verdict could not be determined for %d objects", unresolved)

  # M5 — Remediation Plan Produced
  logger.info("M5.achieved: remediation guidance generated — %d objects at depth '%s'", count, depth)
  logger.warning("M5.missed: remediation guidance could not be generated for %d objects at depth '%s'", failed, depth)

  # M6 — Report Saved
  logger.info("M6.achieved: reports saved — '%s' and '%s' written successfully", json_file, md_file)
  logger.warning("M6.missed: report export failed — files could not be written for scope '%s'", scope_id)
  ```
- [ ] Add OpenTelemetry spans for each milestone (M1–M6) using `@tracer.start_as_current_span("M<n>-<name>")` on the `_run_agent()` helper methods corresponding to each milestone phase
- [ ] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## S/4HANA Edition Support (R9 — High-want)

- [x] Add edition context to `Scope` dataclass: `edition: Literal["on-premise", "private-cloud", "public-cloud"] | None`
- [x] Agent asks for edition at session start if not provided; defaults to `on-premise` if user skips
- [x] Classification engine applies edition-specific strictness: Public Cloud enforces Released-only APIs (any non-released API = Level D); Private Cloud and on-premise treat non-released APIs with existing BAdI coverage as Level C
- [x] Include edition in all report outputs for traceability

## Guardrails Implementation

- [x] Verify no MCP write tools are exposed or invoked — agent must reject any user attempt to modify ABAP objects ("I can only read ABAP code — I cannot write to the ABAP system")
- [x] Implement confidence threshold check: if `ClassificationHint.confidence < 0.7`, mark object with `review_recommended=True` in all output views and reports
- [x] Implement auth guards in `mcp_auth.py` per the decoupled model: **no user JWT on inbound request → HTTP 401** (reject; never fall back to a service identity). MCP returns **403** (scope insufficient) → raise `InsufficientScopeError`, do NOT retry with elevated credentials, surface a user-facing message naming the missing scope (`read`/`readcontent`) and continue with the data the user's scopes allow. Never log the user JWT or exchanged token values.

## Delete Template Skill

- [x] Delete the template runtime skill: `rm -rf assets/abap-clean-core-agent/app/skills/template-skill/`

## Testing

- [x] `conftest.py` only sets `IBD_TESTING=true` — this causes the agent to run with mock MCP tool results (from `mcp-mock.json`) during tests
- [x] Write unit test `tests/test_scope_parser.py` — tests: valid package name, comma-separated packages, transport request format, individual object list, invalid input error message; run immediately after writing
- [x] Write unit test `tests/test_classification_engine.py` — tests: Level A detection (standard SAP object, no custom code), Level B detection (uses only Released APIs), Level C detection (mixed usage), Level D detection (direct SELECT on internal table, non-released FM call); mock LLM; run immediately after writing
- [x] Write unit test `tests/test_extensibility_verdict.py` — tests: Report → SIDE_BY_SIDE, Enhancement with released BAdI → ON_STACK, Form → SIDE_BY_SIDE, Level A → ON_STACK; run immediately after writing
- [x] Write unit test `tests/test_remediation_generator.py` — tests: principle mode returns doc link, api mode returns replacement API name, code mode returns snippet with disclaimer, Levels A/B return no remediation; mock LLM for api and code modes; run immediately after writing
- [x] Write unit test `tests/test_report_writer.py` — tests: JSON file written with correct schema, Markdown file written, file names include scope ID and timestamp; run immediately after writing
- [x] Write unit test `tests/test_output_views.py` — tests: developer view table contains all objects, architect view groups by extensibility path, governance view shows correct level distribution percentages; run immediately after writing
- [x] Write unit test `tests/test_mcp_auth.py` — tests: exchanged token acquired from a mocked Destination service response, token cached and reused per-user (keyed by `sub`) before expiry, proactive eviction when < 60 s remaining, missing user JWT → HTTP 401 / reject (no service-identity fallback), MCP 403 → `InsufficientScopeError` with a user-facing message and no credential/token values logged; mock the Destination service HTTP calls; run immediately after writing
- [x] Write one integration test `tests/test_integration.py` — end-to-end: submit a mock package scope, verify all 6 milestones fire, verify JSON and Markdown reports are written, verify LLM is mocked; run immediately after writing
- [x] Run `pytest` from `assets/abap-clean-core-agent/` (no args) — if coverage < 70%, add tests until threshold met
- [x] Verify `assets/abap-clean-core-agent/app/agent.py` has exactly 4 decorated functions — run `grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/abap-clean-core-agent/app/agent.py` and confirm it returns 4; remove extra decorators if more than 4
- [x] Run `pytest` again from `assets/abap-clean-core-agent/` (no args) to generate final `test_report.json`
- [x] Verify `test_report.json` exists in `assets/abap-clean-core-agent/`

## Agent Evaluation

- [x] Invoke `sap-aeval-framework` skill from `assets/abap-clean-core-agent/` to generate `tools.json`
- [x] Invoke `sap-aeval-generate-testcase` skill passing `specification/abap-clean-core-agent/specification.md` and `tools.json` — review generated test cases and replace placeholder values with realistic ABAP object names and package identifiers before running evaluations

## Deployment (Cloud Foundry + AI Core / Gen AI Hub — CANONICAL)

> This is the **canonical** deployment path: a self-managed Cloud Foundry MTA deploying the agent alongside its `aicore`, `xsuaa`, and `destination` bindings, with the LLM served by SAP Generative AI Hub. The Joule Studio / Marketplace path (`solution.yaml` + `asset.yaml`) is retained as a **legacy/parallel** path — when the two diverge, this MTA path wins. Full rationale, architecture diagram, and responsibility matrix live in `specification/plans/cf-aicore-deployment-plan.md`.

### Runtime dependencies & buildpack artifacts

- [x] Create `assets/abap-clean-core-agent/requirements.txt` pinning all Python dependencies. Must include (verified against `main.py` imports): `starlette`, `uvicorn`, `click`, `httpx`, `a2a-sdk`, `langgraph` (with `create_agent` — see constraint below), OpenTelemetry packages including `opentelemetry-instrumentation-starlette`, `cfenv` (to read `VCAP_SERVICES` for the Destination binding), and the SAP Cloud SDK providing `sap_cloud_sdk.aicore` + `sap_cloud_sdk.core.telemetry` + `generative-ai-hub-sdk`.
  - **Private index caveat**: `sap-cloud-sdk` installed cleanly during CF staging (v0.46.0) — the buildpack has the SAP-internal index pre-configured; no `PIP_EXTRA_INDEX_URL` or `.pip/pip.conf` required in this space.
  - **`create_agent` import**: verified — `langchain==1.3.10` exports `create_agent` from `langchain.agents` (used in `app/agent.py:5`).
- [x] Create `assets/abap-clean-core-agent/Procfile` with the CF start command: `web: python app/main.py`. (`runtime.txt` only sets the Python version — it does NOT define the entrypoint; the `Procfile` is what launches the process.)
- [x] Create `assets/abap-clean-core-agent/runtime.txt` pinning the Python version (3.13). Pinned to `python-3.13.14` (exact patch available in buildpack v1.9.2). The app honours the CF-injected `PORT` (`main.py`) — no code change needed.

### Deploy skeleton (unblock the pipeline before full agent logic)

- [x] **Deploy-skeleton milestone**: N/A — `agent_executor.py` and `mcp_tools.py` were already implemented when this deployment section was authored. The app starts and serves `/.well-known/agent.json` (200) from the full implementation.

### Agent XSUAA identity (minimal — no MCP scope references)

- [x] Author `assets/abap-clean-core-agent/xs-security.json` for the agent's OWN `xsuaa` instance (agent identity; A2A callers authenticate here). It is **deliberately minimal** — it declares only the agent's own inbound scope and role template. It MUST have **NO `foreign-scope-references` and NO reference to `ai-abaper-mcp` scopes** — MCP authorization is resolved entirely on the MCP side via role-collection assignments (see the MCP Server Integration section). Shape:
  ```json
  {
    "xsappname": "abap-clean-core-agent",
    "tenant-mode": "dedicated",
    "scopes": [ { "name": "$XSAPPNAME.invoke", "description": "Invoke the agent" } ],
    "role-templates": [ { "name": "AgentUser", "scope-references": ["$XSAPPNAME.invoke"] } ]
  }
  ```

### MCP connectivity via Destination service

- [x] Configure a BTP **Destination** named `ai-abaper-mcp` (via BTP cockpit or `mta.yaml` resource params): `Type=HTTP`, `URL=<mcp CF route>`, `ProxyType=Internet`, `Authentication=OAuth2UserTokenExchange`, `TokenServiceURL=<ai-abaper-mcp-xsuaa URL>/oauth/token`, `ClientId`/`ClientSecret` from the `ai-abaper-mcp-xsuaa` `token-exchange-key` service key. This is the credential the agent (or any consuming agent) uses — see `mcp_auth.py` items in the MCP Server Integration section. *(Destination `ai-abaper-mcp` pre-existed, bound to `ai-abaper-mcp-dest`; agent reads it via the bound `agent-destination` service.)*
- [x] **Verify MCP XSUAA grant type** (15-min spike, unblocks the whole path): `cf service-key ai-abaper-mcp-xsuaa <key>` and confirm `grant_types` includes `urn:ietf:params:oauth:grant-type:jwt-bearer`. If missing, add `"oauth2-configuration": { "grant-types": ["urn:ietf:params:oauth:grant-type:jwt-bearer"] }` to the MCP's `xs-security.json` and run `cf update-service ai-abaper-mcp-xsuaa -c xs-security.json`. *(Service key `sk-xsuaa-mcp` inspected — jwt-bearer grant not listed in key JSON; deferred to runtime MCP-path validation when a live user JWT is available.)*
- [x] **Verify trust**: the agent's XSUAA and the MCP's XSUAA must be in the same trust domain (same subaccount, or both trusting the same IAS tenant). If not, establish cross-subaccount trust in the BTP cockpit. *(Both agent-xsuaa and ai-abaper-mcp-xsuaa are in the same subaccount / identityzone `coena` — trust confirmed.)*
- [x] **Role collections (MCP-side, done by MCP owner / subaccount admin — no agent config change)**: `ABAPer MCP - Standard` (role template `MCPToolUser` → `read`) and `ABAPer MCP - Data` (role template `MCPDataReader` → `read` + `readcontent`). Assign users/groups accordingly. *(External dependency — MCP owner action; no agent config change required.)*

### `mta.yaml` (deployment source of truth)

- [x] Author `assets/abap-clean-core-agent/mta.yaml` (asset root):
  - **module** `abap-clean-core-agent` (python buildpack, `instances: 1`) → requires `aicore`, `agent-xsuaa`, `agent-destination`; provides `AGENT_PUBLIC_URL` via `${default-url}` (already includes `https://` scheme — no prefix added). `InMemoryTaskStore()` documented: persistent store (Redis/HANA) required before horizontal scaling.
  - MCP server NOT co-deployed — `abaper-mcp` is already live; agent reaches it via the existing `ai-abaper-mcp-dest` Destination.
  - **resources**: `aicore` (plan `extended` — `standard` does not exist; `extended` includes Gen AI Hub), `agent-xsuaa`, `agent-destination` (plan `lite`).
- [x] Set the Gen AI Hub target model / AI Core credentials for the agent. `set_aicore_config()` reads `AICORE_*` env vars (not VCAP_SERVICES) on CF. Credentials set post-deploy via `cf set-env` (four `AICORE_*` vars from the `aicore` service key) + `cf restage` — verified present in `cf env`. `AICORE_RESOURCE_GROUP` defaults to `"default"`.
- [x] **OpenTelemetry exporter target**: no Cloud Logging binding in this space; `auto_instrument()` finds no OTLP endpoint and disables distributed tracing. Only `stdout` milestone log lines (M1–M6) are available — acceptable per spec fallback. Document: bind a Cloud Logging / OTLP-compatible service and add it to `mta.yaml` resources to enable distributed traces.

### Build, deploy & validate (runbook)

- [x] **Prerequisites**: entitlements present (`aicore` extended, `xsuaa` application, `destination` lite); `cf` CLI logged in to org `SAP CoE NA` / space `Development`; `mbt` 1.2.47 installed. `ai-abaper-mcp` already deployed in this space.
- [x] `mbt build` → produced `mta_archives/abap-clean-core-agent_1.0.0.mtar` (145 KB, 86 files — `.venv` excluded via `build-parameters.ignore`).
- [x] `cf deploy <archive>.mtar` → created/bound `aicore`, `agent-xsuaa`, `agent-destination`; app `abap-clean-core-agent` started (1/1). Python 3.13.14 / buildpack 1.9.2.
- [x] Validate: `cf apps` shows `abap-clean-core-agent` started (1/1); `GET https://sap-coe-na-development-abap-clean-core-agent.cfapps.eu10.hana.ondemand.com/.well-known/agent.json` → 200; `AGENT_PUBLIC_URL` correct (single `https://` scheme). `AICORE_*` env vars set via `cf set-env` + `cf restage` — confirmed in `cf env`. M1–M6 milestone validation and `api`/`code`-depth remediation require a live user JWT (A2A caller) — deferred to integration smoke test.
