"""Remediation guidance generator.

Produces remediation guidance for **Level C and Level D** objects at a selectable depth —
``principle`` / ``api`` / ``code`` — per the ``remediation-templates`` runtime skill.

Depth semantics (deeper depths include the shallower content):
  - ``principle`` — deterministic: explains the violated rule (from the classification rationale)
    and cites the level-specific SAP doc link. No LLM required.
  - ``api``        — names the replacement Released API / BAdI + migration complexity. The concrete
    replacement is synthesised by the LLM; this module provides the structured envelope.
  - ``code``       — a refactored ABAP snippet, **always** prefixed with the verbatim disclaimer.

Levels A and B are already compliant and receive *no* remediation — the generator returns a
``no_remediation_needed`` result and never fabricates a fix.
"""

import logging
from dataclasses import dataclass, field

from classification.engine import ClassificationHint

logger = logging.getLogger(__name__)

Depth = str  # "principle" | "api" | "code"
DEPTHS: tuple[Depth, ...] = ("principle", "api", "code")
DEFAULT_DEPTH: Depth = "principle"

# Verbatim, mandatory disclaimer for every `code`-depth output. Do not reword or shorten.
CODE_DISCLAIMER = (
    "⚠️ This snippet is a starting point for developer validation and is NOT production-ready. "
    "Review and test thoroughly before applying."
)

# Level-specific documentation links. Level D → forbidden-modifications; Level C → ABAP Cloud guide.
_DOC_LINKS: dict[str, str] = {
    "D": "https://help.sap.com/docs/clean-core/forbidden-modifications",
    "C": "https://help.sap.com/docs/abap-cloud/released-api-usage",
}

_REMEDIABLE_LEVELS = ("C", "D")


@dataclass
class RemediationGuidance:
    object_name: str
    level: str
    depth: Depth
    needs_remediation: bool
    principle: str = ""            # rule explanation + doc link (always present when remediable)
    doc_url: str = ""
    # api-depth fields — populated by the LLM layer; envelope provided here.
    current_construct: str = ""
    recommended_replacement: str = ""
    migration_complexity: str = ""  # "low" | "medium" | "high"
    # code-depth fields.
    disclaimer: str = ""
    code_snippet: str = ""          # LLM-produced; disclaimer is enforced separately
    needs_llm: bool = False         # True when api/code depth requires LLM synthesis
    notes: list[str] = field(default_factory=list)


def _normalise_depth(depth: Depth | None) -> Depth:
    d = (depth or DEFAULT_DEPTH).lower().strip()
    return d if d in DEPTHS else DEFAULT_DEPTH


def generate_object(
    object_name: str,
    hint: ClassificationHint,
    depth: Depth | None = None,
) -> RemediationGuidance:
    """Generate remediation guidance for one classified object at ``depth``.

    Level A/B → returns ``needs_remediation=False`` (no fix). Level C/D → builds the principle
    layer deterministically and flags ``needs_llm`` for api/code depths.
    """
    depth = _normalise_depth(depth)
    level = hint.candidate_level

    if level not in _REMEDIABLE_LEVELS:
        return RemediationGuidance(
            object_name=object_name, level=level, depth=depth, needs_remediation=False,
            principle="No remediation needed — object is already Clean Core compliant.",
        )

    doc_url = _DOC_LINKS.get(level, _DOC_LINKS["C"])
    rationale = "; ".join(hint.rule_hits) if hint.rule_hits else "non-compliant construct detected"
    principle = (
        f"Level {level} — {rationale}. This breaks Clean Core because non-released/forbidden "
        f"constructs are not covered by SAP's stability contract and may change without notice. "
        f"See: {doc_url}"
    )

    guidance = RemediationGuidance(
        object_name=object_name, level=level, depth=depth, needs_remediation=True,
        principle=principle, doc_url=doc_url,
    )

    # api and code both need LLM synthesis of the concrete replacement/snippet.
    if depth in ("api", "code"):
        guidance.needs_llm = True
        guidance.current_construct = rationale
        guidance.notes.append("api/code depth requires LLM synthesis of the released replacement.")

    if depth == "code":
        # The disclaimer is set deterministically and verbatim regardless of LLM output.
        guidance.disclaimer = CODE_DISCLAIMER

    return guidance


def generate_plan(
    hints: dict[str, ClassificationHint],
    depth: Depth | None = None,
) -> dict[str, RemediationGuidance]:
    """Generate a remediation plan for a batch; emit M5 on completion. Keyed by object name.

    Only Level C/D objects carry a fix; A/B are recorded as ``needs_remediation=False``.
    """
    depth = _normalise_depth(depth)
    plan: dict[str, RemediationGuidance] = {}
    for name, hint in hints.items():
        plan[name] = generate_object(name, hint, depth)

    total = len(plan)
    remediable = sum(1 for g in plan.values() if g.needs_remediation)
    if total:
        logger.info(
            "M5.achieved: remediation plan complete — %d objects at depth '%s'; %d need remediation (C/D)",
            total, depth, remediable,
        )
    else:
        logger.warning("M5.missed: remediation plan empty — no classified objects supplied")
    return plan
