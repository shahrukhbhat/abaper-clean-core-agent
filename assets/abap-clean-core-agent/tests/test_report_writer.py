"""Unit tests for the report writer (JSON schema, Markdown, filenames)."""

import json


def _result(add_agent_to_path):
    from output.result import AnalysisResult, ObjectResult

    objs = [
        ObjectResult(name="ZD1", type="CLAS", level="D", package="ZPKG",
                     extensibility="SIDE_BY_SIDE", ricefw_category="Report",
                     rationale="D#1", remediation="fix"),
        ObjectResult(name="ZB1", type="CLAS", level="B", package="ZPKG",
                     extensibility="ON_STACK"),
    ]
    return AnalysisResult(
        scope_id="zpkg", scope_identifier="ZPKG", edition="on-premise",
        remediation_depth="principle", objects=objs,
    )


class TestWriteReports:
    def test_json_schema(self, add_agent_to_path, tmp_path):
        from output.report_writer import write_json_report

        path = write_json_report(_result(add_agent_to_path), "zpkg", reports_dir=tmp_path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["scope"] == "ZPKG"
        assert data["edition"] == "on-premise"
        assert data["remediation_depth"] == "principle"
        assert "timestamp" in data
        assert data["summary"]["total"] == 2
        assert data["summary"]["level_d"] == 1
        assert data["summary"]["level_b"] == 1
        assert len(data["objects"]) == 2
        # most severe object first
        assert data["objects"][0]["name"] == "ZD1"

    def test_markdown_written(self, add_agent_to_path, tmp_path):
        from output.report_writer import write_markdown_report

        path = write_markdown_report(_result(add_agent_to_path), "zpkg", reports_dir=tmp_path)
        assert path.exists()
        body = path.read_text(encoding="utf-8")
        assert "Clean Core Analysis" in body
        assert "ZD1" in body

    def test_filenames_include_scope_and_timestamp(self, add_agent_to_path, tmp_path):
        from output.report_writer import write_reports

        json_path, md_path = write_reports(_result(add_agent_to_path), "zpkg", reports_dir=tmp_path)
        assert json_path.name.startswith("clean-core-zpkg-")
        assert json_path.suffix == ".json"
        assert md_path.name.startswith("clean-core-zpkg-")
        assert md_path.suffix == ".md"

    def test_write_reports_emits_m6(self, add_agent_to_path, tmp_path, caplog):
        import logging

        from output.report_writer import write_reports

        with caplog.at_level(logging.INFO):
            write_reports(_result(add_agent_to_path), "zpkg", reports_dir=tmp_path)
        assert any("M6.achieved" in r.message for r in caplog.records)
