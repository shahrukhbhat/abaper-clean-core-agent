# Deployment Plan: abap-clean-core-agent → Cloud Foundry + AI Core (Gen AI Hub)

> Status: DRAFT. This is a self-managed Cloud Foundry (MTA) deployment path that runs
> in **parallel** to the existing Joule Studio / Marketplace path defined by
> `solution.yaml` + `asset.yaml`. Decide which is canonical to avoid drift.

## ✅ #1 RESOLVED — Agent → MCP Authentication Model (Decoupled Pattern)

**Decision**: The agent propagates the end user's identity to the MCP server via JWT
Bearer token exchange. The MCP's XSUAA resolves what scopes the user has **by looking up
role assignments for its own app** — not by reading scopes from the incoming JWT. The
agent has zero knowledge of MCP scopes and no design-time dependency on MCP's
`xs-security.json`.

### Core principle: agent is a dumb pipe for identity

```
User authenticates to agent (any method — IAS, XSUAA, whatever)
    → Agent has a JWT proving the user's identity
    → Agent calls MCP's XSUAA: "here's proof this is user X, give me a token"
    → MCP's XSUAA looks up: "what roles does user X have for ai-abaper-mcp?"
    → Issues token with only those scopes (read, readcontent, or both)
    → Agent sends that token to POST /mcp
    → MCP enforces per-tool scope checks
```

The agent doesn't decide what the user can do on the MCP server. It just proves identity.

### Resolved answers

1. **Token flow** → **(a) User-identity propagation via JWT Bearer exchange.**
   The agent passes the user's JWT to the MCP's XSUAA token endpoint
   (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`). The MCP's XSUAA resolves
   the user's identity, looks up their role assignments for `ai-abaper-mcp`, and issues a
   token carrying **only the scopes that user has been granted** via role collections.
   The incoming JWT just proves identity — it doesn't need to carry MCP scopes.

2. **Scope authority** → **MCP's XSUAA is sole authority. Agent has no involvement.**
   `ai-abaper-mcp-xsuaa` defines `read` and `readcontent` scopes, role templates, and
   role collections. The agent's own `xs-security.json` has **NO `foreign-scope-references`
   and NO reference to MCP scopes at all**. Scope resolution happens entirely at
   exchange time on the MCP's XSUAA side, based on the user's role collection assignments.

   This means:
   - The agent's `xs-security.json` doesn't mention `ai-abaper-mcp`
   - The agent has zero knowledge of MCP scopes
   - **Any agent** in the same trust domain can call the MCP server without design-time
     changes to either party's XSUAA config
   - Adding a new consuming agent = configure a Destination or share exchange credentials

3. **No-token case** → **(a) Reject — user token required.**
   If no user JWT is present on the inbound request, the agent returns HTTP 401. Without
   a user identity, the exchange cannot determine what the caller is authorised to access.
   (Agent-to-agent calls must forward a user token or be rejected.)

4. **MCP-side capability** → **Must support JWT Bearer grant.**
   `ai-abaper-mcp-xsuaa` `xs-security.json` must include:
   ```json
   "oauth2-configuration": {
     "grant-types": ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
   }
   ```
   If missing, update and `cf update-service ai-abaper-mcp-xsuaa -c xs-security.json`.

### Trust prerequisite

For the exchange to work, the MCP's XSUAA must trust the issuer of the user's JWT:
- **Same subaccount** — automatic, no config needed.
- **Different subaccounts, same IAS tenant** — automatic via shared trust.
- **Different trust domains** — establish cross-subaccount trust in BTP cockpit.

### Destination service configuration

The Destination handles the exchange transparently — the agent code has no XSUAA logic:

| Field | Value |
|---|---|
| Name | `abaper-mcp` |
| Type | HTTP |
| URL | `https://<mcp-route>.<landscape>.hana.ondemand.com` |
| Proxy Type | Internet |
| Authentication | `OAuth2UserTokenExchange` |
| Token Service URL Type | Dedicated |
| Token Service URL | `<ai-abaper-mcp-xsuaa URL>/oauth/token` |
| Client ID | from `ai-abaper-mcp-xsuaa` service key (`token-exchange-key`) |
| Client Secret | from same service key |

The agent passes its user JWT via `X-user-token` header when calling the Destination
service. The Destination performs the exchange and returns a token scoped to only what
the user is authorized for on the MCP. Zero MCP-specific OAuth code in the agent.

### Agent-side behavior on scope denial

When the MCP returns HTTP 403 (scope insufficient) on a tool call:
- The agent MUST NOT retry the same call with elevated credentials.
- The agent MUST inform the user: _"You do not have permission to read source content
  (`readcontent` scope). Contact your administrator to request access."_
- The agent SHOULD continue the analysis with whatever data it can retrieve using the
  scopes the user does have (e.g. object metadata via `read` without source via
  `readcontent`). Classification may be limited to metadata-only heuristics in this case.

### Impact on `mcp_auth.py` design

`mcp_auth.py` is deliberately simple — it has no XSUAA-specific logic:
1. Read the user JWT from the request-scoped context var (set by `JWTContextMiddleware`)
2. Call the Destination service REST API with the user JWT:
   `GET /destination-configuration/v1/destinations/abaper-mcp`
   with header `X-user-token: <user_jwt>`
3. Extract `authTokens[0].value` from the response (the exchanged MCP-scoped token)
4. Inject `Authorization: Bearer <exchanged_token>` into MCP HTTP requests
5. Handle 403 responses by raising a typed `InsufficientScopeError` that the agent graph
   catches and translates into a user-facing message

Token caching: per-user (keyed by `sub` claim) with TTL from `expires_in`. Evict
proactively when < 60s remain.

**Note**: If a non-BTP agent needs to call the MCP without the Destination service, it
can do the exchange directly:
```
POST <mcp_xsuaa_url>/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
&assertion=<user_jwt>
&client_id=<token-exchange-key clientid>
&client_secret=<token-exchange-key clientsecret>
&response_type=token
```

### Responsibility matrix

| Responsibility | Who |
|---|---|
| Define scopes (`read`, `readcontent`), role templates | MCP server owner |
| Enable JWT Bearer grant on MCP's XSUAA | MCP server owner |
| Create role collections from MCP's role templates | Subaccount admin |
| Assign users to role collections | Subaccount admin |
| Provide token exchange credentials (service key / Destination) | MCP server owner |
| Authenticate the user (any method) | Agent |
| Exchange token / call MCP (via Destination — standard OAuth) | Agent |
| Enforce per-tool scope authorization | MCP server |

### Why this is decoupled (vs `foreign-scope-references`)

- **Agent has NO `foreign-scope-references`** — its `xs-security.json` doesn't mention
  `ai-abaper-mcp` at all
- **Agent has no MCP-specific auth code** — just passes a user JWT through a Destination
- **Any agent** in the same trust domain can call the MCP without design-time changes
- **Adding a new consuming agent** = configure a Destination. No XSUAA updates anywhere.
- **Scope authority** is entirely on the MCP side — controlled via role collection
  assignments, not agent configuration
- The `foreign-scope-references` pattern is only useful for defense-in-depth (agent
  pre-checks scopes before calling). Since the MCP enforces its own scopes via
  `requireBearerAuth` + per-tool checks, this is unnecessary coupling.

---

## Architecture (target state — all in one BTP subaccount / CF space)

```
┌─────────────────────── BTP Subaccount / CF Space ───────────────────────┐
│                                                                          │
│  ┌────────────────────┐        (OAuth2UserTokenExchange — see #1)         │
│  │ abap-clean-core-    │                                                 │
│  │ agent (this app)    │ ──► ┌─────────────────┐ ──►  ┌──────────┐     │
│  │  A2A / port 5000    │     │ Destination svc │      │ ai-abaper│     │
│  │                     │     │ (mcp-endpoint)  │      │ -mcp app │     │
│  │  set_aicore_config()│     └─────────────────┘      └────┬─────┘     │
│  └─────────┬───────────┘                                    │ bound     │
│            │ bound services                                 ▼           │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  ┌──────────────┐  │
│  │ aicore       │  │ xsuaa        │  │destination│  │ ai-abaper-   │  │
│  │ (Gen AI Hub) │  │ (agent auth) │  │ (lite)    │  │ mcp-xsuaa    │  │
│  └──────┬───────┘  └──────────────┘  └───────────┘  └──────────────┘  │
└─────────┼────────────────────────────────────────────────────────────────┘
          │ inference
          ▼
   SAP Generative AI Hub (GPT-4o deployment in AI Core)
```

> **MCP connectivity via Destination service** — the agent calls the MCP server through
> a BTP Destination configured with `OAuth2UserTokenExchange`. This provides: centralised
> URL management (no env var changes on route updates), automatic per-user token exchange
> (the Destination service swaps the user JWT for an MCP-scoped token carrying only the
> user's granted scopes), and future-proofing for multi-space / multi-subaccount
> topologies where direct routes are inaccessible.

## Prerequisites (verify before building)

1. **Entitlements** in the subaccount: `aicore` (standard plan), `xsuaa` (application
   plan), `destination` (lite plan), Cloud Foundry runtime quota (memory for 2 apps).
2. **AI Core provisioned** with a **Gen AI Hub model deployment** (GPT-4o or equivalent per
   PRD line 290) — capture its `deploymentId` / model name.
3. **`ai-abaper-mcp` deployable** — it and its `ai-abaper-mcp-xsuaa` instance must be
   deployable to this same space (PRD assumption line 384). Confirm the artifact/MTA.
4. **Destination service instance** created and bound to the agent app. A destination named
   e.g. `ai-abaper-mcp` configured with:
   - `URL`: the MCP app's CF route (`https://<mcp-route>.<landscape>.hana.ondemand.com`)
   - `Authentication`: **`OAuth2UserTokenExchange`** (propagates user scopes to MCP)
   - `tokenServiceURL`: `<ai-abaper-mcp-xsuaa URL>/oauth/token`
   - `clientId` / `clientSecret`: from `ai-abaper-mcp-xsuaa` service key
5. Tools: `cf` CLI logged into the target org/space, `mbt` (Cloud MTA Build Tool),
   Python buildpack availability.

## Step-by-step

### 1. Runtime config & dependencies
- Create `assets/abap-clean-core-agent/requirements.txt` (currently missing) pinning: the
  SAP Cloud SDK providing `sap_cloud_sdk.aicore` + `generative-ai-hub-sdk`, `a2a-sdk`,
  `langgraph`/`langchain` (`create_agent` — **not** `create_react_agent`, per CLAUDE.md),
  `uvicorn`, `click`, `httpx`, OpenTelemetry packages.
- Add `runtime.txt` (python version) and start command so the CF Python buildpack runs
  `python app/main.py`. The app already honors `PORT` (`main.py:27`) — CF injects `PORT`,
  no change needed.

### 2. AI Core (LLM) binding
- No app code change needed: `main.py:5` already calls `set_aicore_config()`, which reads
  the bound `aicore` service credentials from `VCAP_SERVICES`. Deliverable is the *binding*,
  declared in `mta.yaml`.
- Confirm the Gen AI Hub model the agent targets is set (env like `AICORE_LLM_DEPLOYMENT`
  or in `agent.py` model config) — wire once `agent.py` exists.

### 3. Agent XSUAA instance
- Author `xs-security.json` for the agent's own `xsuaa` instance (agent identity; A2A
  callers authenticate here). JWT middleware (`main.py:30-48`) already extracts inbound
  bearer tokens.
- The agent's `xs-security.json` is **deliberately minimal** — it defines only the
  agent's own identity and inbound scopes for A2A callers. It has **NO reference to
  MCP scopes or `foreign-scope-references`**:
  ```json
  {
    "xsappname": "abap-clean-core-agent",
    "tenant-mode": "dedicated",
    "scopes": [
      { "name": "$XSAPPNAME.invoke", "description": "Invoke the agent" }
    ],
    "role-templates": [
      { "name": "AgentUser", "scope-references": ["$XSAPPNAME.invoke"] }
    ]
  }
  ```
- MCP authorization is handled entirely on the MCP side — role collections for
  `ai-abaper-mcp` scopes (`read`, `readcontent`) are configured by the MCP server owner
  and assigned to users in the subaccount. The agent has no involvement or knowledge of
  these scopes. See #1 RESOLVED section for details.

### 4. MCP connectivity via Destination service (user-token propagation)
- Bind the `destination` service instance to the agent module in `mta.yaml`. The agent
  reads the destination at runtime via the Destination service REST API (`cfenv` to parse
  `VCAP_SERVICES` for destination service credentials).
- Configure a destination named `ai-abaper-mcp` in the BTP cockpit (or via MTA resource
  config) with:
  - `Type`: `HTTP`
  - `URL`: MCP app's CF route (`https://<mcp-route>.<landscape>.hana.ondemand.com`)
  - `ProxyType`: `Internet` (same-landscape CF-to-CF)
  - `Authentication`: **`OAuth2UserTokenExchange`** (propagates user identity + scopes)
  - `tokenServiceURL`: `<ai-abaper-mcp-xsuaa URL>/oauth/token`
  - `clientId` / `clientSecret`: from `ai-abaper-mcp-xsuaa` service key
- `mcp_auth.py` takes the user JWT (from `JWTContextMiddleware` context var), passes it
  to the Destination service via `X-user-token` header, receives an exchanged token
  carrying only the user's granted scopes (`read`, `readcontent`, or both), and injects
  it into MCP requests. Tokens cached per-user (`sub` claim) with TTL-based eviction.
- Set `AGENT_PUBLIC_URL` to the agent's own CF route (used in `AgentCard`, `main.py:68`).
- **Prerequisite**: confirm `ai-abaper-mcp-xsuaa` supports `user_token` grant type
  (`cf service-key ai-abaper-mcp-xsuaa <key>` → check `grant_types`). If missing, update
  the MCP's `xs-security.json` to include it before deploying.

### 5. `mta.yaml` (single archive — deployment source of truth)
Modules & resources:
- **module** `abap-clean-core-agent` (python buildpack, path
  `assets/abap-clean-core-agent`) → requires: `aicore`, `agent-xsuaa`,
  `agent-destination`; provides its route as `AGENT_PUBLIC_URL`.
- **module** `ai-abaper-mcp` (if co-deploying) → requires `ai-abaper-mcp-xsuaa`; provides
  route consumed by the destination config.
- **resources**:
  - `aicore` (service `aicore`, plan e.g. `standard`)
  - `agent-xsuaa` (service `xsuaa`, `xs-security.json`)
  - `agent-destination` (service `destination`, plan `lite`)
  - `ai-abaper-mcp-xsuaa` (service `xsuaa`) — referenced by the destination config, not
    directly bound to the agent module
- The destination named `ai-abaper-mcp` is configured via the BTP cockpit or as an
  `existing-service` resource with parameters in `mta.yaml`. The agent reads it from the
  bound `destination` service at runtime — no cross-module property propagation needed for
  the MCP URL.

### 6. Build & deploy
- `mbt build` → produces `.mtar`.
- `cf deploy <archive>.mtar` → creates/binds `aicore` + both `xsuaa` instances and pushes
  both apps in order.

### 7. Validation
- `cf apps` both `started`; hit `https://<agent-route>/.well-known/agent.json` (matches all
  probes in `asset.yaml:29-46`) → 200.
- Trigger a scope analysis → check logs for `M1.achieved … M6.achieved` milestone lines.
- Confirm an LLM-backed remediation (depth `api`/`code`) returns → proves AI Core binding.
- Confirm object retrieval succeeds → proves MCP auth path (per resolved #1 decision).

## Key risks / decisions to flag
- **App code is still scaffolding** — only `main.py` + `asset.yaml` exist. `agent.py`,
  `mcp_auth.py`, `mcp_tools.py`, `requirements.txt` per the spec are **not yet written**;
  this deployment can't run until the asset is implemented. Deploy artifacts (mta.yaml,
  xs-security.json, requirements.txt) can be authored in parallel, but end-to-end
  validation waits on the app.
- **Two deployment models coexist** — existing `asset.yaml`/`solution.yaml` target Joule
  Studio/Marketplace; this MTA path is parallel/self-managed. Decide the canonical one.
- **AI Core region/resource-group** must match the subaccount the CF space belongs to, or
  the `aicore` binding won't resolve the Gen AI Hub deployment.

## Decisions locked this session
- **Packaging**: MTA (`mta.yaml`), deployed via `cf deploy`.
- **MCP reachability**: via BTP Destination service (centralised URL + auth config).
- **MCP auth model (was #1 PENDING — now resolved)**: decoupled user-identity propagation
  via JWT Bearer exchange (`OAuth2UserTokenExchange` on Destination). The agent is a dumb
  identity pipe — no `foreign-scope-references`, no MCP scope knowledge. The MCP's XSUAA
  resolves user scopes from its own role assignments; a user with only `read` cannot
  invoke `readcontent` tools. Agent rejects requests without a user token (HTTP 401).
- **LLM path**: Generative AI Hub via `set_aicore_config()` (matches existing `main.py`).

## Action items (previously "PENDING")
- **Verify MCP XSUAA grant types** — run `cf service-key ai-abaper-mcp-xsuaa <key>` and
  confirm `grant_types` includes `urn:ietf:params:oauth:grant-type:jwt-bearer`. If
  missing, add it to the MCP's `xs-security.json` and run
  `cf update-service ai-abaper-mcp-xsuaa -c xs-security.json`. (15-minute spike.)
- **Create token exchange service key** — `cf create-service-key ai-abaper-mcp-xsuaa
  token-exchange-key`. Use this key's `clientId`/`clientSecret`/`url` in the Destination
  configuration. This is the only credential the agent (or any consuming agent) needs.
- **Configure role collections (MCP-side, done by MCP server owner / subaccount admin)**:
  - `ABAPer MCP - Standard` → role template `MCPToolUser` → grants `read` scope
  - `ABAPer MCP - Data` → role template `MCPDataReader` → grants `read` + `readcontent`
  Assign users/groups to the appropriate collection. Users in `Standard` can explore
  object metadata/structure; users in `Data` get full source access for deep analysis.
  **This is entirely on the MCP side — no agent config changes needed.**
- **Verify trust** — confirm the agent's XSUAA and MCP's XSUAA are in the same trust
  domain (same subaccount, or both trusting the same IAS tenant). If not, establish
  cross-subaccount trust.

---

## Review Feedback (2026-08-19)

### Issues identified

#### 1. `main.py` will crash on import — not just "validation waits on app"

`main.py` imports two non-existent modules:
```python
from agent_executor import AgentExecutor       # doesn't exist
from mcp_tools import reset_user_token, set_user_token  # doesn't exist
```
The app will fail with `ModuleNotFoundError` on startup — the CF health probes will never
pass, the app will be marked `crashed`. This isn't just "end-to-end validation waits on
the app" — it's "the app won't start at all". Either stub these modules or create a
"deploy skeleton" milestone that can return 200 on `/.well-known/agent.json` without real
agent logic (useful for validating bindings, network paths, and Destination connectivity).

#### 2. `requirements.txt` — missing/incorrect dependencies

- **Missing**: `starlette` (imported `main.py:17`), `opentelemetry-instrumentation-starlette`
  (imported `main.py:21`).
- **Private index**: `sap_cloud_sdk.aicore` and `sap_cloud_sdk.core.telemetry` are not on
  public PyPI. Clarify: do they ship inside `generative-ai-hub-sdk`? Or does the Python
  buildpack need `PIP_EXTRA_INDEX_URL` pointed to an SAP-internal PyPI mirror? If the
  latter, document how to configure it (buildpack env or `.pip.conf`).
- **`create_agent` doesn't exist**: CLAUDE.md says "use `from langchain.agents import
  create_agent`" but no released LangChain/LangGraph version exports this. The actual
  pattern is `StateGraph` from `langgraph`. Clarify the real import and pin the correct
  package (`langgraph>=0.2`).

#### 3. Missing `Procfile`

The CF Python buildpack requires a `Procfile` to define the start command:
```
web: python app/main.py
```
`runtime.txt` only sets the Python version — it doesn't define the entrypoint. Add
`Procfile` to the deliverables in Step 1.

#### 4. `InMemoryTaskStore` — single-instance constraint

`main.py:79` uses `InMemoryTaskStore()`. If CF scales beyond 1 instance, task state is
not shared — requests routed to different instances will see different task stores.
Recommendation: pin `instances: 1` in the MTA module definition, or flag that a persistent
backing store (Redis / HANA) is needed for horizontal scaling.

#### 5. OpenTelemetry exporter destination not specified

`auto_instrument()` initialises telemetry, but the plan doesn't specify where traces/spans
are exported. If it auto-discovers an OTLP endpoint from `VCAP_SERVICES` (e.g. a bound
Cloud Logging instance), document that binding. If not, traces go nowhere and the M1-M6
milestone validation (`grep` for log lines) only works for `stdout` — not distributed
tracing.

#### 6. Destination service — additional implementation notes

Since we're now using the Destination service:
- `mcp_auth.py` should use `cfenv` to read `VCAP_SERVICES` for the `destination` service
  credentials, then call the Destination service REST API:
  `GET /destination-configuration/v1/destinations/<name>` to retrieve the destination config
  including the auto-fetched auth token.
- Alternatively, use `sap-cf-connectivity` package (if available for Python) which wraps
  the Destination service lookup.
- Add `sap-cf-connectivity` or `cfenv` to `requirements.txt`.
- The Destination service binding also requires a `connectivity` service if accessing
  on-premise systems via Cloud Connector — not needed here (CF-to-CF), but worth noting
  for future extensibility.

### Recommendations

1. **Create a "deploy skeleton" milestone** — stub `agent_executor.py` and `mcp_tools.py`
   with minimal no-op implementations so the app starts and serves `/.well-known/agent.json`.
   This validates the full MTA pipeline (build, deploy, bindings, destination lookup) without
   waiting for the real agent implementation.

2. **Resolve auth with a 15-minute spike** — run
   `cf service-key ai-abaper-mcp-xsuaa <key>` and check `grant_types`. This unblocks the
   entire plan; with the Destination service approach it's just a config toggle.

3. **Decide canonical deployment model NOW** — the two models (Joule Studio vs MTA)
   diverging in parallel is a drift risk. Elevate this to a decision for this session.

4. **Add `Procfile`** to Step 1 deliverables.

5. **Pin CF instances to 1** in `mta.yaml` module parameters until a persistent task store
   is implemented.
