"""Structured events emitted by the agent as it works.

Both the CLI renderer and the web server subscribe to the same event stream,
so neither transport needs to know about the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Speak:
    """The assistant produced prose."""

    text: str


@dataclass(slots=True)
class ToolStarted:
    call_id: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolFinished:
    call_id: str
    tool: str
    output: str


@dataclass(slots=True)
class Notice:
    message: str


@dataclass(slots=True)
class Failed:
    message: str


@dataclass(slots=True)
class Finished:
    pass


@dataclass(slots=True)
class RunbookWritten:
    path: str
    filename: str


AgentEvent = Speak | ToolStarted | ToolFinished | Notice | Failed | Finished | RunbookWritten
