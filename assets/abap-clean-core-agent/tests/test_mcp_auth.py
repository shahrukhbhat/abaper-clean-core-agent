"""Unit tests for mcp_auth — user-token exchange, per-user cache, eviction, error paths.

All HTTP is mocked; no real Destination service is contacted.
"""

import base64
import json
import time

import pytest


def _make_jwt(sub: str) -> str:
    """Build an unsigned JWT whose payload carries the given ``sub`` claim."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.fixture
def clean_auth(add_agent_to_path):
    import mcp_auth

    mcp_auth.clear_cache()
    yield mcp_auth
    mcp_auth.clear_cache()


class TestGetAuthHeaders:
    def test_missing_user_token_raises(self, clean_auth):
        with pytest.raises(clean_auth.MissingUserTokenError):
            clean_auth.get_auth_headers(None)

    def test_exchange_and_cache_per_user(self, clean_auth, monkeypatch):
        calls = {"n": 0}

        def fake_exchange(user_jwt):
            calls["n"] += 1
            return clean_auth._CachedToken(value=f"tok-{calls['n']}", expires_at=time.time() + 3600)

        monkeypatch.setattr(clean_auth, "_exchange_user_token", fake_exchange)

        jwt = _make_jwt("user-A")
        h1 = clean_auth.get_auth_headers(jwt)
        h2 = clean_auth.get_auth_headers(jwt)  # served from cache — no second exchange
        assert h1 == h2
        assert calls["n"] == 1
        assert h1["Authorization"].startswith("Bearer tok-1")

    def test_distinct_users_get_distinct_tokens(self, clean_auth, monkeypatch):
        counter = {"n": 0}

        def fake_exchange(user_jwt):
            counter["n"] += 1
            return clean_auth._CachedToken(value=f"tok-{counter['n']}", expires_at=time.time() + 3600)

        monkeypatch.setattr(clean_auth, "_exchange_user_token", fake_exchange)

        a = clean_auth.get_auth_headers(_make_jwt("user-A"))
        b = clean_auth.get_auth_headers(_make_jwt("user-B"))
        assert a["Authorization"] != b["Authorization"]
        assert counter["n"] == 2

    def test_token_near_expiry_is_evicted_and_re_exchanged(self, clean_auth, monkeypatch):
        counter = {"n": 0}

        def fake_exchange(user_jwt):
            counter["n"] += 1
            # First token expires in 30s (< 60s margin) → considered stale immediately.
            ttl = 30 if counter["n"] == 1 else 3600
            return clean_auth._CachedToken(value=f"tok-{counter['n']}", expires_at=time.time() + ttl)

        monkeypatch.setattr(clean_auth, "_exchange_user_token", fake_exchange)

        jwt = _make_jwt("user-C")
        first = clean_auth.get_auth_headers(jwt)
        second = clean_auth.get_auth_headers(jwt)  # stale → re-exchange
        assert first["Authorization"] != second["Authorization"]
        assert counter["n"] == 2

    def test_does_not_log_token_values(self, clean_auth, monkeypatch, caplog):
        import logging

        secret_jwt = _make_jwt("user-D")

        def fake_exchange(user_jwt):
            return clean_auth._CachedToken(value="SUPER-SECRET-TOKEN", expires_at=time.time() + 3600)

        monkeypatch.setattr(clean_auth, "_exchange_user_token", fake_exchange)

        with caplog.at_level(logging.DEBUG):
            clean_auth.get_auth_headers(secret_jwt)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "SUPER-SECRET-TOKEN" not in joined
        assert secret_jwt not in joined


class TestCacheKey:
    def test_cache_key_uses_sub_claim(self, clean_auth):
        assert clean_auth._cache_key(_make_jwt("abc-123")) == "abc-123"

    def test_malformed_jwt_falls_back(self, clean_auth):
        assert clean_auth._cache_key("not-a-jwt") == "__no_sub__"


class TestInsufficientScope:
    def test_insufficient_scope_error_carries_scope(self, clean_auth):
        err = clean_auth.InsufficientScopeError("nope", scope="readcontent")
        assert err.scope == "readcontent"
