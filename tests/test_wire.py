"""The browser-facing event contract must stay stable."""

from __future__ import annotations

from kubemedic.agent import events
from kubemedic.web.wire import serialise


def test_speak_maps_to_text():
    assert serialise(events.Speak("hello")) == {"type": "text", "content": "hello"}


def test_tool_start_and_end():
    start = serialise(events.ToolStarted("c1", "list_pods", {"namespace": "prod"}))
    assert start == {
        "type": "tool_call",
        "id": "c1",
        "name": "list_pods",
        "args": {"namespace": "prod"},
    }

    end = serialise(events.ToolFinished("c1", "list_pods", "line1\nline2\nline3"))
    assert end["type"] == "tool_result"
    assert end["line_count"] == 3
    assert "line1" in end["preview"]


def test_finished_and_failure():
    assert serialise(events.Finished()) == {"type": "done"}
    assert serialise(events.Failed("boom")) == {"type": "error", "message": "boom"}


def test_runbook_event():
    payload = serialise(events.RunbookWritten("/x/y.md", "y.md"))
    assert payload == {"type": "runbook", "path": "/x/y.md", "filename": "y.md"}
