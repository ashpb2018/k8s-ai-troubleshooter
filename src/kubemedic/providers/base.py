"""The abstract contract every LLM backend must satisfy."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .messages import Completion, Conversation


class ChatBackend(ABC):
    """Provider-agnostic chat interface with tool-calling support."""

    @abstractmethod
    def complete(
        self,
        conversation: Conversation,
        tools: list[dict],
        system_prompt: str,
    ) -> Completion:
        """Produce the next assistant turn, possibly requesting tool calls."""

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable backend name, e.g. ``"OpenAI"``."""

    @property
    @abstractmethod
    def model(self) -> str:
        """The concrete model identifier in use."""

    def describe(self) -> str:
        return f"{self.label} / {self.model}"
