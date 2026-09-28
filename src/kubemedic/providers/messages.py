"""Backend-neutral conversation types.

These are the lingua franca between the agent and any LLM backend. Each
provider translates a :class:`Conversation` into its own wire format and maps
the response back into a :class:`Completion`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class ToolInvocation:
    """A request from the model to run a named tool with arguments."""

    call_id: str
    tool: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class Turn:
    """A single entry in a conversation."""

    role: Role
    text: str = ""
    invocations: list[ToolInvocation] = field(default_factory=list)
    # Set on TOOL turns to correlate a result with its originating invocation.
    responds_to: str | None = None
    tool_name: str | None = None

    @classmethod
    def user(cls, text: str) -> Turn:
        return cls(role=Role.USER, text=text)

    @classmethod
    def assistant(cls, text: str, invocations: list[ToolInvocation] | None = None) -> Turn:
        return cls(role=Role.ASSISTANT, text=text, invocations=invocations or [])

    @classmethod
    def tool_result(cls, call_id: str, tool_name: str, output: str) -> Turn:
        return cls(
            role=Role.TOOL,
            text=output,
            responds_to=call_id,
            tool_name=tool_name,
        )


class Conversation:
    """An ordered, mutable list of :class:`Turn` objects."""

    def __init__(self, turns: list[Turn] | None = None) -> None:
        self._turns: list[Turn] = turns or []

    def add(self, turn: Turn) -> None:
        self._turns.append(turn)

    def extend(self, turns: list[Turn]) -> None:
        self._turns.extend(turns)

    def clear(self) -> None:
        self._turns.clear()

    @property
    def turns(self) -> list[Turn]:
        return self._turns

    def __len__(self) -> int:
        return len(self._turns)

    def __iter__(self):
        return iter(self._turns)


@dataclass(slots=True)
class Completion:
    """The model's reply for one round of the agent loop."""

    text: str = ""
    invocations: list[ToolInvocation] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.invocations)
