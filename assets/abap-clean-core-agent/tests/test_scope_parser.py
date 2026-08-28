"""Unit tests for scope_parser — package, transport, object-list, and error paths."""

import pytest


class TestParseScope:
    def test_single_package(self, add_agent_to_path):
        from scope_parser import parse_scope

        scope = parse_scope("ZMYPACKAGE")
        assert scope.scope_type == "package"
        assert scope.identifiers == ["ZMYPACKAGE"]

    def test_comma_separated_packages(self, add_agent_to_path):
        from scope_parser import parse_scope

        scope = parse_scope("ZPKG_ONE, ZPKG_TWO ,zpkg_three")
        assert scope.scope_type == "package"
        # tokens are upper-cased and whitespace-trimmed
        assert scope.identifiers == ["ZPKG_ONE", "ZPKG_TWO", "ZPKG_THREE"]

    def test_transport_request(self, add_agent_to_path):
        from scope_parser import parse_scope

        scope = parse_scope("S4DK900123")
        assert scope.scope_type == "transport"
        assert scope.identifiers == ["S4DK900123"]

    def test_object_list_with_type_prefixes(self, add_agent_to_path):
        from scope_parser import parse_scope

        scope = parse_scope("CLAS:ZCL_FOO, PROG:ZMY_REPORT")
        assert scope.scope_type == "objects"
        assert scope.identifiers == ["ZCL_FOO", "ZMY_REPORT"]
        assert scope.object_types["ZCL_FOO"] == "CLAS"
        assert scope.object_types["ZMY_REPORT"] == "PROG"

    def test_edition_normalisation(self, add_agent_to_path):
        from scope_parser import parse_scope

        assert parse_scope("ZPKG", edition="public").edition == "public-cloud"
        assert parse_scope("ZPKG", edition="on_prem").edition == "on-premise"
        assert parse_scope("ZPKG", edition="Private Cloud").edition == "private-cloud"
        assert parse_scope("ZPKG").edition is None

    def test_empty_input_raises(self, add_agent_to_path):
        from scope_parser import ScopeParseError, parse_scope

        with pytest.raises(ScopeParseError):
            parse_scope("   ")

    def test_invalid_token_raises(self, add_agent_to_path):
        from scope_parser import ScopeParseError, parse_scope

        with pytest.raises(ScopeParseError):
            parse_scope("bad!!token, %%%")

    def test_invalid_edition_raises(self, add_agent_to_path):
        from scope_parser import ScopeParseError, parse_scope

        with pytest.raises(ScopeParseError):
            parse_scope("ZPKG", edition="mainframe")

    def test_scope_id_is_filesystem_safe(self, add_agent_to_path):
        from scope_parser import parse_scope

        scope = parse_scope("CLAS:ZCL_A/B, PROG:ZR")
        # no slashes or unsafe chars remain in the derived id
        assert "/" not in scope.scope_id
        assert scope.scope_id
