# RICEFW Extensibility Patterns

> **Version:** 1.0.0
> Companion reference for the `extensibility-guidance` runtime skill and `app/extensibility/verdict.py`.
> Maps each RICEFW category to a default extensibility path with rationale. The **released-API
> override** (see the skill's decision tree) can upgrade a default `SIDE_BY_SIDE` to `ON_STACK`.

## Extensibility paths

| Path | Meaning |
|---|---|
| `KEY_USER` | Achievable via Key User Extensibility tools — UI adaptation, custom fields, simple field logic. No ABAP coding required for remediation. |
| `ON_STACK` | Rewritten using Released APIs / the ABAP Cloud Developer model; stays inside the S/4HANA stack. |
| `SIDE_BY_SIDE` | Better implemented as a decoupled BTP extension, separate from the digital core. |

## RICEFW category → default verdict

| Category | Typical object types | Default path | Rationale |
|---|---|---|---|
| **Reports** | PROG (output-only), CDS query views | `SIDE_BY_SIDE` | Reporting is a prime candidate for decoupling (SAC / BTP analytics). **Override:** if it reads only via Released APIs, keep `ON_STACK`. |
| **Interfaces** | RFC, IDoc, BAPI wrappers, REST/SOAP endpoints | `SIDE_BY_SIDE` | Integration belongs in BTP Integration Suite / Event Mesh, decoupled from the core. Rarely overridden. |
| **Conversions** | Data-migration programs, one-time loads | `SIDE_BY_SIDE` | One-time / transient logic must not live in the ongoing core; run as a BTP job or migration tool. |
| **Enhancements** | BAdI implementations, user exits, source plug-ins | *conditional* | **If a released BAdI exists → `ON_STACK`.** If no released extension point exists → `SIDE_BY_SIDE`. This is the key branching category. |
| **Forms** | SAPScript, SmartForms, Adobe Forms | `SIDE_BY_SIDE` | Document output → BTP Document / Forms service. |
| **Workflows** | Classic (obsolete WS) workflows | `SIDE_BY_SIDE` | Rebuild in SAP Build Process Automation; classic workflow is obsolete on the clean core. |

## Decision notes

- **Enhancements are the branching category.** Always check released-BAdI availability first:
  - Released BAdI exists for the enhancement point → `ON_STACK` (implement the released BAdI in the
    ABAP Cloud model).
  - No released BAdI / relies on implicit or source-code enhancement → `SIDE_BY_SIDE`.
- **Released-API override applies across categories.** Any object that uses *only* Released APIs and
  fits the ABAP Cloud model can be `ON_STACK`, even if its RICEFW default is `SIDE_BY_SIDE`. Report
  both the category and the override in the rationale.
- **Level A ⇒ `ON_STACK` unconditionally** — already compliant, remains in place.
- **Key-User short-circuit** — if the change is field-level UI/custom-field/simple-logic reachable
  through Key User tools, prefer `KEY_USER` over any ABAP path (no code to migrate).

## Rationale citations

Each verdict should cite SAP extensibility framework guidance, e.g.:
- "SAP extensibility framework — On-Stack Developer Extensibility (ABAP Cloud) for released-API-only logic."
- "SAP extensibility framework — Side-by-Side on BTP for integration/decoupled workloads."
- "Key User Extensibility — custom fields & logic via adaptation tools, no developer effort."
