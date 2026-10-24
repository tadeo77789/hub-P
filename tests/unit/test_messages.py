from paula_hub.domain.messages import (
    Action,
    Channel,
    Event,
    Intent,
    Order,
    Result,
    RobotState,
    Source,
    Status,
)


def test_order_round_trip():
    order = Order(source=Source.HOTKEY, intent=Intent.CONVERSATION, payload={"text": " hola "})
    data = order.to_dict()

    assert data["source"] == "hotkey"
    assert data["intent"] == "conversation"
    assert Order.from_dict(data) == order
    assert order.text == "hola"


def test_result_omits_options_unless_question():
    plain = Result("1", Status.OK, "Listo", True, Channel.PC, RobotState.SPEAKING)
    question = Result(
        "2", Status.QUESTION, "¿Seguro?", True, Channel.PC, RobotState.QUESTION, ["Sí", "No"]
    )

    assert "options" not in plain.to_dict()
    assert question.to_dict()["options"] == ["Sí", "No"]
    assert Result.from_dict(question.to_dict()) == question


def test_action_and_event_round_trip():
    action = Action(order_id="o1", command="open_app", args={"app": "spotify"})
    event = Event(
        action_id=action.id, status=Status.ERROR, output="not found", duration_seconds=1.5
    )

    assert Action.from_dict(action.to_dict()) == action
    assert Event.from_dict(event.to_dict()) == event
