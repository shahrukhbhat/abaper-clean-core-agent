# ADR 0005: Reject-on-missing inbound JWT and non-escalating scope-denial handling

- **Status**: Accepted
- **Date**: 2026-08-21
- **Deciders**: agent owners (Shahrukh Bhat)
- **Related**: ADR 0002 (Destination / JWT-bearer auth)

## Context

The bootstrap `JWTContextMiddleware` in `main.py` **extracts** an inbound Bearer
token into a context var but does not require one — a request with no token is
served with a `None` identity, on the assumption that the Joule platform gate
handled authentication upstream.

Under the decoupled auth model (ADR 0002) the agent is the identity pipe: without
a user JWT there is **nothing to exchange**, so the MCP cannot determine what the
caller is authorized to do. Falling back to any service identity would defeat the
entire model. We also need a defined behavior when the MCP later denies a specific
tool for lack of scope.

## Decision

Enforce user identity at the edge and never escalate on scope denial.

- **Reject-on-missing (HTTP 401).** `JWTContextMiddleware` rejects requests to
  protected paths that carry no Bearer token with **HTTP 401**
  (`{"error": "missing_user_token"}`). The agent never falls back to a service
  identity for MCP access.
- **Public paths stay open.** Agent-card discovery (`/.well-known/*`) and health
  probes (`/health`, `/healthz`, `/ready`, `/readyz`) are exempt from the 401 gate
  so platform readiness/liveness probes and A2A discovery succeed unauthenticated.
- **Non-escalating scope denial.** An MCP `HTTP 403` (scope insufficient) is
  raised as a typed `InsufficientScopeError`. The agent MUST NOT retry with
  elevated credentials. The agent graph catches it, surfaces a user-facing message
  naming the missing scope (`read` / `readcontent`), and continues with whatever
  data the user's scopes allow (e.g. metadata via `read` when `readcontent` is
  denied). A 403 is therefore explicitly **not retryable** in the Destination
  transport's retry loop.
- **Missing-token guard in exchange.** `mcp_auth` raises `MissingUserTokenError`
  if an exchange is attempted with no user JWT — a defensive backstop behind the
  middleware's 401.
- Never log the user JWT or exchanged token value.

## Consequences

- Unauthenticated callers to the A2A RPC endpoints get a clear 401; probes and
  discovery are unaffected. Validated locally: `/.well-known/agent.json` → 200 with
  no token; `POST /` → 401 with no token, not-401 with a Bearer token.
- Scope-limited users still get useful partial results instead of a hard failure,
  and the agent cannot be coerced into privilege escalation.
- The middleware's public-path allowlist must be kept in sync if new unauthenticated
  endpoints (e.g. additional health routes) are introduced.

## References

- `specification/guidelines-agent.md` → "MCP Authentication", "Guardrails" expectations
- `specification/abap-clean-core-agent/specification.md` → "Guardrails Implementation"
- `assets/abap-clean-core-agent/app/main.py` (`JWTContextMiddleware`)
- `assets/abap-clean-core-agent/app/mcp_auth.py` (`InsufficientScopeError`, `MissingUserTokenError`)
- `assets/abap-clean-core-agent/app/mcp_tools.py` (403 handling, non-retryable)
