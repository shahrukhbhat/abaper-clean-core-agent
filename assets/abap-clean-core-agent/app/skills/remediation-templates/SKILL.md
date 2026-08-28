---
name: remediation-templates
description: |
  [WHAT] Provides remediation prompt templates at three selectable depths — principle (rule + doc link), api (replacement Released API / BAdI), and code (refactored ABAP snippet with disclaimer).
  [WHEN] Use when generating remediation guidance for a Level C or Level D object at a requested depth.
  [NOT] Do not use for assigning Clean Core levels — use clean-core-classification — or for choosing the extensibility path — use extensibility-guidance. Never generate remediation for Level A or B objects.
  Key terms: remediation, principle, api, code, depth, refactor, released API, disclaimer, doc link.
allowed-tools:
  - Read
metadata:
  author: abap-clean-core-agent
  version: 1.0.0
  tags:
    - remediation
    - refactoring
    - clean-core
  user-context-dependent: true
  requires-rbac-scope: false
---

# Remediation Templates

## Purpose

Generate remediation guidance for non-compliant ABAP objects at a **selectable depth**:
`principle`, `api`, or `code`. The depth controls how far the guidance goes — from citing the
violated rule and a doc link, up to a refactored code snippet. Only **Level C and Level D** objects
receive remediation; Levels A and B are already compliant.

This skill is an **encoded preference**: it fixes the output shape and the mandatory disclaimer for
each depth so guidance is consistent and safe (the agent must never present generated ABAP as
production-ready).

## When to use

- Generating remediation for a Level C or D object at a known depth (`principle` / `api` / `code`)
- The user asks to "go deeper" / "show the API" / "show me the code" on a prior verdict

## When NOT to use

- The object is Level A or B → return "no remediation needed"; do not invoke this skill
- Assigning the Clean Core level → `clean-core-classification`
- Choosing the extensibility path → `extensibility-guidance`

---

## Instructions

### Step 1 — Determine depth and eligibility

Read the session depth mode (`principle` | `api` | `code`; default `principle`) and any per-object
override in the user's instruction. Then gate on level:

| Situation | Action |
|---|---|
| Level A or B | Return "No remediation needed — object is already Clean Core compliant." Stop. |
| Level C or D, depth resolved | Proceed to Step 2 with that depth |
| Depth not set | Use `principle` (the safe default); state the depth used |

### Step 2 — Apply the depth template

**Depth 1 — `principle`** (no LLM refactor required):
- Explain the violated rule using the classification `rationale`.
- Append the relevant SAP documentation URL:
  - Level D → SAP Clean Core white paper section on forbidden modifications.
  - Level C → ABAP Cloud Developer Guide / Released API usage.
  - Level B (affirmative only, if asked) → cite the Released API used correctly.

**Depth 2 — `api`** (uses the LLM + `extensibility-guidance`):
- Identify the replacement Released API, released BAdI, or extension point that replaces the
  offending construct. Return: **current construct**, **recommended replacement**, **migration
  complexity** (`low` | `medium` | `high`).

**Depth 3 — `code`** (uses the LLM):
- Produce a refactored ABAP snippet using the recommended Released API.
- **Prefix the snippet with this exact disclaimer** (verbatim, do not reword):

  > ⚠️ This snippet is a starting point for developer validation and is NOT production-ready. Review and test thoroughly before applying.

### Step 3 — Produce the output

- `principle`: rule explanation + one doc URL.
- `api`: the three fields (current / replacement / complexity).
- `code`: the disclaimer line, then a fenced ```abap block with the refactored snippet.

Deeper depths **include** the shallower content: `code` output also states the API being used and
the principle behind it.

---

## Examples

### Example 1 — principle depth (Level D)

**Input:**
```
CLAS ZCL_ORDER_HELPER, Level D, rationale: "direct SELECT on VBAK without Released API". depth=principle
```

**Output:**
```
Level D — direct SELECT on VBAK (SD internal table) bypasses the Released API contract, which
breaks Clean Core: SAP may change internal table structures without notice.
See: SAP Clean Core white paper — "Forbidden modifications / direct database access".
<https://help.sap.com/…/clean-core-forbidden-modifications>
```

### Example 2 — code depth (Level D)

**Input:**
```
Same object. depth=code. Recommended replacement: released CDS I_SalesOrder.
```

**Output:**
```
⚠️ This snippet is a starting point for developer validation and is NOT production-ready. Review and test thoroughly before applying.

Replacing the direct VBAK SELECT with the released I_SalesOrder CDS view:

```abap
SELECT SalesOrder, SalesOrderType, SoldToParty
  FROM I_SalesOrder
  WHERE SalesOrder = @iv_order_id
  INTO TABLE @DATA(lt_orders).
```
```

---

## Gotchas

- **Never remediate Level A/B** — returning a "fix" for a compliant object wastes the user's time
  and implies a false problem. Gate on level first, always.

- **The code-depth disclaimer is verbatim and mandatory** — every `code` output must lead with the
  exact ⚠️ line. Do not paraphrase, shorten, or drop it, even if the same object was shown before.

- **`api` depth must name a real Released replacement** — do not invent an API name. If no released
  replacement exists, say so and recommend `SIDE_BY_SIDE` (per `extensibility-guidance`) instead of
  fabricating an on-stack API.

- **Doc links are section-specific** — Level D links to forbidden-modifications guidance; Level C
  links to the ABAP Cloud Developer Guide. Do not swap them; the audience and fix differ.
