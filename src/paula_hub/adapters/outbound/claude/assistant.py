"""AssistantPort backed by the Claude API, with whitelisted commands as tools."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import anthropic

from paula_hub.domain.commands import WHITELIST
from paula_hub.domain.conversation import AssistantTurn, ToolCall, ToolResult
from paula_hub.ports.outbound.assistant import AssistantError

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
REFUSAL_TEXT = "Prefiero no ayudar con eso."

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
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "strict": True,
    }
    for spec in WHITELIST.values()
]


class ClaudeAssistant:
    """Keeps one append-only message history per session.

    On failure or refusal the history is cut back to the last turn that ended
    without open tool calls, so it always stays a valid conversation.
    """

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = "low",
        max_tokens: int = 16000,
    ) -> None:
        # Stay well under the RabbitMQ heartbeat: the consumer blocks during the call.
        self._client = client or anthropic.Anthropic(timeout=60.0, max_retries=1)
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._checkpoints: dict[str, int] = defaultdict(int)

    def send(
        self,
        session_id: str,
        *,
        text: str | None = None,
        results: Sequence[ToolResult] = (),
    ) -> AssistantTurn:
        content: list[dict[str, Any]] = [
            {
                "type": "tool_result",
                "tool_use_id": r.tool_call_id,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in results
        ]
        if text:
            content.append({"type": "text", "text": text})
        if not content:
            raise ValueError("send() needs text or tool results")

        history = self._histories[session_id]
        history.append({"role": "user", "content": content})
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=history,
                output_config={"effort": self._effort},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIError as exc:
            self._rewind(session_id)
            raise AssistantError(str(exc)) from exc

        if response.stop_reason == "refusal":
            log.warning("Claude refused: %s", response.stop_details)
            self._rewind(session_id)
            return AssistantTurn(REFUSAL_TEXT)

        history.append({"role": "assistant", "content": response.content})
        text_out = "".join(b.text for b in response.content if b.type == "text").strip()
        calls = [
            ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"
        ]
        if not calls:
            self._checkpoints[session_id] = len(history)
        return AssistantTurn(text_out, calls)

    def reset(self, session_id: str) -> None:
        self._histories.pop(session_id, None)
        self._checkpoints.pop(session_id, None)

    def _rewind(self, session_id: str) -> None:
        del self._histories[session_id][self._checkpoints[session_id] :]
