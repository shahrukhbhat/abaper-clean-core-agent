# ABAP Clean Core Agent

ABAP Clean Core Compliance Analyzer & Remediation Guide

## Business challenge

Organizations running SAP S/4HANA (on-premise and cloud editions) carry large volumes of custom ABAP code — spread across packages, transport requests, and individual development objects — that was written before SAP's Clean Core paradigm. Before or during an S/4HANA upgrade or cloud migration, architects, developers, and governance teams need to understand:

1. Where each piece of custom code sits on SAP's Clean Core scale (Levels A–D).
2. Whether it is a candidate for on-stack extensibility (Key User or Developer Extensibility) or must move to side-by-side extensibility on BTP.
3. Concrete, actionable steps to remediate code that violates Clean Core principles — from high-level guidance up to refactored code snippets.

Without this, teams face expensive, risky migration projects with no clear roadmap.

## Key Milestones

1. **Scope defined** — user provides a package name, list of packages, a transport request, or individual object names; agent confirms the scope.
2. **Code retrieved** — agent fetches all relevant ABAP objects from the target system via MCP server (service-to-service credentials).
3. **Classification complete** — every object is assigned a Clean Core Level (A, B, C, D) with supporting rationale.
4. **Extensibility verdict delivered** — each object is labelled as suitable for Key User Extensibility, Developer Extensibility (on-stack), or Side-by-Side extensibility.
5. **Remediation plan produced** — actionable guidance generated at the depth requested (principle/doc link, API recommendation, or refactored code snippet).
6. **Report saved** — findings exported to a structured file (JSON/Markdown/PDF) for further use.

## Business Architecture (RBA)

### End-to-End Process

Idea to Release for Software (Design to Release)

### Process Hierarchy

```
Idea to Release for Software (E2E)
└── Design to Release (Phase)
    └── Design software product (BPS-320_005)
        └── Build software product
        └── Design software product
```

### Summary

The challenge maps to the "Design to Release" sub-process (BPS-320_005) — specifically the quality and compliance gates applied during software build — combined with Governance/GRC compliance gap assessment for remediation workstream planning.

## Fit Gap Analysis

| Requirement (business) | Standard asset(s) found | API ORD ID | MCP Server ORD ID | MCP Server Version | Gap? | Notes / assumptions |
| ---------------------- | ----------------------- | ---------- | ----------------- | ------------------ | ---- | ------------------- |
| Retrieve ABAP objects from packages / transports | ODATA Service for Change and Transport System; Explore Technical Objects | — | — | — | Yes | No MCP server found; agent will call MCP server directly via service-to-service credentials on the ai-abaper-mcp instance |
| Classify objects against Clean Core Levels A–D | No standard product | — | — | — | Yes | Classification logic must be custom-built using SAP Clean Core white paper rules embedded in agent prompts |
| Determine on-stack vs. side-by-side extensibility fit | No standard product | — | — | — | Yes | Decision tree based on SAP extensibility guidance; encoded in agent reasoning |
| Generate remediation guidance (3 depth levels) | No standard product | — | — | — | Yes | LLM-driven; references official SAP documentation and Clean Core white paper |
| Save findings to file / document store | SAP Cloud ALM (partial — test & feature tracking) | — | — | — | Partial | Agent writes structured reports (JSON / Markdown); Cloud ALM integration optional future extension |
| Scorecard / summary view for governance teams | No standard product | — | — | — | Yes | Agent generates both summary scorecards and per-object detail views |

### Key findings

- No standard SAP product covers automated Clean Core level classification of custom ABAP — this is a custom AI agent build.
- The target system exposes ABAP object metadata via the MCP server (ai-abaper-mcp); the agent authenticates with service-to-service client credentials (XSUAA, grant_type=client_credentials, scopes: read + readcontent).
- The agent must serve three distinct audiences (developers, architects, governance) with different output formats: per-object detail, scorecard summary, and refactored code snippets.
- The mixed on-premise / cloud target environment means classification rules must account for S/4HANA Public, Private, and on-premise Clean Core constraints, which differ slightly.
- Remediation depth is user-selectable at runtime (principle + doc link → API recommendation → full code rewrite), requiring a multi-mode prompt strategy.
- Token caching for XSUAA tokens (3600 s TTL) must be built into the agent to avoid per-request authentication overhead.

## Recommendations

### AI Agent: ABAP Clean Core Analyzer

#### Executive Summary

Python AI agent classifying ABAP code against Clean Core levels with remediation guidance.

#### Recommended Solution

A pro-code Python AI agent (A2A protocol) that:
- Connects to the ABAP system via the **ai-abaper-mcp MCP server** using XSUAA service-to-service client credentials (client_credentials grant, scopes read + readcontent, token cached for 3600 s).
- Accepts scope inputs: one or more package names, a transport request number, or a list of individual object names.
- Retrieves ABAP source and metadata via MCP tools (read, readcontent).
- Classifies each object against **SAP Clean Core Levels A–D** using rules derived from the SAP Clean Core white paper and official extensibility guidance.
- Labels each object for **on-stack extensibility** (Key User Extensibility or Developer Extensibility / ABAP Cloud) or **side-by-side extensibility** on SAP BTP.
- Generates remediation guidance at three selectable depths:
  1. Principle explanation + link to official SAP documentation.
  2. Recommended replacement SAP API / extension point / BAdI.
  3. Refactored ABAP code snippet using Clean Core APIs (Released APIs, ABAP Cloud).
- Produces audience-appropriate output views: per-object detail report, executive scorecard, and architecture-level extensibility map.
- Saves findings as structured files (JSON and Markdown) to a document store.
- Applies RICEFW (Reports, Interfaces, Conversions, Enhancements, Forms, Workflows) categorisation to help teams decide which objects are better rebuilt as BTP side-by-side extensions.

#### Problem Statement

Custom ABAP code bases are opaque to migration teams — there is no automated way to determine which objects violate Clean Core, at what severity, and what the correct remediation path is. This creates migration risk, cost overruns, and architectural debt.

#### Affected User Roles

- ABAP developers (individual object review and code rewrite guidance)
- Solution architects and tech leads (package / transport-level assessment, extensibility strategy)
- Basis and governance teams (compliance audit, scorecard reporting)
- Project managers (remediation workstream planning based on risk-rated findings)

#### Important factors

##### Covers the full Clean Core classification spectrum
The agent encodes all four Clean Core levels (A = standard SAP, B = released extensibility APIs, C = partially clean, D = violating) with rationale for each verdict, aligned to the official SAP Clean Core white paper.

##### Actionable at every level of depth
Developers get rewritten code; architects get extensibility verdicts; governance teams get risk-scored scorecards — all from the same agent, mode-switched at runtime.

##### Secure machine-to-machine authentication
The agent handles XSUAA token acquisition, scope construction (runtime-qualified xsappname with !t<nnn> tenant suffix), and proactive token refresh, removing manual credential management from users.

##### RICEFW-aware side-by-side guidance
The agent identifies when a RICEFW object (report, interface, form, enhancement, etc.) is a better fit for a BTP side-by-side rebuild and explains why, referencing SAP's preferred extensibility patterns.

#### Potential risks

##### Clean Core rule coverage completeness
SAP's Clean Core guidance evolves; the embedded classification rules must be kept in sync with the latest SAP white paper and S/4HANA release notes.

##### MCP server tool availability
The agent depends on the ai-abaper-mcp MCP server exposing sufficient read and readcontent tools to retrieve full source code and object metadata. Incomplete tool coverage would limit analysis depth.

##### LLM accuracy on ABAP-specific patterns
The remediation code snippet mode relies on LLM reasoning over ABAP syntax and Released API availability; outputs must be treated as guidance requiring developer validation, not production-ready code.

#### Recommended solution category

AI Agent

#### Intent fit
92%
