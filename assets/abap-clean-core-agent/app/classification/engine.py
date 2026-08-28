"""Rule-based Clean Core pre-classifier.

Scans ABAP source for forbidden constructs before any LLM is invoked and assigns a
candidate level (A/B/C/D). Clear, unambiguous rule hits produce a definitive verdict
without an LLM call; ambiguous cases are flagged ``review_recommended=True`` for the
LLM to finalise.

Rule catalogue mirrors ``skills/clean-core-classification/references/clean-core-rules.md``.
"""

import logging
import re
from dataclasses import dataclass, field

from classification.rules_config import EditionPolicy, get_edition_policy
from scope_parser import Edition
from tools.retrieve_objects import ABAPObject

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7

# SAP standard/internal tables commonly seen in custom code. Not exhaustive, but the
# high-signal set for a rule-based first pass. Customer tables (Z*/Y*) are excluded.
_SAP_INTERNAL_TABLES = {
    "VBAK", "VBAP", "VBEP", "VBKD", "LIKP", "LIPS", "VBRK", "VBRP",
    "BSEG", "BKPF", "BSID", "BSIK", "MARA", "MARC", "MARD", "MBEW",
    "EKKO", "EKPO", "KNA1", "LFA1", "MSEG", "MKPF", "COEP", "ACDOCA",
}

# Released CDS view namespaces / prefixes that make a SELECT compliant.
_RELEASED_VIEW_RE = re.compile(r"\bFROM\s+[IC]_[A-Za-z0-9_]+", re.IGNORECASE)


@dataclass
class ClassificationHint:
    candidate_level: str  # "A" | "B" | "C" | "D"
    rule_hits: list[str] = field(default_factory=list)
    confidence: float = 1.0
    review_recommended: bool = False
    edition: Edition | None = None


def _iter_select_targets(source: str) -> list[str]:
    """Return the table/view names targeted by SELECT ... FROM statements."""
    return re.findall(r"\bSELECT\b[\s\S]*?\bFROM\s+([A-Za-z_/][A-Za-z0-9_/]*)", source, re.IGNORECASE)


def _detect_forbidden(source: str) -> list[str]:
    """Detect Level-D forbidden constructs. Returns a list of human-readable rule hits."""
    hits: list[str] = []
    upper = source

    # #1 — direct SELECT on an SAP internal/standard table without a Released API.
    for target in _iter_select_targets(upper):
        name = target.upper().lstrip("/")
        if name in _SAP_INTERNAL_TABLES:
            hits.append(f"D#1: direct SELECT on SAP internal table {name} without a Released API")

    # #2 — CALL FUNCTION to a non-released FM (heuristic: any non-Z/Y FM literal that is
    # not an obvious released service). Customer-namespace FMs are allowed.
    for fm in re.findall(r"CALL\s+FUNCTION\s+'([^']+)'", upper, re.IGNORECASE):
        fm_u = fm.upper()
        if not (fm_u.startswith("Z") or fm_u.startswith("Y") or fm_u.startswith("/")):
            hits.append(f"D#2: CALL FUNCTION to non-released FM '{fm_u}'")

    # #3 — WRITE TO a system field / SY-* assignment.
    if re.search(r"\bSY-\w+\s*=", upper) or re.search(r"WRITE\s+TO\s+SY-", upper, re.IGNORECASE):
        hits.append("D#3: direct write to a system field (SY-*)")

    # #4 — direct DML on an SAP internal (client-dependent) table.
    for verb in ("INSERT", "UPDATE", "MODIFY", "DELETE"):
        for tgt in re.findall(rf"\b{verb}\s+([A-Za-z_/][A-Za-z0-9_/]*)", upper, re.IGNORECASE):
            if tgt.upper().lstrip("/") in _SAP_INTERNAL_TABLES:
                hits.append(f"D#4: direct {verb} on SAP standard table {tgt.upper()} without a Released API")

    # #6 — CALL FUNCTION ... DESTINATION (uncontrolled external RFC).
    if re.search(r"CALL\s+FUNCTION\s+'[^']+'\s+DESTINATION", upper, re.IGNORECASE):
        hits.append("D#6: CALL FUNCTION ... DESTINATION (uncontrolled external RFC)")

    return hits


def _detect_enhancement_without_badi(source: str) -> list[str]:
    """#5 — ENHANCEMENT of standard SAP (flagged; BAdI availability decided later)."""
    if re.search(r"\bENHANCEMENT\b", source, re.IGNORECASE) and not re.search(r"\bBADI\b", source, re.IGNORECASE):
        return ["D#5: ENHANCEMENT of standard SAP without a released BAdI"]
    return []


def _uses_released_api(source: str) -> bool:
    return bool(_RELEASED_VIEW_RE.search(source))


# Dynamic SELECT target — `SELECT ... FROM (lv_tabname)`. The table is unknown at
# static-analysis time, so it cannot be confirmed released or forbidden by regex.
_DYNAMIC_SELECT_RE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\s+\(", re.IGNORECASE)

# SELECT on a non-customer, non-released, non-internal table: an SAP-namespace table
# we don't have on the internal blocklist and that isn't an I_/C_ released view. Can't
# be confidently called forbidden (not on the internal set) or clean (not released).
_SELECT_TARGET_RE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\s+([A-Za-z_/][A-Za-z0-9_/]*)", re.IGNORECASE)


def _ambiguous_signal(source: str) -> bool:
    """Detect genuinely-ambiguous constructs the regex engine cannot classify confidently.

    These are *not* forbidden (D#* would have fired) and *not* clearly released. They warrant
    ``review_recommended`` so the LLM can finalise, rather than a confident C/D verdict. A raw
    non-released FM call is **not** here — that is forbidden (D#2) and handled by ``_detect_forbidden``.
    """
    if _DYNAMIC_SELECT_RE.search(source):
        return True
    for target in _SELECT_TARGET_RE.findall(source):
        name = target.upper().lstrip("/")
        if name in _SAP_INTERNAL_TABLES:
            continue  # forbidden — already flagged as D#1
        if name.startswith(("Z", "Y", "I_", "C_")):
            continue  # customer table or released view — clean
        return True  # an SAP-namespace table we cannot confirm as released
    return False


def classify_object(obj: ABAPObject, edition: Edition | None = None) -> ClassificationHint:
    """Pre-classify a single object. Returns a :class:`ClassificationHint`."""
    policy: EditionPolicy = get_edition_policy(edition)

    if obj.retrieval_status != "success" or not obj.source:
        return ClassificationHint(
            candidate_level="D",
            rule_hits=["source unavailable — cannot verify compliance"],
            confidence=0.0,
            review_recommended=True,
            edition=edition,
        )

    source = obj.source
    forbidden = _detect_forbidden(source) + _detect_enhancement_without_badi(source)

    if forbidden:
        return ClassificationHint(
            candidate_level="D", rule_hits=forbidden, confidence=0.95,
            review_recommended=False, edition=edition,
        )

    uses_released = _uses_released_api(source)
    ambiguous = _ambiguous_signal(source)

    # An ambiguous construct (dynamic SELECT, or a SELECT on an SAP-namespace table we
    # cannot confirm released) is neither forbidden nor clearly clean. Defer to the LLM.
    # Edition still shapes the candidate level: public-cloud leans D (Released-only),
    # on-prem/private lean C (migratable on-stack). Evaluate before the Released-only "B"
    # verdict so a released view alongside an unconfirmed target is not mistaken for clean B.
    if ambiguous:
        level = policy.non_released_level  # "C" on-prem/private, "D" public-cloud
        if level == "C":
            hit = ("C: mixed usage — released API plus an unconfirmed construct"
                   if uses_released
                   else "C: non-released construct present (verify released BAdI/API coverage)")
        else:
            hit = "D: unconfirmed non-released usage on public-cloud (Released-only enforced)"
        return ClassificationHint(
            candidate_level=level, rule_hits=[hit], confidence=0.6,
            review_recommended=True, edition=edition,
        )

    if uses_released:
        return ClassificationHint(
            candidate_level="B", rule_hits=["B: uses only Released APIs"],
            confidence=0.85, review_recommended=False, edition=edition,
        )

    # No released signal, no forbidden constructs, custom code present but ambiguous.
    return ClassificationHint(
        candidate_level="C",
        rule_hits=["ambiguous — no clear released-API usage detected"],
        confidence=0.5, review_recommended=True, edition=edition,
    )


def classify_objects(objects: list[ABAPObject], edition: Edition | None = None) -> dict[str, ClassificationHint]:
    """Classify a batch; emit M3 on completion. Keyed by object name."""
    hints: dict[str, ClassificationHint] = {}
    for obj in objects:
        hint = classify_object(obj, edition)
        if hint.confidence < CONFIDENCE_THRESHOLD:
            hint.review_recommended = True
        hints[obj.name] = hint

    total = len(hints)
    dist = {lvl: sum(1 for h in hints.values() if h.candidate_level == lvl) for lvl in "ABCD"}
    unclassified = sum(1 for h in hints.values() if h.confidence == 0.0)
    if total and unclassified == 0:
        logger.info(
            "M3.achieved: classification complete — %d objects classified; distribution: A=%d, B=%d, C=%d, D=%d",
            total, dist["A"], dist["B"], dist["C"], dist["D"],
        )
    else:
        logger.warning(
            "M3.missed: classification incomplete — %d objects could not be classified",
            unclassified,
        )
    return hints
