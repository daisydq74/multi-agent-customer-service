from __future__ import annotations

import dataclasses
from typing import Any, List


@dataclasses.dataclass
class A2AEvent:
    sender: str
    receiver: str
    action: str
    args: Any

    def format(self) -> str:
        return f"[A2A] from={self.sender} to={self.receiver} action={self.action} args={self.args}"


class ConversationLog:
    """Minimal log to make A2A hops explicit."""

    def __init__(self) -> None:
        self.events: List[A2AEvent] = []

    def record(self, sender: str, receiver: str, action: str, args: Any) -> None:
        self.events.append(A2AEvent(sender, receiver, action, args))

    def clear(self) -> None:
        self.events.clear()

    def dump(self) -> str:
        return "\n".join(event.format() for event in self.events)
