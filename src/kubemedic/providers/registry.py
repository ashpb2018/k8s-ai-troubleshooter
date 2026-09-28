"""Factory that turns :class:`Settings` into a concrete backend."""

from __future__ import annotations

from ..settings import Backend, Settings
from .base import ChatBackend


class BackendConfigError(RuntimeError):
    """Raised when a backend is selected but not configured correctly."""


def build_backend(settings: Settings) -> ChatBackend:
    """Instantiate the backend named by ``settings.backend``.

    Provider SDKs are imported lazily inside each backend, so installing only
    the extra you use (``pip install kubemedic[openai]``) is enough.
    """
    if settings.backend is Backend.OLLAMA:
        from .ollama_backend import OllamaBackend

        return OllamaBackend(host=settings.ollama_host, model=settings.ollama_model)

    if settings.backend is Backend.OPENAI:
        if not settings.openai_api_key:
            raise BackendConfigError("OPENAI_API_KEY is required for the OpenAI backend.")
        from .openai_backend import OpenAIBackend

        return OpenAIBackend(api_key=settings.openai_api_key, model=settings.openai_model)

    if settings.backend is Backend.BEDROCK:
        from .bedrock_backend import BedrockBackend

        return BedrockBackend(
            model_id=settings.bedrock_model_id,
            region=settings.aws_region,
            api_key=settings.bedrock_api_key,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            session_token=settings.aws_session_token,
        )

    raise BackendConfigError(f"Unsupported backend: {settings.backend}")
