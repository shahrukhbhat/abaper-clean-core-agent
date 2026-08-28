"""Pipeline analysis tool exposed to the agent LLM.

Wraps the deterministic analysis pipeline (scope → retrieve → classify → verdict → remediate →
report) as a single LangChain ``StructuredTool`` named ``analyze_scope``. The LLM calls it once it
has gathered scope + edition + remediation depth from the user. Milestone M1 (scope defined) is
logged here; M2–M6 are logged by the engines the pipeline calls.

Keeping orchestration in a tool (not in ``agent.py``) preserves the 4-decorator constraint and lets
the LLM drive the conversation while the heavy lifting stays deterministic and testable.
"""

import logging
from typing import Sequence

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from classification.engine import classify_objects
from extensibility.verdict import decide_objects
from output.report_writer import write_reports
from output.result import AnalysisResult, ObjectResult
from output.views import render_view
from remediation.generator import generate_plan
from scope_parser import ScopeParseError, parse_scope
from tools.retrieve_objects import retrieve_objects

logger = logging.getLogger(__name__)


class AnalyzeScopeInput(BaseModel):
    scope: str = Field(description="Package name(s), a transport request (<SID>K<6-digit>), or object list (optionally TYPE:NAME).")
    edition: str | None = Field(default=None, description="S/4HANA edition: on-premise | private-cloud | public-cloud. Defaults to on-premise.")
    depth: str = Field(default="principle", description="Remediation depth: principle | api | code. Defaults to principle.")
    view: str = Field(default="developer", description="View to render: developer | architect | governance.")
    write_report: bool = Field(default=True, description="Whether to write JSON + Markdown reports to ./reports/.")


async def run_pipeline(
    scope_raw: str,
    tools: Sequence[BaseTool],
    *,
    edition: str | None = None,
    depth: str = "principle",
    view: str = "developer",
    write_report: bool = True,
) -> tuple[AnalysisResult, str]:
    """Execute the full analysis pipeline. Returns (result, rendered_view_markdown)."""
    # M1 — Scope Defined
    try:
        scope = parse_scope(scope_raw, edition=edition)
    except ScopeParseError as exc:
        logger.warning("M1.missed: scope validation failed — no valid objects identified for input '%s': %s", scope_raw, exc)
        raise

    # Retrieve objects (M2 logged inside retrieve_objects).
    objects = await retrieve_objects(scope, tools, fetch_source=True)
    logger.info(
        "M1.achieved: scope confirmed — %d object(s) identified in scope '%s'",
        len(objects), scope.scope_id,
    )

    # M3 — classification; M4 — extensibility; M5 — remediation.
    hints = classify_objects(objects, scope.edition)
    verdicts = decide_objects(objects, hints)
    plan = generate_plan(hints, depth)

    # Assemble the single AnalysisResult every view/report reads from.
    obj_lookup = {o.name: o for o in objects}
    records: list[ObjectResult] = []
    for name, hint in hints.items():
        obj = obj_lookup.get(name)
        verdict = verdicts.get(name)
        guidance = plan.get(name)
        records.append(ObjectResult(
            name=name,
            type=obj.type if obj else "UNKNOWN",
            level=hint.candidate_level,
            package=obj.package if obj else None,
            rationale="; ".join(hint.rule_hits),
            extensibility=verdict.path if verdict else "",
            ricefw_category=verdict.ricefw_category if verdict else "",
            remediation=(guidance.principle if guidance and guidance.needs_remediation
                         else "No remediation needed — already compliant."),
            review_recommended=hint.review_recommended,
        ))

    result = AnalysisResult(
        scope_id=scope.scope_id,
        scope_identifier=",".join(scope.identifiers),
        edition=scope.edition or "on-premise",
        remediation_depth=depth,
        objects=records,
    )

    if write_report:
        try:
            write_reports(result, scope.scope_id)  # M6 logged inside
        except OSError:
            logger.warning("M6.missed: report export failed — files could not be written for scope '%s'", scope.scope_id)

    return result, render_view(view, result)


def get_pipeline_tools(tools: Sequence[BaseTool]) -> list[StructuredTool]:
    """Build the ``analyze_scope`` tool bound to the current request's MCP ``tools``.

    Bound per-request because object retrieval needs the user's MCP tools (credentials-scoped).
    """

    async def _analyze(
        scope: str,
        edition: str | None = None,
        depth: str = "principle",
        view: str = "developer",
        write_report: bool = True,
    ) -> str:
        try:
            _result, rendered = await run_pipeline(
                scope, tools, edition=edition, depth=depth, view=view, write_report=write_report,
            )
        except ScopeParseError as exc:
            return f"Scope error: {exc}"
        return rendered

    return [StructuredTool(
        name="analyze_scope",
        description=(
            "Run the full Clean Core analysis pipeline over an ABAP scope: parse scope, retrieve "
            "objects, classify (A–D), assign extensibility verdicts, generate remediation, and "
            "render the requested audience view (developer/architect/governance). Writes JSON+MD "
            "reports unless write_report is false. Call this once you have the scope, edition, and "
            "remediation depth."
        ),
        args_schema=AnalyzeScopeInput,
        coroutine=_analyze,
    )]
