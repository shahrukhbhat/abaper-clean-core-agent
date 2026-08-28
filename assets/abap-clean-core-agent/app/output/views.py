"""Audience-appropriate views (R5).

Three Markdown renderers over a single :class:`AnalysisResult`:
  - ``render_developer_view``  — per-object table, sorted D → C → B → A.
  - ``render_architect_view``  — objects grouped by extensibility path, with risk ratings + top-10.
  - ``render_governance_view`` — executive scorecard: level distribution, overall risk, split, top-10.

All three read only from the passed-in result — no re-analysis is performed to switch views.
"""

from output.result import AnalysisResult, ObjectResult


def _pct(n: int, total: int) -> str:
    return f"{(100 * n / total):.1f}%" if total else "0.0%"


def render_developer_view(result: AnalysisResult) -> str:
    """Per-object Markdown table, sorted by level D → C → B → A."""
    lines = [
        f"## Developer View — scope `{result.scope_identifier}` ({result.edition})",
        "",
        "| Object Name | Type | Package | Level | Extensibility | RICEFW | Remediation |",
        "|---|---|---|---|---|---|---|",
    ]
    if not result.objects:
        lines.append("| _(no objects)_ | | | | | | |")
    for o in result.objects_sorted_by_risk():
        remediation = (o.remediation or "—").replace("\n", " ").strip()
        if len(remediation) > 80:
            remediation = remediation[:77] + "…"
        pkg = o.package or "—"
        lines.append(
            f"| {o.name} | {o.type} | {pkg} | {o.level} | {o.extensibility or '—'} "
            f"| {o.ricefw_category or '—'} | {remediation} |"
        )
    return "\n".join(lines)


def _risk_line(o: ObjectResult) -> str:
    review = " _(review)_" if o.review_recommended else ""
    return f"  - {o.name} ({o.type}) — Level {o.level} / {o.risk}{review}"


def render_architect_view(result: AnalysisResult) -> str:
    """Extensibility map: objects grouped by path, each with risk ratings; top-10 highlighted."""
    lines = [
        f"## Architect View — scope `{result.scope_identifier}` ({result.edition})",
        "",
        f"**Overall risk:** {result.overall_risk()} · **Objects:** {result.total}",
        "",
        "### Top 10 highest-risk objects",
    ]
    top = result.top_risk(10)
    if top:
        lines.extend(_risk_line(o) for o in top)
    else:
        lines.append("  - _(none)_")
    lines.append("")
    lines.append("### Extensibility map")

    by_path: dict[str, list[ObjectResult]] = {"ON_STACK": [], "SIDE_BY_SIDE": [], "KEY_USER": []}
    for o in result.objects_sorted_by_risk():
        by_path.setdefault(o.extensibility or "UNASSIGNED", []).append(o)

    for path in ("ON_STACK", "SIDE_BY_SIDE", "KEY_USER"):
        group = by_path.get(path, [])
        lines.append(f"\n**{path}** — {len(group)} object(s)")
        if group:
            lines.extend(_risk_line(o) for o in group)
        else:
            lines.append("  - _(none)_")

    # Any objects with an unexpected/unassigned path — surface rather than silently drop.
    extras = {p: v for p, v in by_path.items()
              if p not in ("ON_STACK", "SIDE_BY_SIDE", "KEY_USER") and v}
    for path, group in extras.items():
        lines.append(f"\n**{path}** — {len(group)} object(s)")
        lines.extend(_risk_line(o) for o in group)

    return "\n".join(lines)


def render_governance_view(result: AnalysisResult) -> str:
    """Executive scorecard: level distribution, overall risk, extensibility split, top-10."""
    total = result.total
    counts = result.level_counts()
    ext = result.extensibility_counts()

    lines = [
        f"## Governance Scorecard — scope `{result.scope_identifier}` ({result.edition})",
        "",
        f"**Overall risk rating: {result.overall_risk()}**  ·  Total objects: {total}",
        "",
        "### Clean Core level distribution",
        "| Level | Count | Percentage |",
        "|---|---|---|",
    ]
    names = {"A": "A — Standard", "B": "B — Clean", "C": "C — Mixed", "D": "D — Non-compliant"}
    for lvl in "ABCD":
        lines.append(f"| {names[lvl]} | {counts[lvl]} | {_pct(counts[lvl], total)} |")

    lines += [
        "",
        "### Extensibility split",
        f"- On-Stack: {ext['ON_STACK']}",
        f"- Side-by-Side: {ext['SIDE_BY_SIDE']}",
        f"- Key User: {ext['KEY_USER']}",
        "",
        "### Top 10 highest-risk objects",
    ]
    top = result.top_risk(10)
    if top:
        lines.extend(f"- {o.name} — Level {o.level} ({o.risk})" for o in top)
    else:
        lines.append("- _(none)_")

    return "\n".join(lines)


# Audience-keyword → renderer, for agent view selection.
_VIEW_KEYWORDS: dict[str, str] = {
    "developer": "developer", "dev": "developer",
    "architect": "architect", "architecture": "architect",
    "governance": "governance", "scorecard": "governance",
    "summary": "governance", "executive": "governance",
}

_RENDERERS = {
    "developer": render_developer_view,
    "architect": render_architect_view,
    "governance": render_governance_view,
}


def select_view(text: str, default: str = "developer") -> str:
    """Pick a view name from audience keywords in a user message (first match wins)."""
    low = (text or "").lower()
    for kw, view in _VIEW_KEYWORDS.items():
        if kw in low:
            return view
    return default


def render_view(view: str, result: AnalysisResult) -> str:
    """Render a named view ('developer'|'architect'|'governance')."""
    return _RENDERERS.get(view, render_developer_view)(result)
