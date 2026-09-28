"""Per-connection agent session for the web UI.

The :class:`Investigator` is synchronous, so each session runs it inside a
worker thread and marshals events back onto the asyncio loop through a queue.
Destructive actions block the worker thread on a :class:`threading.Event`
until the browser answers the confirmation prompt.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

from ..agent import Investigator
from ..agent.events import AgentEvent, RunbookWritten
from ..assembly import assemble
from ..settings import Settings
from .wire import serialise

_CONFIRM_TIMEOUT = 300.0


class WebSession:
    def __init__(self, settings: Settings, loop: asyncio.AbstractEventLoop) -> None:
        self.id = str(uuid.uuid4())
        self._loop = loop
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()

        self._runtime = assemble(settings)
        self._gate = threading.Event()
        self._gate_answer = False

        self._agent = Investigator(
            self._runtime.backend,
            self._runtime.operations,
            emit=self._emit,
            confirm=self._await_confirmation,
            max_steps=settings.max_agent_steps,
        )

    # -------------------------------------------------------------- metadata

    def descriptor(self) -> dict[str, Any]:
        return {
            "type": "provider_info",
            "provider": self._runtime.backend.label,
            "model": self._runtime.backend.model,
            "context": self._runtime.client.active_context(),
            "k8s_version": self._runtime.client.server_version(),
        }

    # ---------------------------------------------------------------- events

    def _emit(self, event: AgentEvent) -> None:
        self._enqueue(serialise(event))

    def _enqueue(self, payload: dict) -> None:
        asyncio.run_coroutine_threadsafe(self.outbox.put(payload), self._loop)

    # ------------------------------------------------------------ agent runs

    def investigate(self, request: str) -> None:
        incident = self._agent.investigate(request)
        self._store_runbook(incident)

    def scan(self) -> None:
        incident = self._agent.scan()
        self._store_runbook(incident)

    def reset(self) -> None:
        self._agent.reset()
        self._enqueue({"type": "reset_ack"})

    def _store_runbook(self, incident) -> None:
        path = self._runtime.runbooks.save(incident)
        self._runtime.runbooks.write_index()
        self._emit(RunbookWritten(str(path), path.name))

    # ----------------------------------------------------------- confirmation

    def _await_confirmation(self, action: str) -> bool:
        request_id = str(uuid.uuid4())
        self._gate.clear()
        self._enqueue({"type": "confirmation_required", "id": request_id, "action": action})
        if not self._gate.wait(timeout=_CONFIRM_TIMEOUT):
            return False
        return self._gate_answer

    def answer_confirmation(self, approved: bool) -> None:
        self._gate_answer = approved
        self._gate.set()
