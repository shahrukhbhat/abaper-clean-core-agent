"""Unit tests for the LangGraph agent wrapper (agent.py).

The LLM (``ChatLiteLLM``), the LangGraph ``create_agent`` graph, and the checkpointer are all
mocked — no network, no model calls. Verifies the 4-decorator contract, prompt assembly, and the
stream()/invoke() contract including the no-tools and error paths.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDecoratorContract:
    def test_exactly_four_decorated_functions(self, add_agent_to_path):
        # The asset constraint: agent.py exposes exactly 4 config/prompt decorators.
        from pathlib import Path

        import agent as agent_mod

        text = Path(agent_mod.__file__).read_text(encoding="utf-8")
        count = sum(
            text.count(f"\n@{d}") + (1 if text.startswith(f"@{d}") else 0)
            for d in ("agent_model", "agent_config", "prompt_section")
        )
        assert count == 4

    def test_system_prompt_mentions_clean_core(self, add_agent_to_path):
        from agent import get_system_prompt

        prompt = get_system_prompt()
        assert "Clean Core" in prompt
        assert "read-only" in prompt.lower()


@pytest.fixture
def mocked_agent(add_agent_to_path):
    """A SampleAgent whose LLM/checkpointer are mocked so no model is contacted."""
    with patch("agent.ChatLiteLLM") as mock_llm, \
         patch("agent.create_checkpointer") as mock_ckpt:
        mock_llm.return_value = MagicMock()
        mock_ckpt.return_value = MagicMock()
        from agent import SampleAgent

        yield SampleAgent()


class TestStream:
    async def test_stream_yields_processing_then_result(self, mocked_agent):
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(
            return_value={"messages": [MagicMock(content="Analysis complete.")]}
        )
        with patch("agent.create_agent", return_value=fake_graph):
            chunks = [c async for c in mocked_agent.stream("classify ZPKG", "ctx-1", tools=[])]

        assert chunks[0]["content"] == "Processing..."
        assert chunks[0]["is_task_complete"] is False
        assert chunks[-1]["is_task_complete"] is True
        assert chunks[-1]["content"] == "Analysis complete."

    async def test_stream_error_path(self, mocked_agent):
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("agent.create_agent", return_value=fake_graph):
            chunks = [c async for c in mocked_agent.stream("q", "ctx-2", tools=[])]

        assert chunks[-1]["is_task_complete"] is True
        assert "error" in chunks[-1]["content"].lower()

    async def test_no_tools_adds_guidance_to_prompt(self, mocked_agent):
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(
            return_value={"messages": [MagicMock(content="ok")]}
        )
        with patch("agent.create_agent", return_value=fake_graph) as mock_create:
            _ = [c async for c in mocked_agent.stream("q", "ctx-3", tools=None)]

        # create_agent called with a system_prompt containing the no-tools notice.
        _, kwargs = mock_create.call_args
        assert "No tools are currently available" in kwargs["system_prompt"]


class TestInvoke:
    async def test_invoke_returns_completed(self, mocked_agent):
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(
            return_value={"messages": [MagicMock(content="done")]}
        )
        with patch("agent.create_agent", return_value=fake_graph):
            resp = await mocked_agent.invoke("q", "ctx-4", tools=[])
        assert resp.status == "completed"
        assert resp.message == "done"
