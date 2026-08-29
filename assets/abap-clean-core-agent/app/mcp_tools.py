"""MCP tool loader.

Owned indirection layer between agent code and the MCP server.
All agent code imports get_mcp_tools from here.

Two transports are supported; the active one is selected by the
``MCP_TRANSPORT`` environment variable:

  Destination service token-exchange (DEFAULT — ``MCP_TRANSPORT`` unset or
  anything other than ``agw``):
      Forwards the end-user JWT to the bound BTP Destination service, which
      swaps it for an MCP-scoped token (OAuth2UserTokenExchange) AND returns
      the MCP server URL from the Destination configuration. The agent then
      calls the MCP server over Streamable HTTP directly, injecting that
      Bearer token via ``mcp_auth.get_auth_headers()``. No ``MCP_SERVER_URL``
      env var is needed — the URL is read from the Destination. This is the
      canonical CF + AI Core deployment path today.

  SAP Agent Gateway (``MCP_TRANSPORT=agw``):
      Uses the Agent Gateway client from the SDK to connect via mTLS. Kept
      intact but dormant until AGW is available in our landscape — flip the
      flag with no code change. Its retry/timeout live in ``util.py`` and are
      NOT shared with the Destination path.

Behaviour is additionally controlled by the IBD_TESTING environment variable:

  Local / test mode (IBD_TESTING=1):
      Reads mcp-mock.json from the directory containing this file's parent
      (i.e. <asset-root>/mcp-mock.json) and returns LangChain StructuredTool
      instances built from the mock data — no network calls. Applies to BOTH
      transports.
"""

import asyncio
import json
import logging
import os
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any, Optional

from pydantic import create_model
from langchain_core.tools import StructuredTool, ToolException

import mcp_auth
from util import enhance_tool_description, enhance_tool_name, call_mcp_tool_with_retry

logger = logging.getLogger(__name__)

# Transport selector. Unset (or any value other than "agw") => Destination path.
_MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "").strip().lower()


def _use_agw_transport() -> bool:
    """True when the dormant Agent Gateway transport is explicitly selected."""
    return _MCP_TRANSPORT == "agw"


# Context variable to pass user token from request to tool execution
# This allows cached tools to access per-request user credentials
_user_token_context: ContextVar[str | None] = ContextVar('user_token', default=None)

# Reusable AGW client for connection pooling (AGW transport only)
_agw_client: Optional[Any] = None

# mcp-mock.json lives at the asset root (one level above app/)
_MOCK_FILE = Path(__file__).parent.parent / "mcp-mock.json"

# --- Destination-transport (direct Streamable-HTTP MCP) tunables ------------
# MCP server URL is read from the Destination configuration at runtime via
# mcp_auth.get_mcp_server_url() — no MCP_SERVER_URL env var required.
# Own retry policy for the Destination/direct-HTTP path — deliberately separate
# from util.py's AGW retry (per transport-decoupling decision).
_DEST_RETRY_ATTEMPTS = int(os.environ.get("MCP_DEST_RETRY_ATTEMPTS", 4))
_DEST_RETRY_DELAY_SECONDS = float(os.environ.get("MCP_DEST_RETRY_DELAY_SECONDS", 4.0))
_DEST_CALL_TIMEOUT_SECONDS = float(os.environ.get("MCP_DEST_CALL_TIMEOUT_SECONDS", 30.0))
# Truncate oversized MCP responses to prevent OOM (mirrors util.py's cap).
_DEST_MAX_RESPONSE_CHARS = int(os.environ.get("MCP_MAX_RESPONSE_CHARS", 100_000))


def _build_mock_tools() -> list:
    """Build LangChain StructuredTool instances from mcp-mock.json.

    Returns an empty list (without error) when mcp-mock.json is absent or
    cannot be parsed — add/fix the file to enable tool mocking.
    """
    if not _MOCK_FILE.exists():
        return []

    try:
        mock_data = json.loads(_MOCK_FILE.read_text())
    except Exception:
        logger.warning(
            "Failed to parse mcp-mock.json at %s — returning empty tool list",
            _MOCK_FILE,
            exc_info=True,
        )
        return []

    tools = []

    from langchain_core.tools import StructuredTool
    from pydantic import Field, create_model

    for _server_slug, server in mock_data.get("servers", {}).items():
        for tool_name, tool_def in server.get("tools", {}).items():
            description = tool_def.get("description", "")
            mock_response = tool_def.get("mock_response", {})
            input_schema = tool_def.get("input_schema", {})

            props = input_schema.get("properties", {})
            required_fields = set(input_schema.get("required", []))
            field_definitions: dict = {}
            for field_name, field_info in props.items():
                json_type = field_info.get("type", "string")
                if json_type == "integer":
                    python_type = int
                elif json_type == "number":
                    python_type = float
                elif json_type == "boolean":
                    python_type = bool
                else:
                    python_type = str

                if field_name in required_fields:
                    field_definitions[field_name] = (
                        python_type,
                        Field(description=field_info.get("description", "")),
                    )
                else:
                    field_definitions[field_name] = (
                        python_type,
                        Field(
                            default=None, description=field_info.get("description", "")
                        ),
                    )

            args_schema = (
                create_model(f"{tool_name}_args", **field_definitions)
                if field_definitions
                else create_model(f"{tool_name}_args")
            )
            _response = json.dumps(mock_response)

            async def _coroutine(_resp=_response, **kwargs) -> str:
                return _resp

            tools.append(
                StructuredTool(
                    name=tool_name,
                    description=description,
                    args_schema=args_schema,
                    coroutine=_coroutine,
                    # Catch ToolException and forward it to the LLM as an error
                    # message rather than propagating as a Python exception.
                    handle_tool_error=True,
                )
            )

    logger.info("Loaded %d mock MCP tool(s) from %s", len(tools), _MOCK_FILE)
    return tools


def _convert_mcp_tool_to_langchain(mcp_tool: Any, agw_client: Any) -> StructuredTool:
    """
    Convert an MCP tool to a LangChain StructuredTool.

    Args:
        mcp_tool: The MCP tool to convert (MCPTool object from SDK)
        agw_client: Agent Gateway client for tool execution

    Returns:
        LangChain StructuredTool

    Raises:
        ValueError: If mcp_tool is None

    Note:
        Uses the SDK's namespaced_name property (format: 'server_name__tool_name')
        to prevent naming conflicts when multiple MCP servers provide tools
        with the same name.

        User authentication: The user token is retrieved from the context variable
        _user_token_context at call time, allowing these cached tools to use
        per-request credentials without being recreated for each user.
    """
    if mcp_tool is None:
        raise ValueError("mcp_tool parameter cannot be None")

    async def run(**kwargs) -> str:
        """Execute the MCP tool via Agent Gateway client with retry logic.

        Retrieves the user token from the context variable set by agent_executor.
        """
        user_token = _user_token_context.get()
        return await call_mcp_tool_with_retry(agw_client, mcp_tool, user_token=user_token, **kwargs)

    # Build args schema from input_schema
    properties = mcp_tool.input_schema.get("properties", {})
    required = set(mcp_tool.input_schema.get("required", []))

    fields = {}
    for name, prop in properties.items():
        # Map JSON schema types to Python types
        prop_type = prop.get("type", "string")
        python_type = str  # Default to string
        if prop_type == "integer":
            python_type = int
        elif prop_type == "number":
            python_type = float
        elif prop_type == "boolean":
            python_type = bool

        # Required fields use ... (Ellipsis), optional use None default
        if name in required:
            fields[name] = (python_type, ...)
        else:
            fields[name] = (python_type | None, None)

    args_schema = create_model(f"{mcp_tool.name}_args", **fields) if fields else None

    # Enhance description and name with server context
    enhanced_description = enhance_tool_description(mcp_tool)
    namespaced_tool_name = enhance_tool_name(mcp_tool)

    return StructuredTool.from_function(
        coroutine=run,
        name=namespaced_tool_name,
        description=enhanced_description,
        args_schema=args_schema,
        # Catch ToolException raised inside `run` (e.g. after all retries are
        # exhausted) and forward it to the LLM as a ToolMessage error string.
        # This prevents the LLM from hallucinating results when the real MCP
        # call fails.
        handle_tool_error=True,
    )


async def get_mcp_tools(user_token: str | None) -> list:
    """Return LangChain-compatible MCP tools for the current user.

    Transport is selected by ``MCP_TRANSPORT``:
      * unset / not "agw"  -> Destination service token-exchange (ACTIVE default)
      * "agw"              -> SAP Agent Gateway (dormant, mTLS)

    In local/test mode (IBD_TESTING=1): returns mock tools from mcp-mock.json
    for either transport, without validating ``user_token``.

    IMPORTANT: Both tool listing and tool calling require the user's identity.
    The ``user_token`` parameter is passed explicitly so it cannot be forgotten.

    Args:
        user_token: The end-user JWT (required in production). In local testing
            mode (IBD_TESTING=1) this can be None or empty.

    Returns:
        List of LangChain StructuredTool objects for the current user.

    Raises:
        ValueError: If ``user_token`` is None or empty in production mode.
    """
    # In local/test mode, return mock tools without validating user_token
    if os.environ.get("IBD_TESTING") == "1":
        return _build_mock_tools()

    # Validate user identity is present in production mode (both transports).
    if not user_token:
        raise ValueError("user_token is required for listing and calling MCP tools")

    if _use_agw_transport():
        return await _get_mcp_tools_agw(user_token)
    return await _get_mcp_tools_destination(user_token)


async def _get_mcp_tools_agw(user_token: str) -> list:
    """AGW transport (dormant): list tools via the Agent Gateway SDK over mTLS."""
    global _agw_client

    try:
        from sap_cloud_sdk.agentgateway import create_client
        # Reuse AGW client for connection pooling (mTLS is expensive to establish)
        if _agw_client is None:
            _agw_client = create_client()
            logger.info("Agent Gateway client created successfully")

        agw_client = _agw_client

        # Get MCP tools from Agent Gateway with user token
        logger.info("Listing MCP tools with user credentials")
        mcp_tools = await agw_client.list_mcp_tools(user_token=user_token)

        if not mcp_tools:
            logger.warning("Agent Gateway returned 0 tools - MCP servers may not be available")
            return []

        logger.info(f"Successfully retrieved {len(mcp_tools)} tool(s) from Agent Gateway")

        # Convert to LangChain tools (they retrieve user token at call time from context)
        langchain_tools = []
        for mcp_tool in mcp_tools:
            try:
                langchain_tool = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
                langchain_tools.append(langchain_tool)
            except Exception as e:
                logger.warning(f"Failed to convert tool '{mcp_tool.name}': {e}")
                # Continue with other tools

        # Return empty list when no tools were successfully converted
        if not langchain_tools:
            logger.warning("No tools were successfully converted - returning empty list")
            return []

        return langchain_tools

    except Exception as e:
        logger.exception("Failed to load MCP tools from Agent Gateway")
        # Reset client on failure to force reconnection on next attempt
        _agw_client = None
        return []


# --- Destination transport (ACTIVE default) --------------------------------

def _mcp_request_headers(user_token: str) -> dict[str, str]:
    """Build headers for a direct Streamable-HTTP MCP request.

    Injects the exchanged MCP-scoped Bearer token from the Destination service
    and the Streamable-HTTP content negotiation headers required by the MCP
    transport spec.
    """
    headers = mcp_auth.get_auth_headers(user_token)
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json, text/event-stream"
    return headers


async def _get_mcp_tools_destination(user_token: str) -> list:
    """Destination transport: list MCP tools over Streamable HTTP.

    Uses the MCP Python SDK's ``streamablehttp_client`` with a Bearer token
    obtained from the BTP Destination service (OAuth2UserTokenExchange). The
    MCP server URL is also read from the Destination configuration — no
    separate MCP_SERVER_URL env var is required. Tools are converted to
    LangChain ``StructuredTool`` instances whose execution opens a fresh
    session per call, re-reading the user token from context so cached tools
    use per-request credentials.
    """
    try:
        mcp_server_url = mcp_auth.get_mcp_server_url(user_token)
    except Exception:
        logger.error(
            "Could not resolve MCP server URL from Destination '%s' — "
            "ensure the Destination exists in BTP and the agent-destination "
            "service binding is present",
            mcp_auth._DESTINATION_NAME,
        )
        return []

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        headers = _mcp_request_headers(user_token)

        async with streamablehttp_client(mcp_server_url, headers=headers) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()

        mcp_tools = getattr(listed, "tools", None) or []
        if not mcp_tools:
            logger.warning(
                "MCP server returned 0 tools over Destination transport — the "
                "user may lack scope, or no servers are bound"
            )
            return []

        logger.info(
            "Successfully retrieved %d tool(s) from MCP server (Destination transport)",
            len(mcp_tools),
        )

        langchain_tools = []
        for mcp_tool in mcp_tools:
            try:
                langchain_tools.append(_convert_destination_tool_to_langchain(mcp_tool))
            except Exception as e:
                logger.warning("Failed to convert tool '%s': %s", getattr(mcp_tool, "name", "?"), e)

        if not langchain_tools:
            logger.warning("No tools were successfully converted - returning empty list")
        return langchain_tools

    except mcp_auth.MissingUserTokenError:
        logger.exception("MCP token exchange attempted without a user JWT")
        return []
    except Exception:
        logger.exception("Failed to load MCP tools over Destination transport")
        return []


def _convert_destination_tool_to_langchain(mcp_tool: Any) -> StructuredTool:
    """Convert an MCP SDK tool (Destination transport) to a LangChain tool.

    The returned tool opens its own Streamable-HTTP session per invocation and
    reads the user token from the context var set by the request handler, so
    per-user credentials flow through without recreating the tool.
    """
    name = mcp_tool.name
    description = getattr(mcp_tool, "description", "") or ""
    input_schema = getattr(mcp_tool, "inputSchema", None) or {}

    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))
    fields: dict = {}
    for field_name, prop in properties.items():
        prop_type = prop.get("type", "string")
        if prop_type == "integer":
            python_type = int
        elif prop_type == "number":
            python_type = float
        elif prop_type == "boolean":
            python_type = bool
        else:
            python_type = str
        if field_name in required:
            fields[field_name] = (python_type, ...)
        else:
            fields[field_name] = (python_type | None, None)

    args_schema = create_model(f"{name}_args", **fields) if fields else None

    async def run(**kwargs) -> str:
        user_token = _user_token_context.get()
        return await _call_destination_tool_with_retry(name, user_token, **kwargs)

    return StructuredTool.from_function(
        coroutine=run,
        name=name,
        description=description,
        args_schema=args_schema,
        # Forward ToolException (e.g. after retries exhausted, or a scope error)
        # to the LLM as a ToolMessage rather than crashing the graph.
        handle_tool_error=True,
    )


async def _call_destination_tool_once(tool_name: str, user_token: str, **kwargs: Any) -> str:
    """Invoke a single MCP tool over Streamable HTTP and return its text result.

    Raises:
        InsufficientScopeError: on HTTP 403 (user lacks the required scope).
    """
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    mcp_server_url = mcp_auth.get_mcp_server_url(user_token)
    headers = _mcp_request_headers(user_token)

    try:
        async with streamablehttp_client(mcp_server_url, headers=headers) as (
            read_stream,
            write_stream,
            _get_session_id,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=kwargs or {})
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 403:
            # Scope insufficient — do NOT retry with elevated credentials.
            raise mcp_auth.InsufficientScopeError(
                f"User lacks the scope required to call MCP tool '{tool_name}'"
            ) from exc
        raise

    # Flatten MCP content blocks into a single text string.
    parts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(block))
    text_result = "\n".join(parts) if parts else ""

    if len(text_result) > _DEST_MAX_RESPONSE_CHARS:
        logger.warning(
            "Response from %s truncated from %d to %d chars to prevent OOM",
            tool_name, len(text_result), _DEST_MAX_RESPONSE_CHARS,
        )
        text_result = text_result[:_DEST_MAX_RESPONSE_CHARS] + "\n...[truncated]"
    return text_result


async def _call_destination_tool_with_retry(tool_name: str, user_token: str | None, **kwargs: Any) -> str:
    """Retry wrapper for the Destination/direct-HTTP transport.

    This is intentionally SEPARATE from ``util.call_mcp_tool_with_retry`` (which
    serves the AGW path only). A 403 → ``InsufficientScopeError`` is NEVER
    retried; transient errors are retried with a fixed backoff.
    """
    if not user_token:
        raise ToolException(
            f"Tool '{tool_name}' cannot run: no user identity in request context"
        )

    last_exc: Exception | None = None
    for attempt in range(1 + _DEST_RETRY_ATTEMPTS):
        try:
            logger.info(
                "Calling MCP tool '%s' via Destination transport with %d argument(s)",
                tool_name, len(kwargs) if kwargs else 0,
            )
            return await asyncio.wait_for(
                _call_destination_tool_once(tool_name, user_token, **kwargs),
                timeout=_DEST_CALL_TIMEOUT_SECONDS,
            )
        except mcp_auth.InsufficientScopeError:
            # Surface scope failures immediately — retrying cannot help and the
            # agent must not attempt privilege escalation.
            raise
        except Exception as e:
            last_exc = e
            if attempt < _DEST_RETRY_ATTEMPTS:
                logger.warning(
                    "Error calling %s (attempt %d/%d), retrying in %.1fs: %s",
                    tool_name, attempt + 1, 1 + _DEST_RETRY_ATTEMPTS,
                    _DEST_RETRY_DELAY_SECONDS, e,
                )
                await asyncio.sleep(_DEST_RETRY_DELAY_SECONDS)

    logger.exception(
        "Failed to call %s after %d attempts", tool_name, 1 + _DEST_RETRY_ATTEMPTS,
        exc_info=last_exc,
    )
    raise ToolException(
        f"Tool '{tool_name}' failed after {1 + _DEST_RETRY_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


def set_user_token(user_token: str | None) -> Token:
    """Set the user token for MCP tool calls in the current async context.

    This must be called before invoking any tools to ensure they use the correct
    user credentials. The token is stored in a context variable that is automatically
    isolated per async task/request.

    IMPORTANT: Always reset the token after use to prevent cross-request contamination:
        token_ctx = set_user_token(user_token)
        try:
            # ... use tools ...
        finally:
            reset_user_token(token_ctx)

    Args:
        user_token: The user's authentication token, or None to clear it

    Returns:
        Token object that must be passed to reset_user_token() to restore
        the previous value
    """
    if user_token:
        logger.debug("User token set for tool execution")
    else:
        logger.debug("User token cleared for tool execution")
    return _user_token_context.set(user_token)


def reset_user_token(token: Token) -> None:
    """Restore the user token context to its previous value.

    Args:
        token: The Token returned by a prior set_user_token() call. Passing it to
            ContextVar.reset() unwinds the context stack to the value that was in
            effect before that set_user_token() call, rather than leaving a stale
            or None value behind.
    """
    _user_token_context.reset(token)
    logger.debug("User token context reset to previous value")


def get_user_token() -> str | None:
    """Get the current user token from the async context.

    Returns:
        The user token string, or None if not set
    """
    return _user_token_context.get()
