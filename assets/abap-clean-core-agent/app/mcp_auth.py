"""User-identity token exchange for MCP access (decoupled model).

This module implements the ACTIVE MCP authentication path: it forwards the
end-user's JWT to the bound BTP **Destination service**, which is configured
with ``Authentication: OAuth2UserTokenExchange`` for the ``ai-abaper-mcp``
destination. The Destination service swaps the user JWT for an MCP-scoped
token carrying only the scopes that user has been granted (``read`` /
``readcontent``) via role collections on the MCP side.

Design constraints (see specification & guidelines-agent.md → MCP Authentication):
  * NO XSUAA client-credentials, NO scope requests, NO runtime-qualified
    xsappname. The agent is a dumb identity pipe — it never mints its own token.
  * The user JWT is read from the request-scoped context var set by
    ``JWTContextMiddleware`` (via ``mcp_tools.get_user_token``).
  * Exchanged tokens are cached PER USER (keyed by the ``sub`` claim) with TTL
    from ``expires_in``; evicted proactively when < 60 s remain.
  * Missing user JWT is rejected upstream with HTTP 401 — never fall back to a
    service identity here.
  * MCP HTTP 403 (scope insufficient) → raise ``InsufficientScopeError``; the
    agent must NOT retry with elevated credentials.
  * Never log the user JWT or the exchanged token value.
"""

import base64
import binascii
import json
import logging
import threading
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Destination service REST path for a single destination lookup with token exchange.
_DESTINATION_NAME = "ai-abaper-mcp"
_DESTINATION_LOOKUP_PATH = f"/destination-configuration/v1/destinations/{_DESTINATION_NAME}"

# Proactively evict a cached token when fewer than this many seconds remain.
_TOKEN_EVICT_MARGIN_SECONDS = 60
# Fallback TTL if the exchanged token carries no usable expiry.
_DEFAULT_TOKEN_TTL_SECONDS = 3600
# Per-attempt timeout for the Destination lookup HTTP call.
_DESTINATION_HTTP_TIMEOUT_SECONDS = 30.0


class InsufficientScopeError(Exception):
    """Raised when the MCP returns HTTP 403 for a tool the user lacks scope for.

    The agent graph catches this, surfaces a user-facing message naming the
    missing scope, and continues with whatever data the user's scopes allow.
    It MUST NOT trigger a retry with elevated credentials.
    """

    def __init__(self, message: str, *, scope: Optional[str] = None):
        super().__init__(message)
        self.scope = scope


class MissingUserTokenError(Exception):
    """Raised when a token exchange is attempted without an inbound user JWT.

    Inbound requests without a user JWT are rejected with HTTP 401 upstream
    (see ``JWTContextMiddleware`` in ``main.py``); this is a defensive guard.
    """


class _CachedToken:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: str, expires_at: float):
        self.value = value
        self.expires_at = expires_at

    def is_fresh(self, now: float) -> bool:
        return (self.expires_at - now) > _TOKEN_EVICT_MARGIN_SECONDS


# Per-user cache of exchanged tokens, keyed by the `sub` claim of the user JWT.
_token_cache: dict[str, _CachedToken] = {}
_cache_lock = threading.Lock()


def _decode_jwt_claims(jwt: str) -> dict[str, Any]:
    """Decode a JWT payload WITHOUT verifying the signature.

    Signature verification is the responsibility of the platform / XSUAA at the
    edge; here we only need the ``sub`` claim to key the cache. Returns an empty
    dict if the token is malformed.
    """
    try:
        payload_b64 = jwt.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded)
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return {}


def _cache_key(user_jwt: str) -> str:
    """Derive the per-user cache key from the JWT ``sub`` claim.

    Falls back to a hash-free constant marker only when ``sub`` is absent, which
    should not happen for a valid user token; such tokens simply are not cached
    across users (each exchange is independent).
    """
    claims = _decode_jwt_claims(user_jwt)
    sub = claims.get("sub")
    if sub:
        return str(sub)
    return "__no_sub__"


def _load_destination_credentials() -> dict[str, Any]:
    """Read the bound ``destination`` service credentials from VCAP_SERVICES.

    Uses cfenv to locate the destination service binding. Returns the
    credentials dict containing ``uri`` (the destination service base URL) and
    the client credentials used to obtain the destination-service access token.

    Raises:
        RuntimeError: if the destination service binding is not present.
    """
    from cfenv import AppEnv

    env = AppEnv()
    service = env.get_service(label="destination") or env.get_service(name="destination")
    if service is None:
        raise RuntimeError(
            "destination service binding not found in VCAP_SERVICES — the agent "
            "cannot exchange the user token for an MCP-scoped token"
        )
    return service.credentials


def _get_destination_service_token(creds: dict[str, Any]) -> str:
    """Obtain an access token for the Destination service itself.

    This authenticates the AGENT to the Destination service (so it may call the
    destination-configuration API). It is NOT the MCP token and carries no MCP
    scopes — the MCP-scoped token is produced by the OAuth2UserTokenExchange
    flow inside the destination lookup, keyed on the forwarded user JWT.
    """
    token_url = creds["url"].rstrip("/") + "/oauth/token"
    client_id = creds["clientid"]
    client_secret = creds["clientsecret"]

    resp = httpx.post(
        token_url,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        timeout=_DESTINATION_HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _exchange_user_token(user_jwt: str) -> _CachedToken:
    """Perform the Destination-service token exchange for the given user JWT.

    Returns a freshly exchanged, cache-ready token. Raises on transport errors
    so the caller can decide how to surface them.
    """
    creds = _load_destination_credentials()
    dest_base = creds["uri"].rstrip("/")
    dest_service_token = _get_destination_service_token(creds)

    resp = httpx.get(
        dest_base + _DESTINATION_LOOKUP_PATH,
        headers={
            "Authorization": f"Bearer {dest_service_token}",
            # OAuth2UserTokenExchange: the Destination service swaps this user
            # JWT for an MCP-scoped token reflecting the user's role collections.
            "X-user-token": user_jwt,
            "Accept": "application/json",
        },
        timeout=_DESTINATION_HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    body = resp.json()

    auth_tokens = body.get("authTokens") or []
    if not auth_tokens or not auth_tokens[0].get("value"):
        raise RuntimeError(
            "Destination lookup returned no authTokens — the user token exchange "
            "did not yield an MCP-scoped token"
        )

    token_value = auth_tokens[0]["value"]
    expires_in = auth_tokens[0].get("expires_in")
    try:
        ttl = int(expires_in) if expires_in is not None else _DEFAULT_TOKEN_TTL_SECONDS
    except (TypeError, ValueError):
        ttl = _DEFAULT_TOKEN_TTL_SECONDS

    return _CachedToken(value=token_value, expires_at=time.time() + ttl)


def get_auth_headers(user_jwt: Optional[str]) -> dict[str, str]:
    """Return the Authorization header dict for an MCP request.

    Exchanges (or reuses a cached) MCP-scoped token for the given user JWT via
    the Destination service, then returns ``{"Authorization": "Bearer <token>"}``.

    Args:
        user_jwt: The end-user's JWT forwarded from the inbound A2A request.

    Returns:
        A dict suitable for merging into MCP HTTP request headers.

    Raises:
        MissingUserTokenError: if ``user_jwt`` is falsy (no user identity).
    """
    if not user_jwt:
        raise MissingUserTokenError(
            "No user JWT present — cannot exchange for an MCP-scoped token"
        )

    key = _cache_key(user_jwt)
    now = time.time()

    with _cache_lock:
        cached = _token_cache.get(key)
        if cached is not None and cached.is_fresh(now):
            return {"Authorization": f"Bearer {cached.value}"}

    # Exchange outside the lock (network call); tolerate a benign race where two
    # requests for the same user exchange concurrently — last write wins.
    fresh = _exchange_user_token(user_jwt)

    with _cache_lock:
        _token_cache[key] = fresh

    logger.debug("MCP-scoped token acquired via Destination exchange (user cached)")
    return {"Authorization": f"Bearer {fresh.value}"}


def clear_cache() -> None:
    """Evict all cached exchanged tokens (used by tests)."""
    with _cache_lock:
        _token_cache.clear()
