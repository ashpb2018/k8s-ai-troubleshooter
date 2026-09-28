"""Wiring helpers that assemble the runtime components from settings.

Both the CLI and the web server need the same objects (a cluster client, an
operations facade, a backend, and a runbook library). Building them in one
place keeps the two entry points consistent.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cluster import ClusterClient, ClusterOperations
from .providers import ChatBackend, build_backend
from .runbooks import RunbookLibrary
from .settings import Settings


@dataclass(slots=True)
class Runtime:
    settings: Settings
    client: ClusterClient
    operations: ClusterOperations
    backend: ChatBackend
    runbooks: RunbookLibrary


def assemble(settings: Settings) -> Runtime:
    """Connect to the cluster, initialise the backend, and prepare runbooks."""
    client = ClusterClient(
        kubeconfig=settings.resolve_kubeconfig(),
        context=settings.k8s_context,
    )
    operations = ClusterOperations(
        client,
        max_log_lines=settings.max_log_lines,
        auto_approve=settings.auto_approve,
    )
    backend = build_backend(settings)
    runbooks = RunbookLibrary(
        directory=settings.prepare_runbook_dir(),
        cluster=client.active_context(),
        backend=backend.describe(),
    )
    return Runtime(
        settings=settings,
        client=client,
        operations=operations,
        backend=backend,
        runbooks=runbooks,
    )
