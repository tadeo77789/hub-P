import pytest

from paula_hub.adapters.outbound.ollama.assistant import SYSTEM_PROMPT, TOOLS, OllamaAssistant
from paula_hub.domain.conversation import ToolResult
from paula_hub.ports.outbound.assistant import AssistantError


class FakeOllama:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, url, payload, timeout):
        self.requests.append((url, {**payload, "messages": list(payload["messages"])}))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def reply(content="", tool_calls=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"message": message, "done": True}


def call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


def make(*outcomes):
    fake = FakeOllama(*outcomes)
    return OllamaAssistant(post=fake), fake


def test_tools_cover_whitelist_and_memory():
    assert {t["function"]["name"] for t in TOOLS} == {
        "open_app",
        "system_status",
        "shutdown_pc",
        "remember",
        "forget",
        "list_memories",
    }


def test_recalled_facts_go_in_a_note_before_the_latest_message_only():
    assistant, fake = make(reply("Te pongo rock."), reply("Hola."))

    assistant.send("s", text="pon música", context=["A Ola le gusta el rock de los 80"])
    assistant.send("s", text="hola")

    first, second = (payload["messages"] for _, payload in fake.requests)
    assert first[0]["content"] == SYSTEM_PROMPT  # fixed, so the prompt cache holds
    assert first[1]["role"] == "system"
    assert "- A Ola le gusta el rock de los 80" in first[1]["content"]
    assert first[2] == {"role": "user", "content": "pon música"}
    assert all("rock de los 80" not in m["content"] for m in second)  # not kept


def test_text_reply_uses_qwen_without_thinking():
    assistant, fake = make(reply("Hola, Ola."))

    turn = assistant.send("s", text="hola")

    assert turn.text == "Hola, Ola."
    url, payload = fake.requests[0]
    assert url == "http://localhost:11434/api/chat"
    assert payload["model"] == "qwen3:4b-instruct"
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1] == {"role": "user", "content": "hola"}


def test_think_tags_are_stripped():
    assistant, _ = make(reply("<think>pensando…</think>\nListo."))

    assert assistant.send("s", text="hola").text == "Listo."


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Hola, Ola.", "Hola, Ola."),
        ("<think>a</think>Hola<think>b</think> Ola", "Hola Ola"),
        ("Hola <think>x</think>Ola", "Hola Ola"),
    ],
)
def test_think_blocks_never_eat_visible_text(content, expected):
    assistant, _ = make(reply(content))

    assert assistant.send("s", text="hola").text == expected


def test_reasoning_without_opening_tag_is_stripped():
    assistant, _ = make(reply("Okay, Ola says hello.\n</think>\n\n¡Hola!"))

    assert assistant.send("s", text="hola").text == "¡Hola!"


def test_tool_call_then_result_continue_history():
    assistant, fake = make(
        reply(tool_calls=[call("open_app", {"app": "spotify"})]),
        reply("Abrí Spotify."),
    )

    first = assistant.send("s", text="abre spotify")
    [tool_call] = first.tool_calls
    assert tool_call.name == "open_app"
    assert tool_call.args == {"app": "spotify"}

    second = assistant.send("s", results=[ToolResult(tool_call.id, "opened")])

    assert second.text == "Abrí Spotify."
    messages = fake.requests[1][1]["messages"]
    assert messages[2]["tool_calls"][0]["function"]["name"] == "open_app"
    assert messages[3] == {"role": "tool", "content": "opened", "tool_name": "open_app"}


def test_string_arguments_are_parsed():
    assistant, _ = make(reply(tool_calls=[call("open_app", '{"app": "chrome"}')]))

    [tool_call] = assistant.send("s", text="abre chrome").tool_calls

    assert tool_call.args == {"app": "chrome"}


def test_error_results_are_marked():
    assistant, fake = make(
        reply(tool_calls=[call("open_app", {"app": "x"})]),
        reply("No pude."),
    )
    [tool_call] = assistant.send("s", text="abre x").tool_calls

    assistant.send("s", results=[ToolResult(tool_call.id, "not found", is_error=True)])

    assert fake.requests[1][1]["messages"][3]["content"] == "Error: not found"


def test_connection_error_rewinds_to_last_clean_turn():
    assistant, fake = make(
        reply("Hola."),
        reply(tool_calls=[call("system_status", {})]),
        ConnectionRefusedError("ollama not running"),
        reply("Sigo aquí."),
    )
    assistant.send("s", text="hola")
    [tool_call] = assistant.send("s", text="estado").tool_calls

    with pytest.raises(AssistantError):
        assistant.send("s", results=[ToolResult(tool_call.id, "cpu 3%")])

    assistant.send("s", text="¿sigues?")
    messages = fake.requests[3][1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]


def test_malformed_response_is_an_assistant_error():
    assistant, _ = make({"error": "model not found"})

    with pytest.raises(AssistantError):
        assistant.send("s", text="hola")


def test_reset_clears_history():
    assistant, fake = make(reply("a"), reply("b"))
    assistant.send("s", text="uno")

    assistant.reset("s")
    assistant.send("s", text="dos")

    assert len(fake.requests[1][1]["messages"]) == 2


def test_empty_reply_gets_a_fallback_text():
    assistant, _ = make(reply("<think>hmm</think>"))

    assert assistant.send("s", text="hola").text.startswith("Perdona")


def test_reset_forgets_pending_tool_names():
    assistant, _ = make(reply(tool_calls=[call("system_status", {})]))
    assistant.send("s", text="estado")

    assistant.reset("s")

    assert assistant._tool_names == {}


def test_streaming_hands_over_text_and_hides_think():
    chunks = [
        {"message": {"content": "<think>x</think>Ho"}},
        {"message": {"content": "la."}},
        {"message": {"content": "", "tool_calls": [call("system_status", {})]}},
        {"done": True},
    ]
    sent = []

    def stream(url, payload, timeout):
        sent.append(payload)
        yield from chunks

    pieces = []
    assistant = OllamaAssistant(post=None, stream=stream)

    turn = assistant.send("s", text="hola", on_text=pieces.append)

    assert sent[0]["stream"] is True
    assert "".join(pieces) == "Hola."
    assert turn.text == "Hola."
    assert [c.name for c in turn.tool_calls] == ["system_status"]


def test_streaming_error_chunk_is_an_assistant_error():
    def stream(url, payload, timeout):
        yield {"error": "model not found"}

    assistant = OllamaAssistant(post=None, stream=stream)

    with pytest.raises(AssistantError):
        assistant.send("s", text="hola", on_text=lambda piece: None)


def test_connection_dropped_mid_stream_is_an_assistant_error():
    import http.client

    def stream(url, payload, timeout):
        yield {"message": {"content": "Hola"}}
        raise http.client.IncompleteRead(b"")

    assistant = OllamaAssistant(post=None, stream=stream)

    with pytest.raises(AssistantError):
        assistant.send("s", text="hola", on_text=lambda piece: None)
    assert assistant._histories["s"] == []
