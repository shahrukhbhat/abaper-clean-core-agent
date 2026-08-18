# Product Requirements Document (PRD)

**Title:** ABAP Clean Core Agent  
**Date:** 2026-08-18  
**Owner:** SAP Platform / Architecture Team  
**Solution Category:** AI Agent

---

## Product Purpose & Value Proposition

**Elevator Pitch:**  
Custom ABAP codebases built before SAP's Clean Core paradigm are a blind spot for migration teams. This agent gives developers, architects, and governance teams instant, evidence-based answers: where does each object sit on the Clean Core scale, can it stay on-stack or must it move to BTP, and exactly how should it be fixed?

**Business Need:**  
Organizations running SAP S/4HANA across on-premise and cloud editions carry large volumes of legacy custom ABAP code spanning packages, transports, and individual objects. Before or during an upgrade or cloud migration, teams need to understand the Clean Core compliance posture of every object and have a clear remediation path. Without this, migrations carry hidden risk, runaway costs, and architectural debt.

**Expected Value:**

- Eliminates weeks of manual code review per migration project by automating Clean Core classification.
- Reduces migration risk by surfacing non-compliant objects before go-live, not after.
- Empowers developers to self-serve remediation guidance without waiting for architect review.
- Provides governance teams with auditable, risk-scored compliance reports.

**Product Objectives (Prioritized):**

1. Accurately classify 100% of scoped ABAP objects against Clean Core Levels A–D with supporting rationale.
2. Deliver correct on-stack vs. side-by-side extensibility verdicts aligned to official SAP guidance.
3. Generate actionable remediation guidance selectable at three depth levels (principle → API → code).
4. Serve three distinct audiences (developers, architects, governance) with appropriate output formats.
5. Authenticate securely to the ABAP system using service-to-service credentials without user credential exposure.

---

## User Profiles & Personas

### Primary Persona: Marcus — ABAP Developer

Marcus is a 34-year-old ABAP developer with 8 years of experience on an S/4HANA on-premise system. His team is preparing for a cloud migration and he has been handed a list of 400 custom programs to assess. He knows ABAP well but is not deeply familiar with the new ABAP Cloud / Released API model. He spends hours each day cross-referencing SAP notes and whitepapers trying to work out which of his programs will break in the cloud. He needs concrete, object-level answers fast — ideally with a rewrite suggestion he can act on immediately.

### Secondary Persona: Priya — Solution Architect / Tech Lead

Priya is a 42-year-old SAP solution architect leading the S/4HANA cloud readiness programme for a large manufacturer. She needs to assess entire packages and transport requests to produce an extensibility strategy for the CIO. She cares about the big picture: what percentage of custom code is Clean Core compliant, which objects must move to BTP, and what is the remediation effort estimate. She needs a scorecard she can present in steering committee and a detailed extensibility map she can hand to her team.

### Other User Types

- **Basis & Governance Teams:** Run periodic compliance audits; need risk-scored summary reports and trend data across releases.
- **Project Managers:** Use risk-rated findings to plan remediation workstreams, estimate effort, and track progress toward Clean Core targets.

---

## User Goals & Tasks

### For Marcus (ABAP Developer):

**Goals:**
- Understand exactly which lines or constructs in his code violate Clean Core and why.
- Get a concrete rewrite using the correct Released APIs so he can fix the issue himself.

**Key Tasks:**
- Submit individual programs or object lists to the agent for analysis.
- Review per-object Clean Core level verdict with rationale.
- Request refactored code snippets at depth level 3.
- Export findings to Markdown for ticket creation.

### For Priya (Solution Architect):

**Goals:**
- Produce a Clean Core compliance scorecard across one or more packages.
- Determine which objects belong on-stack vs. must move to BTP side-by-side.
- Identify RICEFW objects that are better rebuilt as BTP extensions.

**Key Tasks:**
- Submit package names or transport request numbers for bulk analysis.
- Review extensibility map (on-stack / side-by-side breakdown per object).
- Export scorecard summary as JSON or Markdown for management reporting.
- Drill into high-risk objects for architect-level guidance.

---

## Product Principles

1. **Evidence-first verdicts:** Every Clean Core classification must cite the specific SAP rule or white paper principle it is based on — no unexplained verdicts.
2. **Audience-aware output:** The same analysis is presented differently to developers (object detail), architects (extensibility map), and governance (scorecard) — the agent adapts without requiring re-analysis.
3. **Guidance, not gospel:** Remediation code snippets are starting points for developer review, not production-ready drops — the agent always states this clearly.
4. **Secure by default:** XSUAA token acquisition, scope construction, and token refresh are handled entirely by the agent; users never handle credentials directly.
5. **SAP-aligned classification:** Classification rules are grounded in the official SAP Clean Core white paper and updated as SAP guidance evolves.

---

## Business Context

**Current State:**  
There is no automated tool that classifies custom ABAP objects against Clean Core Levels A–D at scale. Migration teams perform manual reviews using the SAP Clean Core white paper, ABAP Test Cockpit (ATC), and personal experience. This is slow, inconsistent, and heavily dependent on individual expertise. ATC identifies some issues but does not map them to Clean Core levels, provide extensibility verdicts, or generate remediation guidance.

**Strategic Alignment:**  
SAP's "Rise with SAP" and S/4HANA Cloud migration programmes require customers to reach Clean Core compliance before or during cloud adoption. This agent directly supports that strategic initiative by making the compliance assessment and remediation path explicit and repeatable.

**Success Criteria:**
- 100% of submitted ABAP objects receive a Clean Core level verdict (A, B, C, or D).
- Extensibility verdicts (on-stack / side-by-side) are consistent with SAP's official extensibility framework.
- Developers can generate a usable remediation suggestion within a single conversation turn.
- Governance teams can export a risk-scored scorecard without post-processing.

---

## Goals and Non-Goals

### Goals (In Scope)

- Classify ABAP objects by package, transport request, or individual name against Clean Core Levels A–D.
- Assign extensibility verdict: Key User Extensibility, Developer Extensibility (ABAP Cloud), or Side-by-Side (BTP).
- Apply RICEFW categorisation and provide side-by-side rebuild guidance where appropriate.
- Generate remediation guidance at three selectable depths: principle + doc link, recommended API/BAdI, or refactored ABAP code snippet.
- Produce three output formats: per-object detail report, executive scorecard, and extensibility map.
- Save findings as JSON and Markdown files to a document store.
- Authenticate to the ABAP MCP server using XSUAA service-to-service client credentials with token caching.
- Support mixed environments: S/4HANA on-premise, Cloud Private Edition, Cloud Public Edition.

### Non-Goals (Out of Scope)

- Automatically applying fixes to ABAP source code in the target system.
- Full ATC check replacement — the agent complements, not replaces, the ABAP Test Cockpit.
- SAP Cloud ALM integration (identified as a future extension).
- Real-time continuous monitoring of code changes (batch / on-demand analysis only in V1).
- Support for non-ABAP development objects (UI5, CDS, BTP extensions).

---

## Requirements

### Must-Have Requirements

**R1: Multi-scope ABAP object retrieval**

- **Problem to Solve:** Teams need to analyse groups of objects (packages, transports) as well as individual programs — submitting them one by one is impractical at migration scale.
- **User Story:** As an architect, I need to submit a package name or transport request number so that all contained ABAP objects are automatically retrieved and analysed.
- **Acceptance Criteria:**
  - Given a valid package name, when submitted, then all ABAP development objects in that package are fetched via the MCP server.
  - Given a transport request number, when submitted, then all objects included in the transport are retrieved.
  - Given a comma-separated list of object names, when submitted, then each object is individually retrieved.
  - Objects not found or not accessible return a clear error with the object name.
- **Maps to Objective:** 1, 5
- **Priority Rank:** 1

**R2: Clean Core Level classification (A–D)**

- **Problem to Solve:** There is no automated way to determine which Clean Core level each custom ABAP object falls under, creating manual review bottlenecks.
- **User Story:** As a developer or architect, I need each ABAP object to be classified as Level A, B, C, or D so that I understand its compliance status at a glance.
- **Acceptance Criteria:**
  - Given a retrieved ABAP object, when analysed, then the agent assigns one of four levels: A (standard SAP, no modification), B (uses only Released APIs / ABAP Cloud approved), C (partially clean — uses some released but also some non-released APIs), D (non-compliant — uses internal / deprecated APIs, direct DB access, or forbidden modifications).
  - Each verdict is accompanied by a rationale citing the specific SAP Clean Core principle or rule violated.
  - Classification accounts for the target edition (on-premise / Private / Public) declared by the user at session start.
- **Maps to Objective:** 1
- **Priority Rank:** 2

**R3: Extensibility verdict (on-stack vs. side-by-side)**

- **Problem to Solve:** Developers and architects do not know whether a non-compliant object should be refactored in ABAP Cloud (on-stack) or rebuilt as a BTP side-by-side extension.
- **User Story:** As an architect, I need an extensibility verdict for each object so that I can build an extensibility strategy without researching each case individually.
- **Acceptance Criteria:**
  - Given a classified object, when verdict is requested, then the agent labels it as one of: Key User Extensibility, Developer Extensibility (on-stack / ABAP Cloud), or Side-by-Side (BTP).
  - RICEFW objects (reports, interfaces, conversions, enhancements, forms, workflows) receive additional guidance on whether side-by-side rebuild is the better long-term choice, with rationale.
  - Verdicts align with SAP's official extensibility framework documentation.
- **Maps to Objective:** 2
- **Priority Rank:** 3

**R4: Selectable remediation guidance (3 depth levels)**

- **Problem to Solve:** Different users need different levels of guidance — a governance auditor needs a principle reference; a developer needs a code rewrite.
- **User Story:** As a user, I need to choose the depth of remediation guidance so that I receive output appropriate to my role without being overwhelmed or under-served.
- **Acceptance Criteria:**
  - The agent supports three explicitly selectable modes: (1) Principle — explains the violated rule and links to official SAP documentation; (2) API — recommends the replacement Released API, BAdI, or extension point; (3) Code — generates a refactored ABAP snippet using Clean Core APIs.
  - The mode can be set globally for the session or overridden per object.
  - Code-mode output always includes a disclaimer that the snippet requires developer validation before use.
- **Maps to Objective:** 3
- **Priority Rank:** 4

**R5: Audience-appropriate output views**

- **Problem to Solve:** A single raw output format does not serve all three audience types effectively.
- **User Story:** As a user, I need the agent to present findings in a format suited to my role so that I can act on the results without reformatting.
- **Acceptance Criteria:**
  - Developer view: per-object table showing object name, type, Clean Core level, extensibility verdict, and remediation summary.
  - Architect view: extensibility map grouped by on-stack / side-by-side verdict, with object counts and risk ratings.
  - Governance view: summary scorecard showing distribution across levels A–D as counts and percentages, overall risk rating, and top 10 highest-risk objects.
  - The user can switch between views within the same session without re-running analysis.
- **Maps to Objective:** 4
- **Priority Rank:** 5

**R6: Structured report export (JSON + Markdown)**

- **Problem to Solve:** Teams need to share, store, and track findings over time; conversational output alone is not sufficient.
- **User Story:** As a project manager or architect, I need the analysis saved as a structured file so that I can share it, raise tickets, and track remediation progress.
- **Acceptance Criteria:**
  - The agent saves a JSON file containing all objects, their Clean Core levels, extensibility verdicts, and remediation summaries.
  - The agent saves a Markdown file with the same content formatted for human readability.
  - File names include the scope identifier (package / transport / object list) and a timestamp.
  - Export is triggered by user request or automatically at session end.
- **Maps to Objective:** 4
- **Priority Rank:** 6

**R7: Secure service-to-service authentication to the MCP server**

- **Problem to Solve:** The agent must authenticate to the ai-abaper-mcp MCP server without exposing credentials to users.
- **User Story:** As a platform engineer, I need the agent to manage its own MCP server authentication so that credentials are never passed through the conversation.
- **Acceptance Criteria:**
  - The agent acquires XSUAA tokens using client_credentials grant with the runtime-qualified xsappname (ai-abaper-mcp!t<nnn>) scope for read and readcontent.
  - Tokens are cached for their expires_in duration (default 3600 s) and refreshed proactively before expiry.
  - MCP requests include Authorization: Bearer <token>, Content-Type: application/json, and Accept: application/json, text/event-stream headers.
  - Authentication failures surface a clear error message to the user without exposing credential details.
- **Maps to Objective:** 5
- **Priority Rank:** 7

### High-Want Requirements

**R8: ABAP Test Cockpit (ATC) finding correlation**

- **Problem to Solve:** Teams already run ATC checks; the agent should map ATC findings to Clean Core levels rather than duplicating analysis.
- **User Story:** As a developer, I need ATC findings imported into the agent so that Clean Core levels are derived from existing checks, not from a separate scan.
- **Priority Rank:** 1

**R9: S/4HANA edition-aware classification rules**

- **Problem to Solve:** Clean Core rules differ slightly between on-premise, Private Edition, and Public Edition — a single rule set produces incorrect verdicts for some editions.
- **User Story:** As an architect, I need the agent to apply edition-specific rules so that verdicts are accurate for my deployment model.
- **Priority Rank:** 2

### Nice-to-Have Requirements

**R10: SAP Cloud ALM integration**

- **Problem to Solve:** Remediation findings should feed directly into ALM workitems rather than requiring manual ticket creation.
- **Priority Rank:** 1

**R11: Trend tracking across releases**

- **Problem to Solve:** Governance teams want to see Clean Core compliance improve (or regress) across S/4HANA releases over time.
- **Priority Rank:** 2

---

## Solution Architecture

**Architecture Overview:**  
A Python AI agent (A2A protocol) deployed on SAP BTP. The agent receives user requests via a conversational interface, authenticates to the ai-abaper-mcp MCP server using XSUAA service-to-service credentials, retrieves ABAP object data, applies Clean Core classification and extensibility logic, generates remediation guidance via an LLM (SAP Generative AI Hub), and writes structured reports to a file store.

**Key Components:**

- **ABAP Clean Core Agent (Python / A2A):** Core reasoning engine; orchestrates retrieval, classification, guidance generation, and export.
- **ai-abaper-mcp MCP Server:** Provides ABAP object read and readcontent tools; accessed via Streamable HTTP (POST /mcp).
- **XSUAA Token Manager:** Handles client_credentials token acquisition, caching, and proactive refresh.
- **Clean Core Classification Engine:** Rule-based reasoning module encoding Levels A–D based on SAP Clean Core white paper; applied before LLM reasoning for deterministic verdicts.
- **LLM (SAP Generative AI Hub):** Generates remediation explanations, API recommendations, and code snippets.
- **Report Writer:** Serialises findings to JSON and Markdown and persists to a file / document store.

**Integration Points:**

- **ai-abaper-mcp MCP Server → Agent:** POST /mcp, Streamable HTTP, Bearer token auth; reads ABAP source code and object metadata.
- **XSUAA (ai-abaper-mcp-xsuaa) → Agent:** OAuth 2.0 client_credentials token endpoint; called on startup and proactively on token expiry.
- **SAP Generative AI Hub → Agent:** LLM inference calls for remediation guidance and code generation.
- **File / Document Store → Agent:** Write-only; stores JSON and Markdown report outputs.

### Agent Extensibility & Instrumentation

**Agent Extensibility:**
- The classification rule set is maintained as a versioned configuration file, allowing Clean Core rules to be updated independently of the agent code when SAP guidance changes.
- The remediation depth modes (principle / API / code) are implemented as pluggable prompt templates, enabling new modes to be added without core changes.
- The output view renderers (developer / architect / governance) are modular, allowing new audience formats to be added as extensions.

**Business Step Instrumentation:**
- All six key milestones (M1–M6) are instrumented with structured log statements at milestone entry and completion.
- Logs follow the pattern: `[MILESTONE_ID].[achieved|missed]: [description]`
- Structured logs include: scope identifier, object count, timestamp, and verdict distribution (for classification milestones).

### Automation & Agent Behaviour

**Automation Level:** Autonomous agent with human-in-the-loop for code snippet validation.

**Actions the system performs without human approval:**
- Retrieving ABAP object source and metadata from the MCP server.
- Classifying objects against Clean Core Levels A–D.
- Assigning extensibility verdicts.
- Generating principle-level and API-level remediation guidance.
- Writing JSON and Markdown reports to the file store.

**Actions that require human review or approval:**
- Applying any generated ABAP code snippet to a production or development system — the agent explicitly states that code output requires developer validation.

**Model or engine used:** LLM via SAP Generative AI Hub (GPT-4o or equivalent); classification verdicts are rule-based first, LLM used for explanation and code generation only.

**Knowledge & data sources accessed:**
- ABAP source code and object metadata (via ai-abaper-mcp MCP server, read-only).
- SAP Clean Core white paper rules (embedded in classification engine as versioned config).
- SAP Released API catalogue (referenced in remediation guidance).

**Tools or connectors invoked:**
- `read` MCP tool: retrieves ABAP object metadata (read-only).
- `readcontent` MCP tool: retrieves full ABAP source code (read-only).
- LLM inference: generates explanations and code (no side effects).
- File writer: writes JSON / Markdown reports (write to file store only).

**Guardrails & fail-safes:**
- The agent never writes to the ABAP system — all MCP interactions are strictly read-only.
- Code snippets are always presented with a disclaimer requiring developer validation before use.
- If the MCP server returns an authentication error, the agent re-acquires the token once and retries; if it fails again, it surfaces a clear error and halts the analysis.
- If an object's source cannot be retrieved, the object is flagged as "unclassified — retrieval failed" in the report rather than silently omitted.
- Classification verdicts below confidence threshold (ambiguous cases) are flagged with a "review recommended" marker rather than presented as definitive.

---

## Milestones

### M1: Scope Defined

- **Description:** The user has provided a valid analysis scope (package name(s), transport request number, or object list) and the agent has confirmed it.
- **Achieved when:** The agent has validated the scope input and confirmed the list of objects to be analysed.
- **Log on achievement:** `M1.achieved: scope confirmed — {object_count} objects identified in scope '{scope_identifier}'`
- **Log on miss:** `M1.missed: scope validation failed — no valid objects identified for input '{scope_identifier}'`

### M2: Code Retrieved

- **Description:** All ABAP objects in scope have been successfully fetched from the target system via the MCP server.
- **Achieved when:** Source code and metadata for all scoped objects are available in the agent's working context.
- **Log on achievement:** `M2.achieved: code retrieval complete — {retrieved_count}/{total_count} objects retrieved for scope '{scope_identifier}'`
- **Log on miss:** `M2.missed: code retrieval incomplete — {failed_count} objects could not be retrieved; proceeding with {retrieved_count} objects`

### M3: Classification Complete

- **Description:** Every retrieved object has been assigned a Clean Core Level (A, B, C, or D) with supporting rationale.
- **Achieved when:** All retrieved objects have a Clean Core level verdict and rationale in the agent's working results.
- **Log on achievement:** `M3.achieved: classification complete — {total_count} objects classified; distribution: A={a_count}, B={b_count}, C={c_count}, D={d_count}`
- **Log on miss:** `M3.missed: classification incomplete — {unclassified_count} objects could not be classified`

### M4: Extensibility Verdict Delivered

- **Description:** Each classified object has been labelled with its extensibility path: Key User Extensibility, Developer Extensibility (on-stack), or Side-by-Side (BTP).
- **Achieved when:** All classified objects have an extensibility verdict and RICEFW-aware side-by-side guidance where applicable.
- **Log on achievement:** `M4.achieved: extensibility verdicts complete — on-stack={on_stack_count}, side-by-side={side_by_side_count}, key-user={key_user_count}`
- **Log on miss:** `M4.missed: extensibility verdict could not be determined for {unresolved_count} objects`

### M5: Remediation Plan Produced

- **Description:** Actionable remediation guidance has been generated at the user-selected depth level for all non-compliant objects.
- **Achieved when:** All Level C and D objects have remediation guidance generated at the requested depth (principle, API, or code).
- **Log on achievement:** `M5.achieved: remediation guidance generated — {remediated_count} objects at depth '{depth_level}'`
- **Log on miss:** `M5.missed: remediation guidance could not be generated for {failed_count} objects at depth '{depth_level}'`

### M6: Report Saved

- **Description:** The full findings have been exported to structured JSON and Markdown files in the document store.
- **Achieved when:** Both JSON and Markdown report files are written and confirmed by the file store.
- **Log on achievement:** `M6.achieved: reports saved — '{json_filename}' and '{md_filename}' written successfully`
- **Log on miss:** `M6.missed: report export failed — files could not be written for scope '{scope_identifier}'`

---

## Non-Functional Requirements

### Performance
- **Latency:** Individual object classification should return a verdict within 10 seconds.
- **Throughput:** Bulk analysis of packages up to 500 objects should complete within 10 minutes.

### Reliability
- **XSUAA token failure:** Agent retries once on token expiry; surfaces a clear error after second failure.
- **MCP server unavailability:** Agent surfaces a diagnostic error message; does not silently return empty results.
- **Partial retrieval:** Analysis proceeds with available objects; unresolvable objects are flagged, not silently dropped.

### Explainability
- **Traceability:** Every Clean Core verdict cites the specific white paper rule or API release status it is based on.
- **Decision Logging:** All milestones (M1–M6) emit structured logs with scope, object counts, and verdict distributions.
- **Uncertainty Communication:** Objects where the classification is ambiguous are flagged with a "review recommended" marker in all output views.

---

## Risks, Assumptions, and Dependencies

### Risks
- **Clean Core rule drift:** SAP periodically updates its Clean Core guidance; classification rules embedded in the agent must be versioned and updated to stay accurate.
- **MCP server tool coverage:** The agent depends on the ai-abaper-mcp server exposing read and readcontent tools for all relevant object types. If some object types are not supported, those objects cannot be analysed.
- **LLM accuracy on ABAP:** Code snippet generation is LLM-driven and may produce syntactically correct but semantically incorrect ABAP; developer review is mandatory and must be enforced in UX.

### Assumptions
- The ai-abaper-mcp MCP server is accessible at a known endpoint and a service key can be created on ai-abaper-mcp-xsuaa.
- The runtime-qualified xsappname (with !t<nnn> suffix) is available from the service key output.
- The MCP server exposes read and readcontent tools sufficient to retrieve ABAP source and object type metadata.
- Users have the business context to validate code snippets before applying them.

### Dependencies
- ai-abaper-mcp MCP server (available and provisioned with service key).
- SAP Generative AI Hub (LLM endpoint for remediation guidance and code generation).
- XSUAA instance (ai-abaper-mcp-xsuaa) with client_credentials grant enabled.
- SAP Clean Core white paper and Released API catalogue (reference material for classification rules).

---

## Appendix

### Glossary

- **Clean Core Level A:** Standard SAP-delivered functionality; no modification.
- **Clean Core Level B:** Custom code using only SAP-released extensibility APIs (ABAP Cloud / Released APIs); fully compliant.
- **Clean Core Level C:** Custom code mixing released and non-released API usage; partially compliant, remediation required.
- **Clean Core Level D:** Custom code using internal APIs, direct database access, or forbidden modifications; non-compliant, remediation mandatory.
- **Key User Extensibility:** Low-code/no-code customisation using SAP tools (e.g., custom fields, custom logic via BAdI in Fiori).
- **Developer Extensibility (on-stack / ABAP Cloud):** Custom ABAP development using only Released APIs, deployed on the same stack.
- **Side-by-Side Extensibility:** Custom development deployed on SAP BTP, decoupled from the S/4HANA core.
- **RICEFW:** Reports, Interfaces, Conversions, Enhancements, Forms, Workflows — common categories of custom ABAP objects.
- **MCP:** Model Context Protocol — the communication protocol used between the AI agent and the ABAP system.
- **XSUAA:** Extended Services for User Account and Authentication — SAP BTP's OAuth 2.0 authorization service.

### References

- [SAP Clean Core White Paper](https://www.sap.com/documents/2023/10/dd2a3571-797e-0010-bca6-c68f7e60039b.html)
- [SAP ABAP Cloud Developer Guide](https://help.sap.com/docs/abap-cloud)
- [SAP Extensibility Concepts for S/4HANA](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9a281eac983f4f688d0deedc96b3c61c/7a8c12a2d6e04f3bb8064b765e0d2977.html)
- [SAP BTP XSUAA Service Documentation](https://help.sap.com/docs/btp/sap-business-technology-platform/sap-authorization-and-trust-management-service)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/specification)
