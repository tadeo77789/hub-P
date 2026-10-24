from typing import Protocol

from paula_hub.domain.messages import Action, Result


class AgentGatewayPort(Protocol):
    """Delivers replies and actions to the PC agent."""

    def reply(self, result: Result) -> None: ...

    def dispatch(self, action: Action) -> None: ...
