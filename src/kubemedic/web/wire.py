"""Serialise agent events into the JSON contract the browser consumes.

The browser distinguishes messages by a ``type`` field. This module is the one
place that knows that contract, so the rest of the Python code can stay in
terms of :class:`AgentEvent` objects.
"""

from __future__ import annotations

from ..agent import events
from ..agent.events import AgentEvent

_PREVIEW_LINES = 20


def serialise(event: AgentEvent) -> dict:
    """Map an :class:`AgentEvent` to the browser's JSON event shape."""
    match event:
        case events.Speak(text):
            return {"type": "text", "content": text}
        case events.ToolStarted(call_id, tool, arguments):
            return {"type": "tool_call", "id": call_id, "name": tool, "args": arguments}
        case events.ToolFinished(call_id, tool, output):
            lines = output.splitlines()
            return {
                "type": "tool_result",
                "id": call_id,
                "name": tool,
                "preview": "\n".join(lines[:_PREVIEW_LINES]),
                "line_count": len(lines),
            }
        case events.Notice(message):
            return {"type": "status", "message": message}
        case events.Failed(message):
            return {"type": "error", "message": message}
        case events.RunbookWritten(path, filename):
            return {"type": "runbook", "path": path, "filename": filename}
        case events.Finished():
            return {"type": "done"}
    return {"type": "status", "message": "unknown event"}
