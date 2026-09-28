"""FastAPI application exposing KubeMedic over HTTP and WebSockets."""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
