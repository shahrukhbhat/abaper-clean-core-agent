import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langchain_litellm import ChatLiteLLM
from opentelemetry import trace
from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section
from sap_cloud_sdk.agent_memory.factory.langgraph_checkpoint import create_checkpointer

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@agent_model(
    key="config.model",
    label="LLM Model",
    description="The language model powering this agent",
)
def get_model_name() -> str:
    return "sap/anthropic--claude-4.5-sonnet"


@agent_config(
    key="config.temperature",
    label="LLM Temperature",
    description="Controls randomness of responses (0.0 = deterministic, 1.0 = creative)",
)
def get_temperature() -> float:
    return 0.0

@agent_config(
    key="config.checkpointer.ttl_seconds",
    label="Thread TTL (seconds)",
    description="Evict inactive conversation threads after this period of "
                "inactivity. Set to 0 to disable eviction.",
)
def thread_ttl_seconds() -> int:
    return 3600 # 1 hour

@prompt_section(
    key="prompts.system",
    label="System Prompt",
    description="The full system prompt defining the agent's role and behavior",
    validation={"format": "markdown", "max_length": 5000},
)
def get_system_prompt() -> str:
    return """You are the ABAP Clean Core Compliance Agent, a compliance analyst for S/4HANA migration teams. You classify custom ABAP objects against SAP Clean Core Levels A–D, deliver extensibility verdicts (Key User / Developer on-stack / Side-by-Side on BTP), and generate remediation guidance at a selectable depth.

## Read-only, no fabrication
- You retrieve ABAP source and metadata ONLY through the MCP tools (`read`, `readcontent`). These are strictly READ-ONLY. You can NEVER write to, modify, or create objects in the ABAP system.
- If a user asks you to change, fix in place, or deploy ABAP code, refuse: "I can only read ABAP code — I cannot write to the ABAP system."
- Never fabricate, guess, or invent ABAP objects, source code, or classification data. If a tool returns an error, relay it verbatim and continue with whatever data you do have.

## Session start — ask before analysing
If not already provided or set globally, ask the user at the start of a session for:
1. Target S/4HANA edition — on-premise, Cloud Private, or Cloud Public. Classification strictness varies by edition (Public Cloud enforces Released-only APIs). If the user skips, default to on-premise and state that assumption.
2. Preferred remediation depth — `principle` (rule + doc link), `api` (replacement API), or `code` (refactored snippet). Default is `principle`.

## Cite every verdict
Never give an unexplained classification. Every Clean Core level and extensibility verdict must cite the specific SAP Clean Core rule, released-API status, or white-paper principle behind it.

## Use the runtime skills
Load the relevant runtime skill on demand via the `load` tool:
- `clean-core-classification` when classifying objects into Levels A–D.
- `extensibility-guidance` when producing Key User / On-Stack / Side-by-Side verdicts.
- `remediation-templates` when generating remediation guidance.

## Batch safety
Set page/batch size to a MAXIMUM of 100 objects per MCP call to prevent context overflow. If a scope exceeds 100 objects, process in batches and tell the user the limit was applied.

## Code-snippet disclaimer
Whenever you output an ABAP code snippet, prefix it verbatim with: "⚠️ This snippet is a starting point for developer validation and is NOT production-ready. Review and test thoroughly before applying."

## Scope handling
Accept scope as a package name, comma-separated packages, a transport request (`<SID>K<6-digit>`), or a list of object names (optionally type-prefixed, e.g. `CLAS:ZCL_FOO`). Objects that cannot be retrieved are reported as failed, never silently dropped."""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


class SampleAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        ttl = thread_ttl_seconds()
        self.llm = ChatLiteLLM(model=get_model_name(), temperature=get_temperature())
        self._checkpointer = create_checkpointer(ttl_seconds=ttl or None)
        self._summarization_middleware = SummarizationMiddleware(
            model=self.llm,
            trigger=("tokens", 100_000),
            keep=("messages", 4),
        )

    async def _run_agent(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None,
    ) -> str:
        """Run the LangGraph agent to completion and return the final message content.

        All business logic lives here (never inside the ``stream()`` generator) so it can be
        wrapped in an OpenTelemetry span — spans must not enclose a ``yield``. The pipeline
        milestones M1–M6 are emitted by the ``analyze_scope`` tool and the engines it calls.
        """
        with tracer.start_as_current_span("agent.run"):
            system_prompt = get_system_prompt()
            if not tools:
                system_prompt += "\n\nIMPORTANT: No tools are currently available. Do not attempt to call any tools. Respond to the user explaining that tools are temporarily unavailable."

            tool_names = [tool.name for tool in tools] if tools else []
            logger.info("Running agent with %d tool(s): %s", len(tool_names), tool_names)

            graph = create_agent(
                self.llm,
                tools=list(tools) if tools else [],
                system_prompt=system_prompt,
                checkpointer=self._checkpointer,
                middleware=[self._summarization_middleware],
            )
            config = {"configurable": {"thread_id": context_id}}
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=query)]}, config
            )
            return result["messages"][-1].content

    async def stream(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream agent responses.

        Args:
            query: User query to process
            context_id: Context identifier for the conversation
            tools: Optional sequence of LangChain tools. If None or empty, agent runs without tools.

        Yields:
            Status updates and final response with structure:
            - is_task_complete: Whether the task is complete
            - require_user_input: Whether user input is needed
            - content: The response content or status message
        """
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing...",
        }

        try:
            response = await self._run_agent(query, context_id, tools)
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }
        except Exception:
            logger.exception("Agent stream() failed")
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": "I encountered an error while processing your request. Please try again.",
            }

    async def invoke(
        self,
        query: str,
        context_id: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> AgentResponse:
        """Invoke agent and return final response.

        Args:
            query: User query to process
            context_id: Context identifier for the conversation
            tools: Optional sequence of LangChain tools. If None or empty, agent runs without tools.

        Returns:
            AgentResponse with status and message
        """
        last: dict = {}
        async for chunk in self.stream(query, context_id, tools=tools):
            last = chunk
        if last.get("is_task_complete"):
            return AgentResponse(status="completed", message=last["content"])
        if last.get("require_user_input"):
            return AgentResponse(status="input_required", message=last["content"])
        return AgentResponse(
            status="error", message=last.get("content", "Unknown error")
        )
