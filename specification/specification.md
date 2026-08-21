# Specification

> **Guidelines**: Read [guidelines.md](./guidelines.md) before executing ANY tasks below.

Check off items as completed.

## Solution Setup

- [ ] Create asset directory: `mkdir -p assets/abap-clean-core-agent/`
- [ ] Invoke `setup-solution` skill to create `solution.yaml` and `asset.yaml` files for the `abap-clean-core-agent` asset
- [ ] Validate `assets/abap-clean-core-agent/asset.yaml` and `solution.yaml` exist and are well-formed

## Asset Implementation

- [ ] Execute `specification/abap-clean-core-agent/specification.md` (all items)

## Deployment

- [ ] Execute the **Deployment (Cloud Foundry + AI Core / Gen AI Hub)** section of `specification/abap-clean-core-agent/specification.md` — the canonical self-managed MTA path (artifacts, agent XSUAA, Destination-based MCP auth, `mta.yaml`, build/deploy/validate runbook). Detailed rationale in `specification/plans/cf-aicore-deployment-plan.md`. The Joule Studio / Marketplace path (`solution.yaml` + `asset.yaml`) is legacy/parallel.
