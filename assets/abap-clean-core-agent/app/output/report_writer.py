"""Report export (R6) — JSON + Markdown files.

Serialises an :class:`AnalysisResult` to ``./reports/clean-core-<scope_id>-<timestamp>.json`` and
a companion ``.md`` (governance scorecard + developer-view table). Emits M6 on completion.

The reports directory is created on demand. Filenames use a filesystem-safe ``scope_id`` and a
``YYYYMMDD-HHMMSS`` timestamp so repeated runs never collide.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from output.result import AnalysisResult
from output.views import render_developer_view, render_governance_view

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("./reports")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _summary(result: AnalysisResult) -> dict:
    counts = result.level_counts()
    ext = result.extensibility_counts()
    return {
        "total": result.total,
        "level_a": counts["A"], "level_b": counts["B"],
        "level_c": counts["C"], "level_d": counts["D"],
        "on_stack": ext["ON_STACK"], "side_by_side": ext["SIDE_BY_SIDE"],
        "key_user": ext["KEY_USER"],
    }


def _serialise(result: AnalysisResult) -> dict:
    return {
        "scope": result.scope_identifier,
        "edition": result.edition,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "remediation_depth": result.remediation_depth,
        "summary": _summary(result),
        "objects": [
            {
                "name": o.name, "type": o.type, "package": o.package,
                "level": o.level, "rationale": o.rationale,
                "extensibility": o.extensibility, "ricefw_category": o.ricefw_category,
                "remediation": o.remediation, "review_recommended": o.review_recommended,
            }
            for o in result.objects_sorted_by_risk()
        ],
    }


def write_json_report(result: AnalysisResult, scope_id: str, *, reports_dir: Path = REPORTS_DIR) -> Path:
    """Write the full AnalysisResult as JSON. Returns the written path."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"clean-core-{scope_id}-{_timestamp()}.json"
    path.write_text(json.dumps(_serialise(result), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_markdown_report(result: AnalysisResult, scope_id: str, *, reports_dir: Path = REPORTS_DIR) -> Path:
    """Write a human-readable Markdown report (governance scorecard + developer table)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"clean-core-{scope_id}-{_timestamp()}.md"
    body = "\n\n".join([
        f"# Clean Core Analysis — {result.scope_identifier}",
        render_governance_view(result),
        render_developer_view(result),
    ])
    path.write_text(body + "\n", encoding="utf-8")
    return path


def write_reports(result: AnalysisResult, scope_id: str, *, reports_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    """Write both reports; emit M6.achieved/M6.missed. Returns (json_path, md_path)."""
    try:
        json_path = write_json_report(result, scope_id, reports_dir=reports_dir)
        md_path = write_markdown_report(result, scope_id, reports_dir=reports_dir)
    except OSError as exc:
        logger.warning("M6.missed: reports could not be saved for scope '%s': %s", scope_id, exc)
        raise
    logger.info(
        "M6.achieved: reports saved — '%s' and '%s' written successfully",
        json_path.name, md_path.name,
    )
    return json_path, md_path
