from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from paula_hub.adapters.outbound.claude.assistant import (
    REFUSAL_TEXT,
    TOOLS,
    ClaudeAssistant,
)
from paula_hub.domain.conversation import ToolResult
from paula_hub.ports.outbound.assistant import AssistantError


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(id_, name, input_):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, stop_details=None)


class FakeMessages:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def create(self, **kwargs):
        # Copy messages: the adapter keeps appending to the same list.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(*outcomes):
    messages = FakeMessages(*outcomes)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeAssistant(client), messages


def api_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=request)


def test_tools_are_strict_and_cover_whitelist():
    names = {tool["name"] for tool in TOOLS}

    assert names == {"open_app", "system_status", "shutdown_pc"}
    assert all(tool["strict"] for tool in TOOLS)


def test_text_reply():
    assistant, messages = make(response(text_block("Hola, Ola.")))

    turn = assistant.send("s", text="hola")

    assert turn.text == "Hola, Ola."
    assert turn.tool_calls == []
    request = messages.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    assert request["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hola"}]}]


def test_tool_use_then_results_continue_history():
    assistant, messages = make(
        response(tool_block("t1", "open_app", {"app": "spotify"}), stop_reason="tool_use"),
        response(text_block("Abrí Spotify.")),
    )

    first = assistant.send("s", text="abre spotify")
    assert [c.name for c in first.tool_calls] == ["open_app"]
    assert first.tool_calls[0].args == {"app": "spotify"}

    second = assistant.send("s", results=[ToolResult("t1", "opened")])

    assert second.text == "Abrí Spotify."
    sent = messages.requests[1]["messages"]
    assert len(sent) == 3
    assert sent[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": "opened",
        "is_error": False,
    }


def test_results_come_before_new_text():
    assistant, messages = make(
        response(tool_block("t1", "shutdown_pc", {}), stop_reason="tool_use"),
        response(text_block("Vale.")),
    )
    assistant.send("s", text="apaga")

    assistant.send("s", text="mejor no", results=[ToolResult("t1", "cancelled", True)])

    content = messages.requests[1]["messages"][2]["content"]
    assert [block["type"] for block in content] == ["tool_result", "text"]


def test_api_error_rewinds_to_last_clean_turn():
    assistant, messages = make(
        response(text_block("Hola.")),
        response(tool_block("t1", "system_status", {}), stop_reason="tool_use"),
        api_error(),
        response(text_block("Sigo aquí.")),
    )
    assistant.send("s", text="hola")
    assistant.send("s", text="estado del pc")

    with pytest.raises(AssistantError):
        assistant.send("s", results=[ToolResult("t1", "cpu 3%")])

    assistant.send("s", text="¿sigues?")
    sent = messages.requests[3]["messages"]
    assert len(sent) == 3
    assert sent[2]["content"] == [{"type": "text", "text": "¿sigues?"}]


def test_refusal_returns_fixed_text_and_drops_turn():
    assistant, messages = make(
        response(stop_reason="refusal"),
        response(text_block("Hola.")),
    )

    turn = assistant.send("s", text="algo raro")
    assert turn.text == REFUSAL_TEXT

    assistant.send("s", text="hola")
    assert len(messages.requests[1]["messages"]) == 1


def test_reset_clears_history():
    assistant, messages = make(response(text_block("a")), response(text_block("b")))
    assistant.send("s", text="uno")

    assistant.reset("s")
    assistant.send("s", text="dos")

    assert len(messages.requests[1]["messages"]) == 1


def test_send_requires_content():
    assistant, _ = make()

    with pytest.raises(ValueError):
        assistant.send("s")
