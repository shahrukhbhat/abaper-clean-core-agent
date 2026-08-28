"""Unit tests for AnalysisResult aggregates and the three audience views."""


def _result(add_agent_to_path):
    from output.result import AnalysisResult, ObjectResult

    objs = [
        ObjectResult(name="ZD1", type="CLAS", level="D", extensibility="SIDE_BY_SIDE",
                     ricefw_category="Report", remediation="fix it"),
        ObjectResult(name="ZC1", type="PROG", level="C", extensibility="ON_STACK",
                     ricefw_category="Enhancement", review_recommended=True),
        ObjectResult(name="ZB1", type="CLAS", level="B", extensibility="ON_STACK"),
        ObjectResult(name="ZA1", type="CLAS", level="A", extensibility="KEY_USER"),
    ]
    return AnalysisResult(
        scope_id="zpkg", scope_identifier="ZPKG", edition="on-premise", objects=objs
    )


class TestAnalysisResult:
    def test_level_counts(self, add_agent_to_path):
        r = _result(add_agent_to_path)
        assert r.level_counts() == {"A": 1, "B": 1, "C": 1, "D": 1}

    def test_extensibility_counts(self, add_agent_to_path):
        r = _result(add_agent_to_path)
        assert r.extensibility_counts() == {"KEY_USER": 1, "ON_STACK": 2, "SIDE_BY_SIDE": 1}

    def test_sorted_by_risk_d_first(self, add_agent_to_path):
        r = _result(add_agent_to_path)
        order = [o.level for o in r.objects_sorted_by_risk()]
        assert order == ["D", "C", "B", "A"]

    def test_overall_risk_high_when_d_over_20pct(self, add_agent_to_path):
        r = _result(add_agent_to_path)
        # 1 of 4 = 25% D → HIGH
        assert r.overall_risk() == "HIGH"

    def test_overall_risk_low_when_empty(self, add_agent_to_path):
        from output.result import AnalysisResult

        r = AnalysisResult(scope_id="x", scope_identifier="X", edition="on-premise")
        assert r.overall_risk() == "LOW"


class TestViews:
    def test_developer_view_lists_all_objects(self, add_agent_to_path):
        from output.views import render_developer_view

        r = _result(add_agent_to_path)
        md = render_developer_view(r)
        for name in ("ZD1", "ZC1", "ZB1", "ZA1"):
            assert name in md
        assert "Developer View" in md

    def test_architect_view_groups_by_path(self, add_agent_to_path):
        from output.views import render_architect_view

        md = render_architect_view(_result(add_agent_to_path))
        assert "ON_STACK" in md
        assert "SIDE_BY_SIDE" in md
        assert "KEY_USER" in md
        assert "Extensibility map" in md

    def test_governance_view_has_percentages(self, add_agent_to_path):
        from output.views import render_governance_view

        md = render_governance_view(_result(add_agent_to_path))
        assert "Governance Scorecard" in md
        assert "%" in md
        assert "Overall risk" in md

    def test_select_view_from_keywords(self, add_agent_to_path):
        from output.views import select_view

        assert select_view("show me the governance scorecard") == "governance"
        assert select_view("architect map please") == "architect"
        assert select_view("no keyword here") == "developer"

    def test_render_view_dispatch(self, add_agent_to_path):
        from output.views import render_view

        r = _result(add_agent_to_path)
        assert "Governance Scorecard" in render_view("governance", r)
        # unknown view name falls back to developer
        assert "Developer View" in render_view("nonsense", r)
