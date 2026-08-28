# ADR 0002: Decoupled Destination / JWT-bearer MCP authentication

- **Status**: Accepted
- **Date**: 2026-08-21
- **Deciders**: agent owners (Shahrukh Bhat)
- **Supersedes**: the client-credentials / service-identity auth wiring implied by the bootstrap template and described in early PRD/intent inputs

## Context

The `sap-agent-bootstrap` scaffold wires MCP access assuming the **platform
(Joule runtime) handles identity** — its `mcp_tools.py` connects through the SAP
Agent Gateway and relies on platform-managed credentials. Earlier project inputs
(PRD / intent) additionally described a **client-credentials** design in which the
agent minted its own XSUAA token (`XSUAA_CLIENT_ID` / `XSUAA_CLIENT_SECRET` /
runtime-qualified `xsappname`) and requested MCP scopes explicitly.

Neither fits the self-managed CF deployment (ADR 0001). We need the MCP server's
own XSUAA to be the sole authority on what a given **user** may do, without the
agent knowing or requesting MCP scopes, and without coupling the agent's
`xs-security.json` to the MCP's.

## Decision

Authenticate to the MCP via **decoupled user-identity propagation** — the agent
is a "dumb pipe" for identity:

- The end user's JWT is forwarded to a bound BTP **Destination service**
  (`ai-abaper-mcp`) configured with `Authentication: OAuth2UserTokenExchange`.
  The Destination swaps the user JWT for an MCP-scoped token carrying **only** the
  scopes that user has been granted (`read` / `readcontent`) via role collections
  on the MCP side.
- `mcp_auth.py` reads the user JWT from the request-scoped context var (set by
  `JWTContextMiddleware`), calls
  `GET /destination-configuration/v1/destinations/ai-abaper-mcp` with header
  `X-user-token: <user_jwt>`, extracts `authTokens[0].value`, and returns
  `Authorization: Bearer <exchanged_token>`. Tokens are cached **per user** (keyed
  by the JWT `sub` claim), TTL from `expires_in`, evicted when < 60 s remain.
- The agent's own `xs-security.json` is **deliberately minimal**: its own
  `invoke` scope only, with **no `foreign-scope-references` and no reference to
  MCP scopes**.

Explicitly forbidden (must never be reintroduced): `grant_type=client_credentials`,
`XSUAA_CLIENT_ID` / `XSUAA_CLIENT_SECRET` / `XSUAA_XSAPPNAME` env vars, explicit
`scope=...read ...readcontent` requests, and runtime-qualified `!t<nnn>` xsappnames.

## Consequences

- The agent has **zero design-time dependency** on the MCP's `xs-security.json`.
  Any agent in the same trust domain can call the MCP by configuring a Destination
  — no XSUAA changes on either side.
- Scope authority lives entirely on the MCP side (role-collection assignments,
  managed by the MCP owner / subaccount admin). A user with only `read` cannot
  invoke `readcontent` tools; the agent does not attempt to influence this.
- Prerequisites move outside the app: the MCP's XSUAA must enable the
  `urn:ietf:params:oauth:grant-type:jwt-bearer` grant, a token-exchange service
  key must exist, and the two XSUAA instances must share a trust domain.
- Never log the user JWT or the exchanged token value.
- Inbound-token enforcement and 403 handling are specified separately in ADR 0005.

## References

- `specification/plans/cf-aicore-deployment-plan.md` → "#1 RESOLVED — Agent → MCP Authentication Model"
- `specification/guidelines-agent.md` → "MCP Authentication (decoupled user-identity propagation)"
- `assets/abap-clean-core-agent/app/mcp_auth.py`
