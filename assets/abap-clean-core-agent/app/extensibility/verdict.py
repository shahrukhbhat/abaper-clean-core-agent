"""Extensibility verdict engine.

Maps a classified ABAP object to one SAP extensibility path — ``KEY_USER``, ``ON_STACK``,
or ``SIDE_BY_SIDE`` — using the deterministic decision tree from the ``extensibility-guidance``
skill and the RICEFW category defaults in ``references/ricefw-patterns.md``.

Decision order (first match wins), mirroring the skill:
  1. Level A  → ON_STACK (already compliant, nothing to move).
  2. Key-User-addressable  → KEY_USER (field-level UI / custom field, no ABAP to migrate).
  3. RICEFW default, then the released-API override upgrades a would-be SIDE_BY_SIDE to ON_STACK.

The verdict says *where* the functionality should live after remediation, not *how* to write it.
"""

import logging
import re
from dataclasses import dataclass, field

from classification.engine import ClassificationHint
from tools.retrieve_objects import ABAPObject

logger = logging.getLogger(__name__)

ExtensibilityPath = str  # "KEY_USER" | "ON_STACK" | "SIDE_BY_SIDE"
RicefwCategory = str     # Report | Interface | Conversion | Enhancement | Form | Workflow | Unknown


@dataclass
class ExtensibilityVerdict:
    object_name: str
    path: ExtensibilityPath
    ricefw_category: RicefwCategory
    rationale: str
    review_recommended: bool = False


# --- RICEFW category inference ------------------------------------------------------------
# Signals are ordered by specificity; the first strong match wins. Object type gives a coarse
# hint, source patterns refine it. Deliberately conservative — ambiguity defers to review.

_INTERFACE_RE = re.compile(
    r"\b(CALL\s+FUNCTION\s+'[^']+'\s+DESTINATION|IDOC|BAPI_|RFC|/IWBEP/|ODATA|HTTP_CLIENT|REST|SOAP)\b",
    re.IGNORECASE,
)
_CONVERSION_RE = re.compile(r"\b(LSMW|BATCH\s+INPUT|BDC_|CALL\s+TRANSACTION|MIGRATION|DATA[_ ]?LOAD)\b", re.IGNORECASE)
_ENHANCEMENT_RE = re.compile(r"\b(ENHANCEMENT|BADI|GET\s+BADI|CALL\s+BADI|USER[_ ]?EXIT|CUSTOMER-FUNCTION)\b", re.IGNORECASE)
_FORM_RE = re.compile(r"\b(SAPSCRIPT|SMARTFORM|SSF_|ADOBE|FP_|SFP\b|OPEN\s+FORM|WRITE_FORM)\b", re.IGNORECASE)
_WORKFLOW_RE = re.compile(r"\b(SWWWIHEAD|WORKFLOW|SWE_|SWW_|WS[0-9]{6,}|SAP_WAPI)\b", re.IGNORECASE)
_REPORT_RE = re.compile(r"\b(WRITE\b|WRITE\s*:|ALV|CL_SALV|REUSE_ALV|LIST-PROCESSING|SELECTION-SCREEN)\b", re.IGNORECASE)


def _infer_ricefw_category(obj: ABAPObject) -> RicefwCategory:
    """Infer the RICEFW category from object type + dominant source behaviour.

    Conservative: matches the most specific behavioural signal first; returns "Unknown"
    when nothing dominant is present so the caller can defer to review.
    """
    src = obj.source or ""
    otype = (obj.type or "").upper()

    # Type-driven strong hints first.
    if otype in ("FUGR", "FUNC") and _INTERFACE_RE.search(src):
        return "Interface"
    if otype in ("SSFO", "FORM", "ADSP") or _FORM_RE.search(src):
        return "Form"
    if otype in ("WFLW",) or _WORKFLOW_RE.search(src):
        return "Workflow"

    # Behavioural signals (specific → general).
    if _ENHANCEMENT_RE.search(src):
        return "Enhancement"
    if _CONVERSION_RE.search(src):
        return "Conversion"
    if _INTERFACE_RE.search(src):
        return "Interface"
    if _REPORT_RE.search(src) or otype == "PROG":
        return "Report"
    return "Unknown"


# RICEFW category → default path (from ricefw-patterns.md). Enhancement is conditional and
# resolved in the tree (released-BAdI branch), so its listed default is the no-coverage fallback.
_RICEFW_DEFAULT: dict[RicefwCategory, ExtensibilityPath] = {
    "Report": "SIDE_BY_SIDE",
    "Interface": "SIDE_BY_SIDE",
    "Conversion": "SIDE_BY_SIDE",
    "Enhancement": "SIDE_BY_SIDE",
    "Form": "SIDE_BY_SIDE",
    "Workflow": "SIDE_BY_SIDE",
    "Unknown": "SIDE_BY_SIDE",
}

# Levels whose sole released-API usage qualifies for the on-stack override.
_RELEASED_ONLY_LEVEL = "B"

_KEY_USER_RE = re.compile(
    r"\b(CUSTOM\s*FIELD|APPEND\s+STRUCTURE|CI_[A-Z0-9_]+|KEY\s*USER|FIELD\s+EXTENSION|ADAPTATION)\b",
    re.IGNORECASE,
)


def _has_released_badi(source: str) -> bool:
    """A released BAdI reference in the source indicates an on-stack extension point exists."""
    return bool(re.search(r"\bGET\s+BADI\b|\bCALL\s+BADI\b|BADI\s+[A-Z]", source, re.IGNORECASE))


def _is_key_user_addressable(obj: ABAPObject, category: RicefwCategory) -> bool:
    """Field-level UI / custom-field logic reachable via Key User tools — no ABAP to migrate."""
    return bool(obj.source and _KEY_USER_RE.search(obj.source))


def decide_object(obj: ABAPObject, hint: ClassificationHint) -> ExtensibilityVerdict:
    """Apply the extensibility decision tree to one classified object."""
    level = hint.candidate_level
    category = _infer_ricefw_category(obj)

    # 1 — Level A: already compliant, stays on the stack unconditionally.
    if level == "A":
        return ExtensibilityVerdict(
            object_name=obj.name, path="ON_STACK", ricefw_category=category,
            rationale="Level A (standard/unmodified) → ON_STACK; already compliant, nothing to move.",
        )

    # 2 — Key-User short-circuit: no ABAP migration needed.
    if _is_key_user_addressable(obj, category):
        return ExtensibilityVerdict(
            object_name=obj.name, path="KEY_USER", ricefw_category=category,
            rationale="Field-level/custom-field change reachable via Key User Extensibility → KEY_USER (no ABAP to migrate).",
        )

    source = obj.source or ""
    uses_released_only = level == _RELEASED_ONLY_LEVEL

    # 3 — Enhancement is the branching category: released BAdI → ON_STACK, else SIDE_BY_SIDE.
    if category == "Enhancement":
        if uses_released_only or _has_released_badi(source):
            return ExtensibilityVerdict(
                object_name=obj.name, path="ON_STACK", ricefw_category=category,
                rationale="Enhancement with a released BAdI available → ON_STACK (ricefw-patterns Enhancements: released-BAdI branch).",
            )
        return ExtensibilityVerdict(
            object_name=obj.name, path="SIDE_BY_SIDE", ricefw_category=category,
            rationale="Enhancement with no released BAdI coverage → SIDE_BY_SIDE (ricefw-patterns Enhancements: no-BAdI branch).",
            review_recommended=hint.review_recommended,
        )

    # 3 (cont.) — Released-API override upgrades any RICEFW default to ON_STACK.
    default = _RICEFW_DEFAULT.get(category, "SIDE_BY_SIDE")
    if uses_released_only:
        return ExtensibilityVerdict(
            object_name=obj.name, path="ON_STACK", ricefw_category=category,
            rationale=(f"{category} default is {default}, but object uses only Released APIs → "
                       f"released-API override to ON_STACK (ricefw-patterns {category})."),
        )

    return ExtensibilityVerdict(
        object_name=obj.name, path=default, ricefw_category=category,
        rationale=f"{category} default path → {default} (ricefw-patterns {category}); no released-API override applies.",
        review_recommended=hint.review_recommended or category == "Unknown",
    )


def decide_objects(
    objects: list[ABAPObject], hints: dict[str, ClassificationHint]
) -> dict[str, ExtensibilityVerdict]:
    """Produce extensibility verdicts for a batch; emit M4 on completion. Keyed by object name."""
    verdicts: dict[str, ExtensibilityVerdict] = {}
    for obj in objects:
        hint = hints.get(obj.name)
        if hint is None:
            continue
        verdicts[obj.name] = decide_object(obj, hint)

    total = len(verdicts)
    dist = {p: sum(1 for v in verdicts.values() if v.path == p)
            for p in ("KEY_USER", "ON_STACK", "SIDE_BY_SIDE")}
    if total and total == len([o for o in objects if o.name in hints]):
        logger.info(
            "M4.achieved: extensibility verdicts complete — %d objects; KEY_USER=%d, ON_STACK=%d, SIDE_BY_SIDE=%d",
            total, dist["KEY_USER"], dist["ON_STACK"], dist["SIDE_BY_SIDE"],
        )
    else:
        missing = len(objects) - total
        logger.warning(
            "M4.missed: extensibility verdicts incomplete — %d objects without a classification hint",
            missing,
        )
    return verdicts
