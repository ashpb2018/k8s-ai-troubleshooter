"""Runtime configuration for KubeMedic.

Settings are layered: defaults in code, overridden by a ``.env`` file, then by
process environment variables. The ``.env`` path is resolved relative to the
current working directory's project root so the CLI and the web server behave
identically regardless of where they are launched from.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(str, Enum):
    """Supported LLM backends."""

    OLLAMA = "ollama"
    BEDROCK = "bedrock"
    OPENAI = "openai"


def _project_root() -> Path:
    """Locate the repository root by walking up from this file."""
    # src/kubemedic/settings.py -> src/kubemedic -> src -> <root>
    return Path(__file__).resolve().parents[2]


ENV_PATH = _project_root() / ".env"


class Settings(BaseSettings):
    """Central configuration object, populated from the environment."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- backend selection ---------------------------------------------------
    backend: Backend = Field(default=Backend.OLLAMA, alias="llm_provider")

    # --- ollama --------------------------------------------------------------
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # --- aws bedrock ---------------------------------------------------------
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    bedrock_api_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # --- openai --------------------------------------------------------------
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    # --- kubernetes ----------------------------------------------------------
    kubeconfig: str | None = None
    k8s_context: str | None = None

    # --- behaviour -----------------------------------------------------------
    auto_approve: bool = Field(default=False, alias="auto_fix")
    runbook_dir: Path = Path("./runbooks")
    max_log_lines: int = 200
    max_agent_steps: int = 30
    debug: bool = False

    @field_validator(
        "bedrock_api_key",
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
        "openai_api_key",
        "kubeconfig",
        "k8s_context",
        mode="before",
    )
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        """Treat blank env values as unset so ``if setting:`` works cleanly."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("runbook_dir", mode="before")
    @classmethod
    def _resolve_runbook_dir(cls, value: object) -> Path:
        return Path(str(value)).expanduser().resolve()

    # --- derived helpers -----------------------------------------------------

    @property
    def active_model(self) -> str:
        """The model name for the currently selected backend."""
        return {
            Backend.OLLAMA: self.ollama_model,
            Backend.BEDROCK: self.bedrock_model_id,
            Backend.OPENAI: self.openai_model,
        }[self.backend]

    def resolve_kubeconfig(self) -> str | None:
        """Determine which kubeconfig path to hand to the client, if any."""
        if self.kubeconfig:
            return str(Path(self.kubeconfig).expanduser())
        env_path = os.environ.get("KUBECONFIG")
        if env_path:
            return env_path
        default = Path.home() / ".kube" / "config"
        return str(default) if default.exists() else None

    def prepare_runbook_dir(self) -> Path:
        """Create the runbook directory if needed and return it."""
        self.runbook_dir.mkdir(parents=True, exist_ok=True)
        return self.runbook_dir


_cached: Settings | None = None


def load_settings(*, refresh: bool = False) -> Settings:
    """Return a process-wide :class:`Settings` singleton.

    Pass ``refresh=True`` to rebuild it after mutating the ``.env`` file.
    """
    global _cached
    if _cached is None or refresh:
        _cached = Settings()
    return _cached


def write_env_values(values: dict[str, str]) -> None:
    """Merge ``values`` into the ``.env`` file, preserving layout and comments.

    Existing keys are updated in place; unknown keys are appended. The file is
    bootstrapped from ``.env.example`` when it does not yet exist.
    """
    path = ENV_PATH
    if not path.exists():
        example = path.parent / ".env.example"
        path.write_text(
            example.read_text(encoding="utf-8") if example.exists() else "",
            encoding="utf-8",
        )

    original = path.read_text(encoding="utf-8").splitlines(keepends=True)
    remaining = dict(values)
    rewritten: list[str] = []

    for line in original:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rewritten.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            rewritten.append(f"{key}={remaining.pop(key)}\n")
        else:
            rewritten.append(line)

    for key, value in remaining.items():
        rewritten.append(f"{key}={value}\n")

    path.write_text("".join(rewritten), encoding="utf-8")
