"""Unit tests for the rule-based classification engine (Levels A–D)."""


def _obj(add_agent_to_path, source, name="ZCL_TEST", otype="CLAS", status="success"):
    from tools.retrieve_objects import ABAPObject

    return ABAPObject(name=name, type=otype, source=source, retrieval_status=status)


class TestClassifyObject:
    def test_level_b_released_view_only(self, add_agent_to_path):
        from classification.engine import classify_object

        obj = _obj(add_agent_to_path, "SELECT * FROM I_SalesOrder INTO TABLE @DATA(lt).")
        hint = classify_object(obj)
        assert hint.candidate_level == "B"
        assert not hint.review_recommended

    def test_level_d_forbidden_select_internal_table(self, add_agent_to_path):
        from classification.engine import classify_object

        obj = _obj(add_agent_to_path, "SELECT * FROM VBAK INTO TABLE @DATA(lt).")
        hint = classify_object(obj)
        assert hint.candidate_level == "D"
        assert any("D#1" in h for h in hint.rule_hits)

    def test_level_d_non_released_function_module(self, add_agent_to_path):
        from classification.engine import classify_object

        obj = _obj(add_agent_to_path, "CALL FUNCTION 'BAPI_SOMETHING'.")
        hint = classify_object(obj)
        assert hint.candidate_level == "D"
        assert any("D#2" in h for h in hint.rule_hits)

    def test_level_d_destination_rfc(self, add_agent_to_path):
        from classification.engine import classify_object

        obj = _obj(add_agent_to_path, "CALL FUNCTION 'Z_REMOTE' DESTINATION 'RFCDEST'.")
        hint = classify_object(obj)
        assert hint.candidate_level == "D"
        assert any("D#6" in h for h in hint.rule_hits)

    def test_source_unavailable_is_level_d_review(self, add_agent_to_path):
        from classification.engine import classify_object

        obj = _obj(add_agent_to_path, None, status="failed")
        hint = classify_object(obj)
        assert hint.candidate_level == "D"
        assert hint.review_recommended
        assert hint.confidence == 0.0

    def test_ambiguous_on_premise_is_c(self, add_agent_to_path):
        from classification.engine import classify_object

        # SELECT on an SAP-namespace table not on the internal blocklist → ambiguous.
        obj = _obj(add_agent_to_path, "SELECT * FROM TADIR INTO TABLE @DATA(lt).")
        hint = classify_object(obj, edition="on-premise")
        assert hint.candidate_level == "C"
        assert hint.review_recommended

    def test_ambiguous_public_cloud_escalates_to_d(self, add_agent_to_path):
        from classification.engine import classify_object

        obj = _obj(add_agent_to_path, "SELECT * FROM TADIR INTO TABLE @DATA(lt).")
        hint = classify_object(obj, edition="public-cloud")
        assert hint.candidate_level == "D"
        assert hint.review_recommended

    def test_mixed_usage_released_plus_ambiguous(self, add_agent_to_path):
        from classification.engine import classify_object

        src = (
            "SELECT * FROM I_SalesOrder INTO TABLE @DATA(a).\n"
            "SELECT * FROM TADIR INTO TABLE @DATA(b)."
        )
        hint = classify_object(_obj(add_agent_to_path, src), edition="on-premise")
        assert hint.candidate_level == "C"
        assert any("mixed" in h.lower() for h in hint.rule_hits)


class TestClassifyObjects:
    def test_batch_keyed_by_name_and_m3(self, add_agent_to_path, caplog):
        import logging

        from classification.engine import classify_objects

        objs = [
            _obj(add_agent_to_path, "SELECT * FROM I_Product INTO TABLE @DATA(x).", name="ZCL_OK"),
            _obj(add_agent_to_path, "SELECT * FROM VBAK INTO TABLE @DATA(y).", name="ZCL_BAD"),
        ]
        with caplog.at_level(logging.INFO):
            hints = classify_objects(objs)
        assert set(hints) == {"ZCL_OK", "ZCL_BAD"}
        assert hints["ZCL_OK"].candidate_level == "B"
        assert hints["ZCL_BAD"].candidate_level == "D"
        assert any("M3.achieved" in r.message for r in caplog.records)

    def test_low_confidence_forces_review(self, add_agent_to_path):
        from classification.engine import classify_objects

        # ambiguous-only source yields confidence 0.6 (< 0.7 threshold).
        objs = [_obj(add_agent_to_path, "SELECT * FROM TADIR INTO TABLE @DATA(z).", name="ZCL_AMB")]
        hints = classify_objects(objs, edition="on-premise")
        assert hints["ZCL_AMB"].review_recommended
