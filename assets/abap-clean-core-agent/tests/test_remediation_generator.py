"""Unit tests for the remediation generator (principle / api / code depths)."""


def _hint(add_agent_to_path, level, hits=None):
    from classification.engine import ClassificationHint

    return ClassificationHint(candidate_level=level, rule_hits=hits or [])


class TestGenerateObject:
    def test_level_a_no_remediation(self, add_agent_to_path):
        from remediation.generator import generate_object

        g = generate_object("ZA", _hint(add_agent_to_path, "A"))
        assert g.needs_remediation is False

    def test_level_b_no_remediation(self, add_agent_to_path):
        from remediation.generator import generate_object

        g = generate_object("ZB", _hint(add_agent_to_path, "B"))
        assert g.needs_remediation is False

    def test_principle_depth_has_doc_link(self, add_agent_to_path):
        from remediation.generator import generate_object

        g = generate_object("ZC", _hint(add_agent_to_path, "C", ["mixed usage"]), depth="principle")
        assert g.needs_remediation is True
        assert g.doc_url
        assert g.doc_url in g.principle
        assert g.needs_llm is False

    def test_api_depth_flags_llm(self, add_agent_to_path):
        from remediation.generator import generate_object

        g = generate_object("ZD", _hint(add_agent_to_path, "D", ["D#1"]), depth="api")
        assert g.needs_llm is True
        assert g.current_construct

    def test_code_depth_has_verbatim_disclaimer(self, add_agent_to_path):
        from remediation.generator import CODE_DISCLAIMER, generate_object

        g = generate_object("ZD", _hint(add_agent_to_path, "D", ["D#2"]), depth="code")
        assert g.needs_llm is True
        assert g.disclaimer == CODE_DISCLAIMER

    def test_unknown_depth_defaults_to_principle(self, add_agent_to_path):
        from remediation.generator import generate_object

        g = generate_object("ZC", _hint(add_agent_to_path, "C"), depth="bogus")
        assert g.depth == "principle"

    def test_level_d_uses_forbidden_doc_link(self, add_agent_to_path):
        from remediation.generator import generate_object

        g = generate_object("ZD", _hint(add_agent_to_path, "D"))
        assert "forbidden-modifications" in g.doc_url


class TestGeneratePlan:
    def test_plan_keyed_by_name_and_m5(self, add_agent_to_path, caplog):
        import logging

        from remediation.generator import generate_plan

        hints = {
            "ZA": _hint(add_agent_to_path, "A"),
            "ZC": _hint(add_agent_to_path, "C", ["mixed"]),
            "ZD": _hint(add_agent_to_path, "D", ["D#1"]),
        }
        with caplog.at_level(logging.INFO):
            plan = generate_plan(hints, depth="principle")
        assert set(plan) == {"ZA", "ZC", "ZD"}
        assert plan["ZA"].needs_remediation is False
        assert plan["ZC"].needs_remediation is True
        assert plan["ZD"].needs_remediation is True
        assert any("M5.achieved" in r.message for r in caplog.records)
