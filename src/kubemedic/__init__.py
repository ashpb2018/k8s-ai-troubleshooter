"""KubeMedic — an LLM-driven Kubernetes troubleshooting agent.

KubeMedic connects a large language model to a curated set of Kubernetes
operations. It investigates a cluster, reasons about what is wrong, applies
safe remediations (with confirmation), and records a Markdown runbook for
every incident it works through.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
