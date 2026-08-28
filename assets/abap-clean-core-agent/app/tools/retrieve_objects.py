"""MCP object-retrieval wrapper.

Resolves the ``read`` and ``readcontent`` MCP tools *by capability* (never by a
hard-coded, namespaced tool name — real MCP tool names are prefixed with a server
identifier at runtime) and turns their results into :class:`ABAPObject` records.

Objects that cannot be retrieved are returned with ``retrieval_status="failed"``
(or ``"not_found"``) — they are never silently dropped.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from langchain_core.tools import BaseTool

from scope_parser import Scope

logger = logging.getLogger(__name__)

# Max objects fetched per read call — mirrors the 100-object batch cap in the system prompt.
MAX_BATCH_SIZE = 100

RetrievalStatus = str  # "success" | "failed" | "not_found"


@dataclass
class ABAPObject:
    name: str
    type: str
    source: str | None = None
    package: str | None = None
    transport: str | None = None
    retrieval_status: RetrievalStatus = "success"
    responsible: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _find_tool(tools: Sequence[BaseTool], capability: str) -> BaseTool | None:
    """Resolve a tool by capability suffix (e.g. 'read', 'readcontent').

    Matches the bare tool name or a namespaced ``server__read`` form, without
    hard-coding the server prefix. 'readcontent' is checked before 'read' by the
    caller to avoid a 'read' prefix matching 'readcontent'.
    """
    for tool in tools:
        name = tool.name.lower()
        bare = name.rsplit("__", 1)[-1]
        if bare == capability:
            return tool
    return None


def _parse_tool_payload(raw: Any) -> Any:
    """MCP/mock tools return JSON strings; decode to dict/list where possible."""
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    return raw


async def _invoke(tool: BaseTool, args: dict[str, Any]) -> Any:
    result = await tool.ainvoke(args)
    return _parse_tool_payload(result)


async def retrieve_objects(
    scope: Scope,
    tools: Sequence[BaseTool],
    *,
    fetch_source: bool = True,
) -> list[ABAPObject]:
    """List objects in ``scope`` via ``read`` and (optionally) fetch source via ``readcontent``.

    Emits an ``M2.achieved``/``M2.missed`` log line on completion.
    """
    scope_id = scope.scope_id
    read_tool = _find_tool(tools, "read")
    content_tool = _find_tool(tools, "readcontent")

    if read_tool is None:
        logger.warning(
            "M2.missed: code retrieval incomplete — 'read' tool unavailable; proceeding with 0 objects for scope '%s'",
            scope_id,
        )
        return []

    scope_arg = ",".join(scope.identifiers)
    objects: list[ABAPObject] = []
    try:
        payload = await _invoke(read_tool, {"scope": scope_arg})
    except Exception as exc:  # noqa: BLE001 — tool/transport errors must not abort the pipeline
        logger.warning(
            "M2.missed: code retrieval incomplete — 'read' failed for scope '%s': %s",
            scope_id, exc,
        )
        return []

    raw_objects = payload.get("objects", []) if isinstance(payload, dict) else []
    if len(raw_objects) > MAX_BATCH_SIZE:
        logger.info(
            "Scope '%s' returned %d objects; capping at %d per batch limit",
            scope_id, len(raw_objects), MAX_BATCH_SIZE,
        )
        raw_objects = raw_objects[:MAX_BATCH_SIZE]

    for entry in raw_objects:
        obj = _to_abap_object(entry, scope)
        objects.append(obj)

    if fetch_source and content_tool is not None:
        for obj in objects:
            await _fetch_source(obj, content_tool)
    elif fetch_source and content_tool is None:
        logger.warning("'readcontent' tool unavailable — objects retrieved without source")

    retrieved = sum(1 for o in objects if o.retrieval_status == "success")
    total = len(objects)
    failed = total - retrieved
    if total and failed == 0:
        logger.info(
            "M2.achieved: code retrieval complete — %d/%d objects retrieved for scope '%s'",
            retrieved, total, scope_id,
        )
    else:
        logger.warning(
            "M2.missed: code retrieval incomplete — %d objects could not be retrieved; proceeding with %d for scope '%s'",
            failed, retrieved, scope_id,
        )
    return objects


def _to_abap_object(entry: Any, scope: Scope) -> ABAPObject:
    if not isinstance(entry, dict):
        return ABAPObject(name=str(entry), type="UNKNOWN", retrieval_status="failed",
                          error="malformed object entry from 'read'")
    status = str(entry.get("retrieval_status", "success")).lower()
    if status in ("ok", "success"):
        status = "success"
    return ABAPObject(
        name=entry.get("name", ""),
        type=entry.get("type", "UNKNOWN"),
        package=entry.get("package"),
        transport=entry.get("transport") or (scope.identifiers[0] if scope.scope_type == "transport" else None),
        responsible=entry.get("responsible"),
        retrieval_status=status,
        metadata={k: v for k, v in entry.items()
                  if k not in ("name", "type", "package", "transport", "responsible", "retrieval_status")},
    )


async def _fetch_source(obj: ABAPObject, content_tool: BaseTool) -> None:
    if obj.retrieval_status != "success" or not obj.name:
        return
    try:
        payload = await _invoke(content_tool, {"name": obj.name, "type": obj.type})
    except Exception as exc:  # noqa: BLE001
        obj.retrieval_status = "failed"
        obj.error = f"readcontent failed: {exc}"
        return
    if isinstance(payload, dict):
        status = str(payload.get("retrieval_status", "success")).lower()
        if status in ("not_found", "notfound"):
            obj.retrieval_status = "not_found"
            return
        source = payload.get("source")
        if source is None:
            obj.retrieval_status = "failed"
            obj.error = "readcontent returned no source"
            return
        obj.source = source
    else:
        obj.retrieval_status = "failed"
        obj.error = "readcontent returned a non-object payload"
