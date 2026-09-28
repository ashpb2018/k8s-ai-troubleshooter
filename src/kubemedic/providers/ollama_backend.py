"""Ollama backend — local models with no API key required."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .base import ChatBackend
from .messages import Completion, Conversation, Role, ToolInvocation


def _tool_schema(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def _serialise(conversation: Conversation, system_prompt: str) -> list[dict]:
    wire: list[dict] = []
    if system_prompt:
        wire.append({"role": "system", "content": system_prompt})

    for turn in conversation:
        if turn.role is Role.TOOL:
            wire.append({"role": "tool", "content": turn.text})
        elif turn.role is Role.ASSISTANT and turn.invocations:
            wire.append(
                {
                    "role": "assistant",
                    "content": turn.text or "",
                    "tool_calls": [
                        {"function": {"name": inv.tool, "arguments": inv.arguments}}
                        for inv in turn.invocations
                    ],
                }
            )
        else:
            wire.append({"role": turn.role.value, "content": turn.text})
    return wire


class OllamaBackend(ChatBackend):
    def __init__(self, host: str, model: str) -> None:
        import ollama

        self._model = model
        self._client = ollama.Client(host=host)

    @property
    def label(self) -> str:
        return "Ollama"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        conversation: Conversation,
        tools: list[dict],
        system_prompt: str,
    ) -> Completion:
        reply = self._client.chat(
            model=self._model,
            messages=_serialise(conversation, system_prompt),
            tools=_tool_schema(tools) if tools else None,
        )

        message = reply.message
        invocations: list[ToolInvocation] = []
        for call in message.tool_calls or []:
            args: Any = call.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            invocations.append(
                ToolInvocation(
                    call_id=str(uuid.uuid4()),
                    tool=call.function.name,
                    arguments=args or {},
                )
            )

        return Completion(text=message.content or "", invocations=invocations)
