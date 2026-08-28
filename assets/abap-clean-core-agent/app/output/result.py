"""In-memory analysis result — the single object every view and report renders from.

An :class:`AnalysisResult` aggregates, per object, the outputs of the three engines
(classification, extensibility, remediation) plus scope metadata. Views (developer / architect /
governance) and the report writer read *only* from this object — no re-analysis to switch views.
"""

from dataclasses import dataclass, field

# Risk rating derived from Clean Core level. Level → rating and severity ordering live here so
# every view and report ranks objects identically.
_LEVEL_RISK: dict[str, str] = {"D": "HIGH", "C": "MEDIUM", "B": "LOW", "A": "NONE"}
_LEVEL_ORDER: dict[str, int] = {"D": 0, "C": 1, "B": 2, "A": 3}


def risk_rating(level: str) -> str:
    """Map a Clean Core level to its risk rating (HIGH/MEDIUM/LOW/NONE)."""
    return _LEVEL_RISK.get(level, "NONE")


def level_sort_key(level: str) -> int:
    """Sort key placing the most severe level (D) first."""
    return _LEVEL_ORDER.get(level, 99)


@dataclass
class ObjectResult:
    """One object's full analysis record."""

    name: str
    type: str
    level: str
    package: str | None = None
    rationale: str = ""
    extensibility: str = ""          # KEY_USER | ON_STACK | SIDE_BY_SIDE
    ricefw_category: str = ""
    remediation: str = ""            # short remediation summary (principle line, typically)
    review_recommended: bool = False

    @property
    def risk(self) -> str:
        return risk_rating(self.level)


@dataclass
class AnalysisResult:
    """Aggregate result for a whole scope — the source of truth for all rendering."""

    scope_id: str
    scope_identifier: str
    edition: str
    remediation_depth: str = "principle"
    objects: list[ObjectResult] = field(default_factory=list)

    # --- derived aggregates -------------------------------------------------------------
    @property
    def total(self) -> int:
        return len(self.objects)

    def level_counts(self) -> dict[str, int]:
        return {lvl: sum(1 for o in self.objects if o.level == lvl) for lvl in "ABCD"}

    def extensibility_counts(self) -> dict[str, int]:
        return {
            path: sum(1 for o in self.objects if o.extensibility == path)
            for path in ("KEY_USER", "ON_STACK", "SIDE_BY_SIDE")
        }

    def objects_sorted_by_risk(self) -> list[ObjectResult]:
        """Objects ordered most-severe first (D → C → B → A), stable within a level by name."""
        return sorted(self.objects, key=lambda o: (level_sort_key(o.level), o.name))

    def top_risk(self, n: int = 10) -> list[ObjectResult]:
        return self.objects_sorted_by_risk()[:n]

    def overall_risk(self) -> str:
        """HIGH if >20% Level D, MEDIUM if >20% Level C, else LOW."""
        if self.total == 0:
            return "LOW"
        counts = self.level_counts()
        pct_d = counts["D"] / self.total
        pct_c = counts["C"] / self.total
        if pct_d > 0.20:
            return "HIGH"
        if pct_c > 0.20:
            return "MEDIUM"
        return "LOW"
