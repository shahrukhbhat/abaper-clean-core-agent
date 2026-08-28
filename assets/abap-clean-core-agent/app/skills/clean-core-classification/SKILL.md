---
name: clean-core-classification
description: |
  [WHAT] Classifies custom ABAP objects against SAP Clean Core Levels A–D using released-API status and forbidden-construct detection.
  [WHEN] Use when assigning a Clean Core level to an ABAP object, explaining an ambiguous classification, or citing the specific rule behind a verdict.
  [NOT] Do not use for extensibility path decisions (Key User / On-Stack / Side-by-Side) — use extensibility-guidance instead — or for generating fixes — use remediation-templates.
  Key terms: clean core, level A, level B, level C, level D, released API, ABAP Cloud, forbidden construct, RAP.
allowed-tools:
  - Read
metadata:
  author: abap-clean-core-agent
  version: 1.0.0
  tags:
    - classification
    - clean-core
    - abap
  user-context-dependent: true
  requires-rbac-scope: false
---

# Clean Core Classification

## Purpose

Assign every analysed ABAP object exactly one Clean Core level (A, B, C, or D) and cite the
specific rule behind the verdict. Classification is driven by **released-API status** and the
presence of **forbidden constructs** in the source, adjusted by the target S/4HANA edition.

This skill is a **capability uplift**: it encodes SAP's Clean Core rule set (which an LLM would
otherwise approximate inconsistently) into a deterministic level assignment. The authoritative
rule table and forbidden-pattern list live in the companion reference — always load it before
classifying.

## When to use

- The agent is assigning a Clean Core level (A/B/C/D) to one or more ABAP objects
- The user asks *why* an object received a given level, or challenges a classification
- A rule-based pre-classification returned low confidence and needs explanation

## When NOT to use

- Deciding the extensibility path for an object → use `extensibility-guidance`
- Generating remediation guidance or refactored code → use `remediation-templates`
- Retrieving object source — that is the MCP `read` / `readcontent` tool layer, not a skill

---

## Instructions

### Step 1 — Load the rule set and confirm edition

Load the companion reference before classifying:

```
load("clean-core-classification/references/clean-core-rules.md")
```

Confirm the target S/4HANA edition (on-premise / private-cloud / public-cloud). Edition changes
strictness — do not classify without it. If the caller has not supplied one, the agent defaults
to `on-premise` (the most permissive) and states that assumption.

| Situation | Action |
|---|---|
| Edition supplied | Apply that edition's strictness column from the reference |
| Edition missing | Default to `on-premise`, state the assumption, proceed |
| Source not retrieved (`retrieval_status != success`) | Do not classify — mark `review_recommended=True`, level unknown |

### Step 2 — Apply the level rules deterministically

Classify strictly from the highest-severity match. Severity order is **D > C > B > A** — a single
Level-D forbidden construct makes the whole object Level D regardless of other content.

- **Level D** — any forbidden construct present (see reference "Forbidden constructs"): direct
  `SELECT` on an SAP internal/system table without a Released API, `CALL FUNCTION` to a
  non-released FM, `WRITE TO` a system field, direct write to a `MANDT`-keyed standard table,
  modification of standard SAP via `ENHANCEMENT` without a released BAdI, or use of an API SAP has
  flagged obsolete.
- **Level C** — mixed usage: some Released APIs but also at least one non-released (not forbidden)
  construct, OR a non-released API that has existing BAdI coverage. On **public-cloud**, any
  non-released API usage escalates to Level D (Released-only is strictly enforced).
- **Level B** — uses **only** Released APIs / the ABAP Cloud development model; no non-released or
  forbidden constructs.
- **Level A** — standard SAP object with no custom modification (nothing to remediate).

Set `confidence`. If `confidence < 0.7`, set `review_recommended=True` and pass the object to the
LLM for a final determination — never silently downgrade certainty.

### Step 3 — Produce the classification

Return, per object:

```
level: <A|B|C|D>
rationale: "<specific rule cited from clean-core-rules.md, e.g. 'D: direct SELECT on VBAK (SD internal table) with no Released API wrapper — see Forbidden constructs #1'>"
review_recommended: <true|false>
edition: <on-premise|private-cloud|public-cloud>
```

Never emit a level without a `rationale` that names the rule or released-API status.

---

## Examples

### Example 1 — Clear Level D

**Input:**
```
CLAS ZCL_ORDER_HELPER — source contains: SELECT * FROM vbak INTO TABLE @lt_orders.
Edition: public-cloud
```

**Output:**
```
level: D
rationale: "D: direct SELECT on VBAK (SD internal table) without a Released API — Forbidden constructs #1. Public-cloud enforces Released-only."
review_recommended: false
edition: public-cloud
```

### Example 2 — Edge case (mixed usage, edition-sensitive)

**Input:**
```
PROG ZR_SALES_LIST — reads sales data via released API I_SalesOrder, but also calls
non-released FM Z_LEGACY_CONV. Edition: on-premise
```

**Output:**
```
level: C
rationale: "C: mixed usage — released I_SalesOrder plus non-released FM Z_LEGACY_CONV. On-premise treats non-released-with-coverage as C, not D."
review_recommended: false
edition: on-premise
```

---

## Gotchas

- **Severity is max, not average** — one Level-D construct sets the object to D even if the rest is
  pristine Level-B code. Do not average or "mostly B" an object with a forbidden construct.

- **Edition flips C↔D** — the same non-released API is Level C on on-premise/private-cloud but
  Level D on public-cloud. Always apply the edition column; never hard-code a single verdict.

- **Custom `Z`/`Y` tables are not internal tables** — a `SELECT` on a customer-namespace table is
  allowed. Forbidden-construct #1 targets SAP **standard/internal** tables (e.g. `VBAK`, `BSEG`),
  not customer tables. Check the namespace before flagging.

- **Unretrieved source ≠ Level A** — if `readcontent` failed, the object is *unknown*, not clean.
  Mark `review_recommended=True`; never default a missing-source object to Level A.
