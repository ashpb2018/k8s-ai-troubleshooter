"""The agent control loop that ties a backend to cluster operations."""

from __future__ import annotations

import inspect
from collections.abc import Callable

from ..cluster.operations import ClusterOperations
from ..providers.base import ChatBackend
from ..providers.messages import Completion, Conversation, ToolInvocation, Turn
from . import events, toolspec
from .events import AgentEvent
from .incident import Incident
from .prompt import SCAN_REQUEST, SYSTEM_PROMPT

EmitFn = Callable[[AgentEvent], None]
ConfirmFn = Callable[[str], bool]


def _coerce_arguments(method: object, arguments: dict) -> dict:
    """Drop null values and any keys the target method does not declare.

    Models occasionally hallucinate parameters or send ``null`` for optionals;
    filtering here keeps the actual call clean.
    """
    cleaned = {key: value for key, value in arguments.items() if value is not None}
    try:
        signature = inspect.signature(method)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return cleaned
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
        return cleaned
    allowed = set(signature.parameters)
    return {key: value for key, value in cleaned.items() if key in allowed}


class Investigator:
    """Runs the reason-act loop until the model stops requesting tools."""

    def __init__(
        self,
        backend: ChatBackend,
        operations: ClusterOperations,
        *,
        emit: EmitFn | None = None,
        confirm: ConfirmFn | None = None,
        max_steps: int = 30,
    ) -> None:
        self._backend = backend
        self._ops = operations
        self._emit_fn = emit
        self._max_steps = max_steps
        self._conversation = Conversation()
        self._used_tools: set[str] = set()

        if confirm is not None:
            self._ops.confirm = confirm

    # -------------------------------------------------------------- emission

    def _emit(self, event: AgentEvent) -> None:
        if self._emit_fn is not None:
            self._emit_fn(event)

    # ------------------------------------------------------------------- api

    def investigate(self, request: str) -> Incident:
        """Work a single request to completion and return the incident record."""
        self._conversation.add(Turn.user(request))
        incident = Incident(request=request)
        final: Completion | None = None

        for _ in range(self._max_steps):
            try:
                completion = self._backend.complete(
                    self._conversation, toolspec.schemas(), SYSTEM_PROMPT
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                self._emit(events.Failed(f"Backend error: {exc}"))
                break

            self._conversation.add(
                Turn.assistant(completion.text, completion.invocations)
            )
            if completion.text:
                self._emit(events.Speak(completion.text))

            if not completion.wants_tools:
                final = completion
                self._emit(events.Finished())
                break

            for invocation in completion.invocations:
                self._dispatch(invocation)
        else:
            self._emit(events.Notice("Reached the step limit for this investigation."))
            self._emit(events.Finished())

        if final and final.text:
            incident.absorb_report(final.text)
            incident.resolved = bool(
                self._used_tools
                & {"restart_deployment", "rollback_deployment", "scale_deployment", "apply_manifest", "patch_resource"}
            )
        return incident

    def scan(self) -> Incident:
        return self.investigate(SCAN_REQUEST)

    def reset(self) -> None:
        self._conversation.clear()
        self._used_tools.clear()

    # -------------------------------------------------------------- dispatch

    def _dispatch(self, invocation: ToolInvocation) -> None:
        self._emit(events.ToolStarted(invocation.call_id, invocation.tool, invocation.arguments))
        output = self._run_tool(invocation)
        self._used_tools.add(invocation.tool)
        self._conversation.add(
            Turn.tool_result(invocation.call_id, invocation.tool, output)
        )
        self._emit(events.ToolFinished(invocation.call_id, invocation.tool, output))

    def _run_tool(self, invocation: ToolInvocation) -> str:
        handler_name = toolspec.handler_for(invocation.tool)
        if handler_name is None:
            return f"Unknown tool: {invocation.tool}"
        method = getattr(self._ops, handler_name, None)
        if method is None:
            return f"Tool '{invocation.tool}' has no implementation."
        try:
            result = method(**_coerce_arguments(method, invocation.arguments))
        except Exception as exc:  # noqa: BLE001 - reported back to the model
            return f"Tool error: {exc}"
        return str(result)
