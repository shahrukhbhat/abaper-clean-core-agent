"""End-to-end integration test for the analysis pipeline.

Drives ``run_pipeline`` with fake ``read`` / ``readcontent`` MCP tools (no real MCP, no LLM),
and asserts that all six milestones (M1–M6) fire and both reports are written.
"""

import json
import logging


def _fake_tools(add_agent_to_path, objects_payload, source_map):
    """Build fake LangChain ``read`` and ``readcontent`` StructuredTools."""
    from langchain_core.tools import StructuredTool

    async def _read(scope: str) -> str:
        return json.dumps({"objects": objects_payload})

    async def _readcontent(name: str, type: str = "") -> str:
        src = source_map.get(name)
        if src is None:
            return json.dumps({"retrieval_status": "not_found"})
        return json.dumps({"source": src, "retrieval_status": "success"})

    read_tool = StructuredTool.from_function(coroutine=_read, name="server__read",
                                             description="list objects in scope")
    content_tool = StructuredTool.from_function(coroutine=_readcontent, name="server__readcontent",
                                                description="read object source")
    return [read_tool, content_tool]


class TestPipelineEndToEnd:
    async def test_full_pipeline_all_milestones(self, add_agent_to_path, tmp_path, caplog):
        from pipeline_tools import run_pipeline

        objects_payload = [
            {"name": "ZCL_ORDER_ENRICH", "type": "CLAS", "package": "ZPKG"},
            {"name": "ZCL_CLEAN_RPT", "type": "CLAS", "package": "ZPKG"},
        ]
        source_map = {
            # forbidden direct SELECT on VBAK → Level D
            "ZCL_ORDER_ENRICH": "SELECT * FROM VBAK INTO TABLE @DATA(lt).",
            # released view only → Level B
            "ZCL_CLEAN_RPT": "SELECT * FROM I_SalesOrder INTO TABLE @DATA(lt). WRITE: / 'ok'.",
        }
        tools = _fake_tools(add_agent_to_path, objects_payload, source_map)

        # Redirect report output into tmp_path. The pipeline calls write_reports without a
        # reports_dir arg, so wrap it to inject tmp_path (patching the module global is not
        # enough — the default is bound at def-time).
        import pipeline_tools

        orig_write = pipeline_tools.write_reports

        def _write_to_tmp(res, scope_id, **kwargs):
            return orig_write(res, scope_id, reports_dir=tmp_path)

        pipeline_tools.write_reports = _write_to_tmp
        try:
            with caplog.at_level(logging.INFO):
                result, rendered = await run_pipeline(
                    "ZPKG", tools, edition="on-premise", depth="principle", view="developer",
                )
        finally:
            pipeline_tools.write_reports = orig_write

        # Result assertions
        assert result.total == 2
        levels = {o.name: o.level for o in result.objects}
        assert levels["ZCL_ORDER_ENRICH"] == "D"
        assert levels["ZCL_CLEAN_RPT"] == "B"
        assert "Developer View" in rendered

        # All six milestones fired
        messages = " ".join(r.message for r in caplog.records)
        for m in ("M1.achieved", "M2.achieved", "M3.achieved",
                  "M4.achieved", "M5.achieved", "M6.achieved"):
            assert m in messages, f"missing milestone {m}"

        # Both reports written to tmp
        assert list(tmp_path.glob("clean-core-*.json"))
        assert list(tmp_path.glob("clean-core-*.md"))

    async def test_scope_error_surfaces(self, add_agent_to_path):
        from pipeline_tools import get_pipeline_tools

        tools = get_pipeline_tools([])
        analyze = tools[0]
        out = await analyze.coroutine(scope="!!!invalid!!!")
        assert "Scope error" in out
