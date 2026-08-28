# ADR 0001: Canonical deployment is a self-managed Cloud Foundry MTA, not Joule Studio

- **Status**: Accepted
- **Date**: 2026-08-21
- **Deciders**: agent owners (Shahrukh Bhat)

## Context

The `sap-agent-bootstrap` scaffold, together with the `setup-solution`,
`deploy-solution`, and `joule-studio-cli` (`jl`) skills, targets the **SAP Joule
Studio / Marketplace runtime**. In that model the platform builds, deploys, and
runs the agent from the `solution.yaml` + `asset.yaml` descriptors, and the `jl`
CLI (or the `deploy_solution` tool) is the deployment mechanism.

Our operational requirement is a **self-managed deployment we control end to
end**: the agent must run alongside its own `aicore`, `xsuaa`, and `destination`
service bindings, with the LLM served by SAP Generative AI Hub, in a Cloud
Foundry space we own. Joule Studio is not the target environment for this agent
today.

## Decision

The **canonical deployment path is a Cloud Foundry Multi-Target Application
(MTA)**, built with `mbt build` and deployed with `cf deploy`.

- CF buildpack artifacts are real deliverables: `Procfile` (`web: python
  app/main.py`), `runtime.txt` (Python 3.13), `requirements.txt` (see ADR 0003).
- `mta.yaml` is the deployment source of truth: the agent module requires
  `aicore`, `agent-xsuaa`, and `agent-destination`; resources declare those
  services plus the MCP's XSUAA.
- The agent module is pinned to **`instances: 1`** because `main.py` uses
  `InMemoryTaskStore()`, whose state is not shared across instances. Horizontal
  scaling requires a persistent store (Redis / HANA) first.
- The `solution.yaml` + `asset.yaml` (Joule Studio / Marketplace) descriptors are
  **retained as a legacy/parallel path**. When the two diverge, the MTA path wins.
- The `deploy-solution` and `joule-studio-cli` (`jl`) skills MUST NOT be invoked
  for the canonical path. They remain available only if the legacy Joule path is
  ever exercised.

## Consequences

- We own build/deploy/validate: `mbt build` → `.mtar` → `cf deploy`, then verify
  both apps `started` and `GET /.well-known/agent.json` → 200.
- Two deployment descriptors coexist (drift risk). Mitigated by the explicit
  "MTA path wins" tie-breaker documented here and in
  `specification/guidelines-agent.md`.
- The AI Core region / resource-group must match the subaccount the CF space
  belongs to, or the `aicore` binding will not resolve the Gen AI Hub deployment.
- Commands and status summaries for the canonical path should not reference
  `jl` / `deploy_solution`.

## References

- `specification/guidelines-agent.md` → "Skill Usage Policy", "Deployment Constraints (CF + AI Core)"
- `specification/plans/cf-aicore-deployment-plan.md`
- `specification/abap-clean-core-agent/specification.md` → "Deployment (Cloud Foundry + AI Core / Gen AI Hub — CANONICAL)"
