# ADR 0004: MCP transport fork — Destination active, Agent Gateway kept dormant

- **Status**: Accepted
- **Date**: 2026-08-21
- **Deciders**: agent owners (Shahrukh Bhat)
- **Related**: ADR 0002 (Destination / JWT-bearer auth)

## Context

The `sap-agent-bootstrap` scaffold's `mcp_tools.py` reaches the MCP server
exclusively through the **SAP Agent Gateway (AGW)** — `create_client()`,
`list_mcp_tools(user_token=...)`, `call_mcp_tool(...)`, with retry/timeout logic in
`util.py`. AGW is the Joule-runtime transport.

Our canonical deployment (ADR 0001) authenticates via the Destination service and
calls the MCP directly over Streamable HTTP (ADR 0002). However, the Agent Gateway
is expected to become available in our landscape in the future, and we want to be
able to switch to it **without re-implementing** the transport. We therefore need
both transports to coexist.

## Decision

Fork the MCP transport in `mcp_tools.py` on an environment flag, with the
**Destination path as the active default** and the **AGW plumbing kept intact but
dormant**:

- `get_mcp_tools(user_token)` selects the transport via `MCP_TRANSPORT`:
  - unset (or any value other than `agw`) → **Destination path** (direct
    Streamable-HTTP MCP client, injecting `mcp_auth.get_auth_headers()` plus the
    Streamable-HTTP negotiation headers `Content-Type: application/json` and
    `Accept: application/json, text/event-stream`).
  - `MCP_TRANSPORT=agw` → the original **Agent Gateway path** (`create_client()` /
    `list_mcp_tools` / `call_mcp_tool`), preserved unchanged.
- **Retry is per-transport, not shared.** The Destination/direct-HTTP path has its
  own retry + timeout + `403 → InsufficientScopeError` handling in `mcp_tools.py`.
  The AGW path continues to use `util.call_mcp_tool_with_retry`, left untouched.
- The public surface of `mcp_tools.py` is stable across both transports:
  `get_mcp_tools`, `set_user_token`, `reset_user_token`, `get_user_token`, and the
  `IBD_TESTING=1` → mock-tools behavior all apply regardless of transport.

## Consequences

- Switching to AGW when it lands is a config toggle (`MCP_TRANSPORT=agw`), no code
  change.
- The AGW code paths (`create_client`, `list_mcp_tools`, `call_mcp_tool`, and
  `util.call_mcp_tool_with_retry`) must **not** be deleted as "unused" — they are
  intentionally dormant, not dead.
- The two retry mechanisms must not be merged; each is tuned to its transport.
- Slightly more code to maintain (two transports) in exchange for a clean future
  migration and no regression risk on the eventual AGW switch.

## References

- `assets/abap-clean-core-agent/app/mcp_tools.py`
- `assets/abap-clean-core-agent/app/util.py` (AGW-only retry)
- `assets/abap-clean-core-agent/app/mcp_auth.py` (Destination headers)
