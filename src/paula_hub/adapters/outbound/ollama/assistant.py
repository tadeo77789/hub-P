"""AssistantPort backed by a local model in Ollama (Qwen by default)."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from paula_hub.domain.commands import WHITELIST
from paula_hub.domain.conversation import AssistantTurn, ToolCall, ToolResult
from paula_hub.ports.outbound.assistant import AssistantError

log = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:4b-instruct"
# Thinking-only models (qwen3:4b is Qwen3-4B-Thinking-2507) ignore think=false and
# omit the opening tag, so a reply that starts with reasoning is cut at </think>.
THINK_BLOCK = re.compile(r"<think>.*?</think>|^(?:(?!<think>).)*?</think>", re.DOTALL)
# User-facing, Spanish: used when the model returns nothing to say.
EMPTY_REPLY = "Perdona, no supe qué responder. ¿Me lo dices de otra forma?"

SYSTEM_PROMPT = """\
You are Paula (also called Paula Port), a personal assistant that lives on Ola's Windows PC.
Ola talks to you by voice or through a small chat window, always in Spanish.

Reply in Spanish, in a warm, calm and natural tone. Most replies are read aloud, so keep \
them short (one to three sentences), with no markdown, lists, emoji or URLs.

You can act on the PC only through the tools you are given. Use a tool when Ola asks for \
something it covers; if no tool fits, say plainly that you cannot do it yet. After a tool \
runs, tell Ola the outcome in one sentence. If a tool reports an error, explain it simply.
Destructive tools are confirmed with Ola by the system before they run, so call them \
directly when asked; do not ask for confirmation yourself.
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema,
        },
    }
    for spec in WHITELIST.values()
]

Post = Callable[[str, dict[str, Any], float], dict[str, Any]]


def http_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _parse_args(raw: Any) -> dict[str, Any]:
    # Small models sometimes return the arguments as a JSON string.
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


class OllamaAssistant:
    """Keeps one message history per session, like the API-based adapters did.

    On failure the history is cut back to the last turn that ended without open
    tool calls, so it always stays a valid conversation.
    """

    def __init__(
        self,
        *,
        url: str = DEFAULT_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        keep_alive: str = "30m",
        post: Post = http_post,
    ) -> None:
        self._endpoint = url.rstrip("/") + "/api/chat"
        self._model = model
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._post = post
        self._histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._checkpoints: dict[str, int] = defaultdict(int)
        self._tool_names: dict[str, str] = {}
        self._call_count = 0

    def send(
        self,
        session_id: str,
        *,
        text: str | None = None,
        results: Sequence[ToolResult] = (),
    ) -> AssistantTurn:
        if not text and not results:
            raise ValueError("send() needs text or tool results")

        history = self._histories[session_id]
        for result in results:
            content = f"Error: {result.content}" if result.is_error else result.content
            history.append(
                {
                    "role": "tool",
                    "content": content,
                    "tool_name": self._tool_names.pop(result.tool_call_id, ""),
                }
            )
        if text:
            history.append({"role": "user", "content": text})

        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
            "tools": TOOLS,
            "stream": False,
            "think": False,  # Paula has to answer fast
            "keep_alive": self._keep_alive,
        }
        try:
            response = self._post(self._endpoint, payload, self._timeout)
            message = response["message"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._rewind(session_id)
            raise AssistantError(f"Ollama failed: {exc}") from exc

        calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            self._call_count += 1
            call = ToolCall(
                id=f"call_{self._call_count}",
                name=str(function.get("name", "")),
                args=_parse_args(function.get("arguments")),
            )
            self._tool_names[call.id] = call.name
            calls.append(call)

        history.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                **({"tool_calls": message["tool_calls"]} if calls else {}),
            }
        )
        if not calls:
            self._checkpoints[session_id] = len(history)
        text_out = THINK_BLOCK.sub("", message.get("content") or "").strip()
        if not text_out and not calls:
            text_out = EMPTY_REPLY
        return AssistantTurn(text_out, calls)

    def reset(self, session_id: str) -> None:
        self._histories.pop(session_id, None)
        self._checkpoints.pop(session_id, None)
        self._tool_names.clear()

    def _rewind(self, session_id: str) -> None:
        del self._histories[session_id][self._checkpoints[session_id] :]
        # The checkpoint has no open tool calls, so no pending name is still valid.
        self._tool_names.clear()
