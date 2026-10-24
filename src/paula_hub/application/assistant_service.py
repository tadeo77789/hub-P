"""Core use case: turn orders into replies and actions, and events into follow-ups."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from paula_hub.domain.commands import get_command
from paula_hub.domain.conversation import AssistantTurn, ToolCall, ToolResult
from paula_hub.domain.messages import (
    Action,
    Alert,
    Channel,
    Event,
    Intent,
    Order,
    Result,
    RobotState,
    Source,
    Status,
)
from paula_hub.ports.outbound.agent_gateway import AgentGatewayPort
from paula_hub.ports.outbound.assistant import AssistantError, AssistantPort
from paula_hub.ports.outbound.notifier import NotifierPort

log = logging.getLogger(__name__)

# User-facing text is Spanish: Paula talks to the user in Spanish.
CONFIRM_YES = "Sí, confirmo"
CONFIRM_NO = "No"
MAX_TOOL_ROUNDS = 5

_CHANNELS = {
    Source.VOICE: Channel.PC,
    Source.HOTKEY: Channel.PC,
    Source.CHAT: Channel.CHAT,
    Source.ALEXA: Channel.ALEXA,
}


@dataclass
class _Turn:
    """Tool calls of one assistant turn that still need a result."""

    order: Order
    calls: list[ToolCall]
    round: int
    results: dict[str, ToolResult] = field(default_factory=dict)

    def missing(self) -> list[ToolCall]:
        return [c for c in self.calls if c.id not in self.results]


@dataclass(frozen=True)
class _InFlight:
    order_id: str
    call_id: str
    command: str


class AssistantService:
    def __init__(
        self,
        assistant: AssistantPort,
        gateway: AgentGatewayPort,
        notifier: NotifierPort,
        *,
        session_id: str = "default",
        long_task_seconds: float = 30.0,
        idle_reset_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._assistant = assistant
        self._gateway = gateway
        self._notifier = notifier
        self._session_id = session_id
        self._long_task_seconds = long_task_seconds
        self._idle_reset_seconds = idle_reset_seconds
        self._clock = clock
        self._last_activity = clock()
        self._turns: dict[str, _Turn] = {}
        self._in_flight: dict[str, _InFlight] = {}
        self._confirmations: dict[str, ToolCall] = {}

    # Inbound

    def handle_order(self, order: Order) -> None:
        self._reset_if_idle()
        if order.intent is Intent.CONFIRM:
            self._handle_confirm(order)
        elif order.intent is Intent.WAKE_PC:
            self._reply(order, "Encender el PC a distancia todavía no está disponible.")
        elif not order.text:
            self._reply(order, "No te escuché bien. ¿Me lo repites?")
        else:
            self._ask(order, round_=0, text=order.text, results=self._cancel_outstanding())

    def handle_event(self, event: Event) -> None:
        flight = self._in_flight.pop(event.action_id, None)
        turn = self._turns.get(flight.order_id) if flight else None
        if flight is None or turn is None:
            log.info("Ignoring event for unknown or cancelled action %s", event.action_id)
            return
        turn.results[flight.call_id] = ToolResult(
            flight.call_id, event.output, is_error=event.status is Status.ERROR
        )
        # Answer the user first; the alert is best effort and must not block the reply.
        self._continue_if_done(turn)
        if event.duration_seconds >= self._long_task_seconds:
            self._notify(Alert(title="Tarea terminada", message=event.output[:200]))

    # Steps

    def _ask(
        self,
        order: Order,
        *,
        round_: int,
        text: str | None = None,
        results: Sequence[ToolResult] = (),
    ) -> None:
        try:
            turn = self._assistant.send(self._session_id, text=text, results=results)
        except AssistantError:
            log.exception("Assistant failed for order %s", order.id)
            self._reply_error(order, "No pude pensar una respuesta. Inténtalo de nuevo.")
            return
        self._process(order, turn, round_)

    def _process(self, order: Order, turn: AssistantTurn, round_: int) -> None:
        if not turn.tool_calls:
            self._reply(order, turn.text)
            return

        state = _Turn(order=order, calls=list(turn.tool_calls), round=round_)
        self._turns[order.id] = state
        if round_ >= MAX_TOOL_ROUNDS:
            # Left unanswered on purpose: the next order closes these calls.
            self._reply(
                order, turn.text or "Me enredé con esa tarea. ¿Lo intentamos de otra forma?"
            )
            return

        for call in state.calls:
            spec = get_command(call.name)
            if spec is None:
                state.results[call.id] = ToolResult(
                    call.id, f"Unknown command '{call.name}'.", is_error=True
                )
            elif spec.destructive:
                if order.id in self._confirmations:
                    state.results[call.id] = ToolResult(
                        call.id, "Only one destructive action can wait for confirmation.", True
                    )
                else:
                    self._confirmations[order.id] = call
            else:
                self._dispatch(order, call, confirmed=False)

        call = self._confirmations.get(order.id)
        if call is not None:
            self._send(
                order,
                Status.QUESTION,
                turn.text or f"Esta acción ({call.name}) no se puede deshacer. ¿Confirmas?",
                RobotState.QUESTION,
                options=[CONFIRM_YES, CONFIRM_NO],
            )
        self._continue_if_done(state)

    def _handle_confirm(self, order: Order) -> None:
        reply_to = str(order.payload.get("reply_to", ""))
        call = self._confirmations.pop(reply_to, None)
        turn = self._turns.get(reply_to)
        if call is None or turn is None:
            self._reply(order, "No tengo nada pendiente por confirmar.")
            return
        if order.text.casefold() == CONFIRM_YES.casefold():
            self._dispatch(turn.order, call, confirmed=True)
        else:
            turn.results[call.id] = ToolResult(call.id, "The user declined. Nothing was done.")
            self._continue_if_done(turn)

    def _dispatch(self, order: Order, call: ToolCall, *, confirmed: bool) -> None:
        action = Action(order_id=order.id, command=call.name, args=call.args, confirmed=confirmed)
        self._in_flight[action.id] = _InFlight(order.id, call.id, call.name)
        self._gateway.dispatch(action)

    def _continue_if_done(self, turn: _Turn) -> None:
        if turn.missing() or turn.round >= MAX_TOOL_ROUNDS:
            return
        del self._turns[turn.order.id]
        results = [turn.results[c.id] for c in turn.calls]
        self._ask(turn.order, round_=turn.round + 1, results=results)

    def _cancel_outstanding(self) -> list[ToolResult]:
        """Close every open tool call so the next user message is valid."""
        results: list[ToolResult] = []
        for turn in self._turns.values():
            for call in turn.calls:
                results.append(
                    turn.results.get(call.id)
                    or ToolResult(
                        call.id,
                        "Not completed: the user sent a new request first. "
                        "The action may still finish.",
                        is_error=True,
                    )
                )
        self._turns.clear()
        self._in_flight.clear()
        self._confirmations.clear()
        return results

    def _reset_if_idle(self) -> None:
        now = self._clock()
        if now - self._last_activity > self._idle_reset_seconds:
            # A fresh history has no open tool calls, so forget the pending ones too.
            self._assistant.reset(self._session_id)
            self._turns.clear()
            self._in_flight.clear()
            self._confirmations.clear()
        self._last_activity = now

    # Replies

    def _reply(self, order: Order, text: str) -> None:
        speak = order.source in (Source.VOICE, Source.HOTKEY)
        state = RobotState.SPEAKING if speak else RobotState.SLEEPING
        self._send(order, Status.OK, text, state)

    def _reply_error(self, order: Order, text: str) -> None:
        self._send(order, Status.ERROR, text, RobotState.ANGRY)

    def _send(
        self,
        order: Order,
        status: Status,
        text: str,
        robot_state: RobotState,
        options: list[str] | None = None,
    ) -> None:
        result = Result(
            id=order.id,
            status=status,
            response_text=text,
            speak=order.source in (Source.VOICE, Source.HOTKEY),
            channel=_CHANNELS[order.source],
            robot_state=robot_state,
            options=options,
        )
        self._gateway.reply(result)
        if order.source is Source.ALEXA:
            self._notify(Alert(title="Paula", message=text))

    def _notify(self, alert: Alert) -> None:
        try:
            self._notifier.notify(alert)
        except Exception:
            log.exception("Notifier failed")
