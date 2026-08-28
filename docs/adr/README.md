# Architecture Decision Records

This directory records the decisions where the **ABAP Clean Core Compliance Agent**
deliberately diverges from the `sap-agent-bootstrap` template and its implied
**Joule Studio runtime** deployment / platform-managed authentication model.

The bootstrap scaffold assumes the agent runs inside the Joule Studio runtime,
which manages MCP connectivity, identity, and deployment for it. Our canonical
target is a **self-managed Cloud Foundry MTA + SAP AI Core / Gen AI Hub**, which
shifts several responsibilities from the platform onto the agent. Each ADR below
captures one such divergence: what the template assumed, what we chose instead,
and why.

Authority note: where these ADRs and the template conflict, these ADRs win, as
codified in `specification/guidelines-agent.md` → "Skill Usage Policy" and the
`specification/plans/cf-aicore-deployment-plan.md` deployment plan.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-canonical-deployment-cf-mta.md) | Canonical deployment is a self-managed Cloud Foundry MTA, not Joule Studio | Accepted |
| [0002](0002-decoupled-destination-jwt-mcp-auth.md) | Decoupled Destination / JWT-bearer MCP authentication | Accepted |
| [0003](0003-requirements-txt-as-deliverable.md) | `requirements.txt` is a first-class deliverable, not cluster-managed | Accepted |
| [0004](0004-mcp-transport-fork-destination-active-agw-dormant.md) | MCP transport fork: Destination active, Agent Gateway kept dormant | Accepted |
| [0005](0005-inbound-jwt-enforcement-and-scope-denial.md) | Reject-on-missing inbound JWT and non-escalating scope-denial handling | Accepted |
