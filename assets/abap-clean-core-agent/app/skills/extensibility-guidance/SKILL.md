---
name: extensibility-guidance
description: |
  [WHAT] Maps a classified ABAP object to an SAP extensibility path — Key User, On-Stack (ABAP Cloud), or Side-by-Side (BTP) — using the extensibility decision tree and RICEFW category.
  [WHEN] Use when producing an extensibility verdict for an object, or explaining why an object should stay on-stack versus move to BTP.
  [NOT] Do not use for assigning Clean Core levels — use clean-core-classification — or for generating the fix — use remediation-templates.
  Key terms: extensibility, key user, on-stack, side-by-side, BTP, RICEFW, released BAdI, decision tree.
allowed-tools:
  - Read
metadata:
  author: abap-clean-core-agent
  version: 1.0.0
  tags:
    - extensibility
    - ricefw
    - btp
  user-context-dependent: false
  requires-rbac-scope: false
---

# Extensibility Guidance

## Purpose

Assign each classified ABAP object one extensibility path — `KEY_USER`, `ON_STACK`, or
`SIDE_BY_SIDE` — and justify it against the SAP extensibility framework and the object's RICEFW
category. The verdict tells the migration team *where* the functionality should live after
remediation, not *how* to write it.

This skill is a **capability uplift**: it encodes SAP's extensibility decision tree and RICEFW-to-
path defaults so the agent gives consistent, citable verdicts. The RICEFW pattern table lives in
the companion reference — load it before deciding.

## When to use

- The agent is producing an extensibility verdict for a classified object
- The user asks whether an object should be rebuilt on-stack or moved to BTP, or why
- Grouping objects by extensibility path for an architect/governance view

## When NOT to use

- Assigning a Clean Core level (A/B/C/D) → use `clean-core-classification`
- Writing remediation guidance or a code snippet → use `remediation-templates`
- Retrieving source or metadata → MCP `read` / `readcontent` tool layer

---

## Instructions

### Step 1 — Load RICEFW patterns and gather inputs

```
load("extensibility-guidance/references/ricefw-patterns.md")
```

Required inputs per object: Clean Core `level` (from classification), object `type`
(PROG / CLAS / FUNC / TABL / …), and enough source signal to infer the **RICEFW category**
(Report, Interface, Conversion, Enhancement, Form, Workflow).

| Situation | Action |
|---|---|
| Level and type present | Proceed to Step 2 |
| RICEFW category ambiguous | Infer from dominant behaviour; if still unclear, mark `review_recommended` and explain |
| Level A object | Short-circuit to `ON_STACK` (already compliant) — skip the tree |

### Step 2 — Apply the decision tree deterministically

Evaluate in this order; take the first branch that matches:

1. **Level A** → `ON_STACK` (already compliant, nothing to move).
2. **Key-User-addressable** (UI adaptation, custom fields, simple field-level logic reachable via
   Key User Extensibility tools, no ABAP required) → `KEY_USER`.
3. **RICEFW default** from the reference, then apply the released-API override:
   - If the object uses **only Released APIs** (or a released BAdI exists for its enhancement point)
     and can run in the ABAP Cloud model → `ON_STACK`.
   - Otherwise take the RICEFW category's default path from the reference (most categories default
     to `SIDE_BY_SIDE`).

Released-API availability **upgrades** a would-be Side-by-Side to On-Stack. Absence of a released
extension point pushes toward Side-by-Side.

### Step 3 — Produce the verdict

Return, per object:

```
extensibility: <KEY_USER|ON_STACK|SIDE_BY_SIDE>
ricefw_category: <Report|Interface|Conversion|Enhancement|Form|Workflow>
rationale: "<cite the tree branch + RICEFW pattern, e.g. 'Enhancement with released BAdI available → ON_STACK (ricefw-patterns Enhancements)'>"
```

Every verdict cites both the decision-tree branch taken and the RICEFW pattern applied.

---

## Examples

### Example 1 — Report using released APIs

**Input:**
```
PROG ZR_OPEN_ITEMS — output-only report, reads exclusively via released CDS I_JournalEntry.
Level: B
```

**Output:**
```
extensibility: ON_STACK
ricefw_category: Report
rationale: "Report default is SIDE_BY_SIDE, but object uses only Released APIs → released-API override to ON_STACK (ricefw-patterns Reports)."
```

### Example 2 — Enhancement without a released BAdI

**Input:**
```
CLAS ZCL_PRICING_EXIT — implements a user exit in standard pricing; no released BAdI exists.
Level: D
```

**Output:**
```
extensibility: SIDE_BY_SIDE
ricefw_category: Enhancement
rationale: "Enhancement with no released BAdI coverage → SIDE_BY_SIDE (ricefw-patterns Enhancements: no released BAdI branch)."
```

---

## Gotchas

- **Level A is always ON_STACK** — never route a compliant standard object to Side-by-Side. It has
  nothing to remediate and stays where it is.

- **Released API upgrades the path, it does not skip the category** — always report the RICEFW
  category even when the released-API override lands the object on-stack. Architects group by both.

- **"Could be BTP" ≠ "must be BTP"** — an Enhancement with a released BAdI belongs `ON_STACK` even
  though the same logic *could* be built side-by-side. Prefer keeping released-API-capable logic on
  the stack; reserve Side-by-Side for genuinely decoupled or non-released cases.

- **Interfaces and Forms default to Side-by-Side regardless of level** — integration and document
  output are BTP-preferred (Integration Suite / Document service). Only a released on-stack API for
  the specific case overrides this.
