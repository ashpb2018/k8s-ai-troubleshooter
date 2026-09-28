"""The reason-act loop, driven by a scripted fake backend."""

from __future__ import annotations

from kubemedic.agent import events
from kubemedic.agent.loop import Investigator, _coerce_arguments
from kubemedic.providers.base import ChatBackend
from kubemedic.providers.messages import Completion, Conversation, ToolInvocation


class ScriptedBackend(ChatBackend):
    """Returns a queued list of completions, one per call."""

    def __init__(self, script: list[Completion]) -> None:
        self._script = list(script)
        self.calls = 0

    def complete(self, conversation: Conversation, tools, system_prompt) -> Completion:
        self.calls += 1
        return self._script.pop(0)

    @property
    def label(self) -> str:
        return "Scripted"

    @property
    def model(self) -> str:
        return "test"


class FakeOps:
    """Stand-in for ClusterOperations recording calls."""

    def __init__(self) -> None:
        self.confirm = None
        self.seen: list[tuple[str, dict]] = []

    def triage(self) -> str:
        self.seen.append(("triage", {}))
        return "all nodes ready"

    def restart_deployment(self, name: str, namespace: str = "default") -> str:
        self.seen.append(("restart_deployment", {"name": name, "namespace": namespace}))
        return f"restarted {namespace}/{name}"


def test_coerce_arguments_drops_unknown_and_none():
    def method(name, namespace="default"):
        return name, namespace

    cleaned = _coerce_arguments(method, {"name": "web", "namespace": None, "bogus": 1})
    assert cleaned == {"name": "web"}


def test_loop_runs_tool_then_finishes():
    backend = ScriptedBackend(
        [
            Completion(text="looking", invocations=[ToolInvocation("c1", "cluster_triage", {})]),
            Completion(text="**Root Cause**\nNothing wrong."),
        ]
    )
    ops = FakeOps()
    seen: list = []
    agent = Investigator(backend, ops, emit=seen.append)

    incident = agent.investigate("check the cluster")

    assert ops.seen == [("triage", {})]
    assert backend.calls == 2
    assert "Nothing wrong" in incident.root_cause
    assert any(isinstance(e, events.ToolStarted) for e in seen)
    assert any(isinstance(e, events.Finished) for e in seen)


def test_loop_marks_resolved_when_remediation_tool_used():
    backend = ScriptedBackend(
        [
            Completion(
                text="fixing",
                invocations=[ToolInvocation("c1", "restart_deployment", {"name": "web"})],
            ),
            Completion(text="**Fix Applied**\nRestarted the deployment."),
        ]
    )
    agent = Investigator(backend, FakeOps(), emit=lambda _e: None)
    incident = agent.investigate("restart web")
    assert incident.resolved is True


def test_narrative_falls_back_to_last_prose_when_final_turn_empty():
    # Many models stop producing text after their final tool call; the loop
    # should still capture the earlier prose in the runbook narrative.
    backend = ScriptedBackend(
        [
            Completion(
                text="**Root Cause**\nBad image tag.",
                invocations=[ToolInvocation("c1", "cluster_triage", {})],
            ),
            Completion(text=""),  # empty final turn, no tool calls
        ]
    )
    agent = Investigator(backend, FakeOps(), emit=lambda _e: None)
    incident = agent.investigate("what is wrong?")
    assert "Bad image tag" in incident.root_cause
    assert incident.narrative


def test_unknown_tool_reports_error_without_crashing():
    backend = ScriptedBackend(
        [
            Completion(text="", invocations=[ToolInvocation("c1", "no_such_tool", {})]),
            Completion(text="done"),
        ]
    )
    seen: list = []
    agent = Investigator(backend, FakeOps(), emit=seen.append)
    agent.investigate("do a thing")
    finished = [e for e in seen if isinstance(e, events.ToolFinished)]
    assert finished and "Unknown tool" in finished[0].output
