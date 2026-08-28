# Clean Core Classification Rules

> **Rule set version:** 1.0.0
> **Editions covered:** on-premise, private-cloud, public-cloud
> Authoritative reference loaded by the `clean-core-classification` runtime skill and parsed by
> `app/classification/rules_config.py`. When this file changes, bump the version above — the
> version is logged on agent start for traceability.

## Clean Core Levels

| Level | Name | Definition | Remediation needed |
|---|---|---|---|
| **A** | Standard / unmodified | Standard SAP object with no custom modification. Nothing customer-owned to change. | None |
| **B** | Clean (Released-only) | Custom object that uses **only** Released APIs / the ABAP Cloud development model (RAP, released CDS, released BAdIs). Fully Clean Core compliant. | None |
| **C** | Mixed | Custom object mixing Released APIs with at least one **non-released but not forbidden** construct, or a non-released API that has existing released BAdI/API coverage. Migratable on-stack. | Yes (API-level) |
| **D** | Non-compliant | Custom object containing at least one **forbidden construct** (see below), a genuinely internal/obsolete API, or a standard-object modification without a released extension point. | Yes (often side-by-side) |

Severity order is **D > C > B > A**. Classify by the **highest-severity** match: a single Level-D
construct makes the whole object Level D.

## Forbidden constructs (any one ⇒ Level D)

1. **Direct `SELECT` on an SAP internal/standard table** without a Released API wrapper.
   - Pattern: `SELECT ... FROM <sap_std_table>` where the table is SAP-namespace and internal
     (e.g. `VBAK`, `VBAP`, `BSEG`, `MARA`, `LIKP`) and no released CDS view / API is used.
   - Not forbidden: `SELECT` on a customer-namespace table (`Z*`, `Y*`) or on a **released** CDS
     view (`I_*` interface views, `C_*` consumption views).
2. **`CALL FUNCTION` to a non-released Function Module.**
   - Pattern: `CALL FUNCTION '<fm>'` where `<fm>` is not on the Released-API allow-list and not a
     customer FM. Released FMs / RFC-enabled released services are permitted.
3. **`WRITE TO` a system-managed field**, or any direct manipulation of system fields
   (`SY-*` writes, `MANDT`, audit/administrative columns).
4. **Direct write to a `MANDT`-keyed standard SAP table** (`INSERT`/`UPDATE`/`MODIFY`/`DELETE` on a
   client-dependent standard table) without going through a Released API / BAPI / RAP behaviour.
5. **Modification of a standard SAP program via `ENHANCEMENT`** (implicit/explicit enhancement
   spots, source-code plug-ins) where a **released BAdI** exists and should be used instead.
6. **`CALL FUNCTION ... DESTINATION`** to a non-BTP-approved destination pattern (uncontrolled
   external RFC), or use of an API SAP has flagged **obsolete** in an SAP Note.

## Released-API status indicators

An API/construct counts as **Released** (Level-B eligible) when any of these hold:

- CDS view / entity carries `@API.state: 'released'` (or is a published `I_*` / `C_*` view).
- Function module / class is marked with release contract **C1 (use system-internally + by
  customer)** — i.e. released for customer use, ABAP Cloud allowed.
- The object is a **released BAdI** (enhancement spot published for customer use).
- It is part of the **RAP** development model (released behaviour definitions, released business
  objects).

Treated as **non-released** (Level C or D):

- Release contract **C0** (not released) or **internal** APIs.
- Any FM/class/table not on the released allow-list and not in the customer namespace.

## Edition-specific strictness

The same non-released construct classifies differently by edition. Apply the matching column.

| Construct | on-premise | private-cloud | public-cloud |
|---|---|---|---|
| Uses only Released APIs | B | B | B |
| Non-released API **with** existing released BAdI/API coverage | C | C | **D** |
| Non-released API **without** coverage | C | C | **D** |
| Any forbidden construct (list above) | D | D | D |
| Standard SAP object, unmodified | A | A | A |

**Rule of thumb:** public-cloud enforces **Released-only** — any non-released API usage is Level D.
Private-cloud and on-premise treat non-released-with-coverage as Level C (migratable on-stack).

## Confidence & review

- Rule-based pre-classification assigns `confidence`. If `confidence < 0.7`, set
  `review_recommended=True` and defer the final level to the LLM.
- Ambiguous cases to flag for review: dynamic table names (`SELECT ... FROM (lv_tabname)`),
  reflection/generic programming, macro-expanded code, and any object whose source could not be
  fully retrieved.
