from collections.abc import Sequence

import pytest

from paula_hub.application.assistant_service import CONFIRM_NO, CONFIRM_YES, AssistantService
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
from paula_hub.ports.outbound.assistant import AssistantError


class FakeAssistant:
    def __init__(self, *turns: AssistantTurn | Exception) -> None:
        self.turns = list(turns)
        self.calls: list[tuple[str | None, list[ToolResult]]] = []
        self.resets = 0

    def send(self, session_id: str, *, text=None, results: Sequence[ToolResult] = ()):
        self.calls.append((text, list(results)))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn

    def reset(self, session_id: str) -> None:
        self.resets += 1


class FakeGateway:
    def __init__(self) -> None:
        self.replies: list[Result] = []
        self.actions: list[Action] = []

    def reply(self, result: Result) -> None:
        self.replies.append(result)

    def dispatch(self, action: Action) -> None:
        self.actions.append(action)


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def notify(self, alert: Alert) -> None:
        self.alerts.append(alert)


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def notifier():
    return FakeNotifier()


def make_service(assistant, gateway, notifier, **kwargs):
    return AssistantService(assistant, gateway, notifier, **kwargs)


def voice(text: str) -> Order:
    return Order(source=Source.VOICE, intent=Intent.CONVERSATION, payload={"text": text})


def test_plain_conversation_is_spoken(gateway, notifier):
    service = make_service(FakeAssistant(AssistantTurn("Hola, Ola")), gateway, notifier)
    order = voice("hola")

    service.handle_order(order)

    [reply] = gateway.replies
    assert reply.id == order.id
    assert reply.status is Status.OK
    assert reply.speak is True
    assert reply.channel is Channel.PC
    assert reply.robot_state is RobotState.SPEAKING


def test_chat_reply_is_not_spoken(gateway, notifier):
    service = make_service(FakeAssistant(AssistantTurn("Hola")), gateway, notifier)

    service.handle_order(
        Order(source=Source.CHAT, intent=Intent.CONVERSATION, payload={"text": "hola"})
    )

    [reply] = gateway.replies
    assert reply.speak is False
    assert reply.channel is Channel.CHAT
    assert reply.robot_state is RobotState.SLEEPING


def test_tool_call_dispatches_action_then_replies_with_result(gateway, notifier):
    assistant = FakeAssistant(
        AssistantTurn("", [ToolCall("t1", "open_app", {"app": "navegador"})]),
        AssistantTurn("Listo, abrí el navegador."),
    )
    service = make_service(assistant, gateway, notifier)

    service.handle_order(voice("abre el navegador"))
    [action] = gateway.actions
    assert action.command == "open_app"
    assert action.args == {"app": "navegador"}
    assert gateway.replies == []

    service.handle_event(Event(action_id=action.id, status=Status.OK, output="opened"))

    assert assistant.calls[-1] == (None, [ToolResult("t1", "opened")])
    assert gateway.replies[-1].response_text == "Listo, abrí el navegador."


def test_destructive_command_asks_and_runs_on_yes(gateway, notifier):
    assistant = FakeAssistant(
        AssistantTurn("¿Apago el PC?", [ToolCall("t1", "shutdown_pc", {})]),
        AssistantTurn("Apagando en un minuto."),
    )
    service = make_service(assistant, gateway, notifier)
    order = voice("apaga el pc")

    service.handle_order(order)
    [question] = gateway.replies
    assert question.status is Status.QUESTION
    assert question.options == [CONFIRM_YES, CONFIRM_NO]
    assert question.robot_state is RobotState.QUESTION
    assert gateway.actions == []

    service.handle_order(
        Order(Source.CHAT, Intent.CONFIRM, {"text": CONFIRM_YES, "reply_to": order.id})
    )
    [action] = gateway.actions
    assert action.confirmed is True

    service.handle_event(Event(action_id=action.id, status=Status.OK, output="scheduled"))
    assert gateway.replies[-1].response_text == "Apagando en un minuto."
    assert gateway.replies[-1].id == order.id


def test_destructive_command_declined_does_nothing(gateway, notifier):
    assistant = FakeAssistant(
        AssistantTurn("", [ToolCall("t1", "shutdown_pc", {})]),
        AssistantTurn("Entendido, no lo apago."),
    )
    service = make_service(assistant, gateway, notifier)
    order = voice("apaga el pc")

    service.handle_order(order)
    service.handle_order(
        Order(Source.CHAT, Intent.CONFIRM, {"text": CONFIRM_NO, "reply_to": order.id})
    )

    assert gateway.actions == []
    assert assistant.calls[-1][1][0].content.startswith("The user declined")
    assert gateway.replies[-1].response_text == "Entendido, no lo apago."


def test_unknown_command_is_reported_to_assistant(gateway, notifier):
    assistant = FakeAssistant(
        AssistantTurn("", [ToolCall("t1", "format_disk", {})]),
        AssistantTurn("No puedo hacer eso."),
    )
    service = make_service(assistant, gateway, notifier)

    service.handle_order(voice("formatea el disco"))

    assert gateway.actions == []
    [result] = assistant.calls[-1][1]
    assert result.is_error is True
    assert gateway.replies[-1].response_text == "No puedo hacer eso."


def test_new_order_closes_pending_confirmation(gateway, notifier):
    assistant = FakeAssistant(
        AssistantTurn("", [ToolCall("t1", "shutdown_pc", {})]),
        AssistantTurn("Hola de nuevo"),
    )
    service = make_service(assistant, gateway, notifier)

    service.handle_order(voice("apaga el pc"))
    service.handle_order(voice("mejor dime hola"))

    text, results = assistant.calls[-1]
    assert text == "mejor dime hola"
    assert [r.tool_call_id for r in results] == ["t1"]
    assert results[0].is_error is True


def test_assistant_error_makes_robot_angry(gateway, notifier):
    service = make_service(FakeAssistant(AssistantError("down")), gateway, notifier)

    service.handle_order(voice("hola"))

    [reply] = gateway.replies
    assert reply.status is Status.ERROR
    assert reply.robot_state is RobotState.ANGRY


def test_long_task_sends_alert(gateway, notifier):
    assistant = FakeAssistant(
        AssistantTurn("", [ToolCall("t1", "system_status", {})]),
        AssistantTurn("Todo bien."),
    )
    service = make_service(assistant, gateway, notifier, long_task_seconds=10)

    service.handle_order(voice("cómo está el pc"))
    [action] = gateway.actions
    service.handle_event(
        Event(action_id=action.id, status=Status.OK, output="cpu 5%", duration_seconds=12)
    )

    [alert] = notifier.alerts
    assert alert.title == "Tarea terminada"


def test_empty_text_is_not_sent_to_assistant(gateway, notifier):
    assistant = FakeAssistant()
    service = make_service(assistant, gateway, notifier)

    service.handle_order(voice("   "))

    assert assistant.calls == []
    assert gateway.replies[0].status is Status.OK


def test_conversation_resets_after_idle(gateway, notifier):
    now = [0.0]
    assistant = FakeAssistant(AssistantTurn("uno"), AssistantTurn("dos"))
    service = make_service(
        assistant, gateway, notifier, idle_reset_seconds=60, clock=lambda: now[0]
    )

    service.handle_order(voice("hola"))
    now[0] = 120.0
    service.handle_order(voice("hola otra vez"))

    assert assistant.resets == 1
