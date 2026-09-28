"""FastAPI application factory for the KubeMedic web UI."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..settings import Backend, load_settings, write_env_values
from .session import WebSession

_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "web" / "frontend" / "dist"


class ConfigPatch(BaseModel):
    llm_provider: str | None = None
    ollama_model: str | None = None
    bedrock_model_id: str | None = None
    aws_region: str | None = None
    bedrock_api_key: str | None = None
    aws_session_token: str | None = None
    openai_model: str | None = None
    openai_api_key: str | None = None
    k8s_context: str | None = None
    auto_fix: bool | None = None
    max_log_lines: int | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="KubeMedic", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    sessions: dict[str, WebSession] = {}

    # ---------------------------------------------------------- websocket

    @app.websocket("/ws/{session_id}")
    async def stream(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        loop = asyncio.get_running_loop()
        try:
            session = sessions.get(session_id) or WebSession(load_settings(), loop)
            sessions[session_id] = session
        except Exception as exc:  # noqa: BLE001 - report and close
            await websocket.send_json({"kind": "error", "message": str(exc)})
            await websocket.close()
            return

        await websocket.send_json(session.descriptor())

        async def pump_outbox() -> None:
            while True:
                payload = await session.outbox.get()
                await websocket.send_json(payload)

        async def pump_inbox() -> None:
            async for message in websocket.iter_json():
                await _handle_inbound(loop, session, message)

        try:
            await asyncio.gather(pump_outbox(), pump_inbox())
        except (WebSocketDisconnect, Exception):
            pass

    # ------------------------------------------------------------- config

    @app.get("/api/config")
    def read_config() -> dict:
        s = load_settings()
        return {
            "llm_provider": s.backend.value,
            "ollama_host": s.ollama_host,
            "ollama_model": s.ollama_model,
            "bedrock_model_id": s.bedrock_model_id,
            "aws_region": s.aws_region,
            "bedrock_api_key_configured": bool(s.bedrock_api_key),
            "aws_session_token_configured": bool(s.aws_session_token),
            "openai_model": s.openai_model,
            "openai_api_key_configured": bool(s.openai_api_key),
            "k8s_context": s.k8s_context or "",
            "auto_fix": s.auto_approve,
            "max_log_lines": s.max_log_lines,
            "runbook_dir": str(s.runbook_dir),
        }

    @app.post("/api/config")
    def write_config(patch: ConfigPatch) -> dict:
        _persist_config(patch)
        sessions.clear()
        load_settings(refresh=True)
        return {"status": "ok"}

    # ----------------------------------------------------------- cluster

    @app.get("/api/cluster/contexts")
    def contexts() -> dict:
        try:
            from kubernetes import config as kconfig

            available, active = kconfig.list_kube_config_contexts()
            return {
                "contexts": [c["name"] for c in available],
                "active": active["name"] if active else "",
            }
        except Exception as exc:  # noqa: BLE001
            return {"contexts": [], "active": "", "error": str(exc)}

    # ---------------------------------------------------------- runbooks

    @app.get("/api/runbooks")
    def runbooks() -> dict:
        directory = load_settings().runbook_dir
        if not directory.exists():
            return {"runbooks": []}
        items = []
        for path in sorted(directory.glob("*.md"), reverse=True):
            if path.name == "index.md":
                continue
            items.append(
                {
                    "filename": path.name,
                    "title": _title_of(path),
                    "date": _date_of(path),
                    "size": path.stat().st_size,
                }
            )
        return {"runbooks": items}

    @app.get("/api/runbooks/{filename}")
    def runbook(filename: str) -> dict:
        path = _safe_runbook_path(filename)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Runbook not found")
        return {"filename": filename, "content": path.read_text(encoding="utf-8")}

    @app.delete("/api/runbooks/{filename}")
    def remove_runbook(filename: str) -> dict:
        path = _safe_runbook_path(filename)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Runbook not found")
        path.unlink()
        return {"status": "deleted"}

    # -------------------------------------------------------- static SPA

    if _FRONTEND_DIST.exists():
        app.mount(
            "/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets"
        )

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:
            return FileResponse(_FRONTEND_DIST / "index.html")
    else:

        @app.get("/")
        def dev_hint() -> HTMLResponse:
            return HTMLResponse(
                "<h2>KubeMedic backend is running.</h2>"
                "<p>Start the UI with <code>npm run dev</code> in web/frontend.</p>"
            )

    return app


# ---------------------------------------------------------------- inbound


async def _handle_inbound(loop, session: WebSession, message: dict) -> None:
    kind = message.get("type")
    if kind == "message":
        text = (message.get("content") or "").strip()
        if text:
            loop.run_in_executor(None, session.investigate, text)
    elif kind == "scan":
        loop.run_in_executor(None, session.scan)
    elif kind == "fix":
        problem = (message.get("problem") or "").strip()
        namespace = (message.get("namespace") or "").strip()
        if namespace:
            problem = f"[namespace: {namespace}] {problem}"
        if problem:
            loop.run_in_executor(None, session.investigate, problem)
    elif kind == "confirm":
        session.answer_confirmation(bool(message.get("answer", False)))
    elif kind == "reset":
        loop.run_in_executor(None, session.reset)


# ----------------------------------------------------------------- helpers


def _persist_config(patch: ConfigPatch) -> None:
    s = load_settings()
    updates: dict[str, str] = {}

    if patch.llm_provider:
        s.backend = Backend(patch.llm_provider)
        updates["LLM_PROVIDER"] = patch.llm_provider
    if patch.ollama_model:
        s.ollama_model = patch.ollama_model
        updates["OLLAMA_MODEL"] = patch.ollama_model
    if patch.bedrock_model_id:
        s.bedrock_model_id = patch.bedrock_model_id
        updates["BEDROCK_MODEL_ID"] = patch.bedrock_model_id
    if patch.aws_region:
        s.aws_region = patch.aws_region
        updates["AWS_REGION"] = patch.aws_region
    if patch.bedrock_api_key:
        s.bedrock_api_key = patch.bedrock_api_key
        updates["BEDROCK_API_KEY"] = patch.bedrock_api_key
    if patch.aws_session_token:
        s.aws_session_token = patch.aws_session_token
        updates["AWS_SESSION_TOKEN"] = patch.aws_session_token
    if patch.openai_model:
        s.openai_model = patch.openai_model
        updates["OPENAI_MODEL"] = patch.openai_model
    if patch.openai_api_key:
        s.openai_api_key = patch.openai_api_key
        updates["OPENAI_API_KEY"] = patch.openai_api_key
    if patch.k8s_context is not None:
        s.k8s_context = patch.k8s_context or None
        updates["K8S_CONTEXT"] = patch.k8s_context or ""
    if patch.auto_fix is not None:
        s.auto_approve = patch.auto_fix
        updates["AUTO_FIX"] = "true" if patch.auto_fix else "false"
    if patch.max_log_lines is not None:
        s.max_log_lines = patch.max_log_lines
        updates["MAX_LOG_LINES"] = str(patch.max_log_lines)

    if updates:
        write_env_values(updates)


def _safe_runbook_path(filename: str) -> Path:
    directory = load_settings().runbook_dir
    candidate = (directory / filename).resolve()
    # Prevent path traversal outside the runbook directory.
    if directory.resolve() not in candidate.parents or candidate.suffix != ".md":
        raise HTTPException(status_code=400, detail="Invalid runbook name")
    return candidate


def _date_of(path: Path) -> str:
    try:
        return datetime.strptime(path.stem[:15], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "?"


def _title_of(path: Path) -> str:
    remainder = path.stem[16:]
    return remainder.replace("-", " ").title() if remainder else path.stem


app = create_app()
