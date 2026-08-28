"""Unit tests for the extensibility verdict engine (KEY_USER / ON_STACK / SIDE_BY_SIDE)."""


def _obj(add_agent_to_path, source, name="ZCL_X", otype="CLAS"):
    from tools.retrieve_objects import ABAPObject

    return ABAPObject(name=name, type=otype, source=source)


def _hint(add_agent_to_path, level, review=False):
    from classification.engine import ClassificationHint

    return ClassificationHint(candidate_level=level, review_recommended=review)


class TestDecideObject:
    def test_level_a_is_on_stack(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        v = decide_object(_obj(add_agent_to_path, "* standard"), _hint(add_agent_to_path, "A"))
        assert v.path == "ON_STACK"

    def test_report_defaults_side_by_side(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        obj = _obj(add_agent_to_path, "WRITE: / 'hello'. CL_SALV.", name="ZR_REPORT", otype="PROG")
        v = decide_object(obj, _hint(add_agent_to_path, "C"))
        assert v.ricefw_category == "Report"
        assert v.path == "SIDE_BY_SIDE"

    def test_enhancement_with_released_badi_is_on_stack(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        obj = _obj(add_agent_to_path, "ENHANCEMENT z. GET BADI lo_badi. ENDENHANCEMENT.")
        v = decide_object(obj, _hint(add_agent_to_path, "C"))
        assert v.ricefw_category == "Enhancement"
        assert v.path == "ON_STACK"

    def test_enhancement_without_badi_is_side_by_side(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        obj = _obj(add_agent_to_path, "ENHANCEMENT z_no_badi. \" custom logic")
        v = decide_object(obj, _hint(add_agent_to_path, "D"))
        assert v.ricefw_category == "Enhancement"
        assert v.path == "SIDE_BY_SIDE"

    def test_form_is_side_by_side(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        obj = _obj(add_agent_to_path, "CALL FUNCTION 'SSF_OPEN'. SMARTFORM.", name="ZSF", otype="SSFO")
        v = decide_object(obj, _hint(add_agent_to_path, "C"))
        assert v.ricefw_category == "Form"
        assert v.path == "SIDE_BY_SIDE"

    def test_key_user_short_circuit(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        obj = _obj(add_agent_to_path, "APPEND STRUCTURE ci_foo. custom field extension.")
        v = decide_object(obj, _hint(add_agent_to_path, "C"))
        assert v.path == "KEY_USER"

    def test_released_only_level_b_override_to_on_stack(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        # A Report (default SIDE_BY_SIDE) at level B uses only released APIs → on-stack override.
        obj = _obj(add_agent_to_path, "WRITE: / 'x'.", name="ZR", otype="PROG")
        v = decide_object(obj, _hint(add_agent_to_path, "B"))
        assert v.path == "ON_STACK"

    def test_unknown_category_recommends_review(self, add_agent_to_path):
        from extensibility.verdict import decide_object

        obj = _obj(add_agent_to_path, "\" no strong signal", otype="XXXX")
        v = decide_object(obj, _hint(add_agent_to_path, "C"))
        assert v.ricefw_category == "Unknown"
        assert v.review_recommended


class TestDecideObjects:
    def test_batch_emits_m4(self, add_agent_to_path, caplog):
        import logging

        from extensibility.verdict import decide_objects

        objs = [
            _obj(add_agent_to_path, "WRITE: / 'x'.", name="ZR", otype="PROG"),
            _obj(add_agent_to_path, "* standard", name="ZA"),
        ]
        hints = {"ZR": _hint(add_agent_to_path, "C"), "ZA": _hint(add_agent_to_path, "A")}
        with caplog.at_level(logging.INFO):
            verdicts = decide_objects(objs, hints)
        assert set(verdicts) == {"ZR", "ZA"}
        assert any("M4.achieved" in r.message for r in caplog.records)

    def test_object_without_hint_skipped(self, add_agent_to_path):
        from extensibility.verdict import decide_objects

        objs = [_obj(add_agent_to_path, "* x", name="ZNO_HINT")]
        verdicts = decide_objects(objs, {})
        assert verdicts == {}
