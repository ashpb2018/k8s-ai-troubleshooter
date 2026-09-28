"""OpenAI backend using the Chat Completions API."""

from __future__ import annotations

import json

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
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": turn.responds_to or "unknown",
                    "content": turn.text,
                }
            )
        elif turn.role is Role.ASSISTANT and turn.invocations:
            wire.append(
                {
                    "role": "assistant",
                    "content": turn.text or None,
                    "tool_calls": [
                        {
                            "id": inv.call_id,
                            "type": "function",
                            "function": {
                                "name": inv.tool,
                                "arguments": json.dumps(inv.arguments),
                            },
                        }
                        for inv in turn.invocations
                    ],
                }
            )
        else:
            wire.append({"role": turn.role.value, "content": turn.text})
    return wire


class OpenAIBackend(ChatBackend):
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self._model = model
        self._client = OpenAI(api_key=api_key)

    @property
    def label(self) -> str:
        return "OpenAI"

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        conversation: Conversation,
        tools: list[dict],
        system_prompt: str,
    ) -> Completion:
        request: dict = {
            "model": self._model,
            "messages": _serialise(conversation, system_prompt),
            "temperature": 0,
            "max_tokens": 4096,
        }
        if tools:
            request["tools"] = _tool_schema(tools)
            request["tool_choice"] = "auto"

        message = self._client.chat.completions.create(**request).choices[0].message

        invocations: list[ToolInvocation] = []
        for call in message.tool_calls or []:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                args = {}
            invocations.append(
                ToolInvocation(
                    call_id=call.id,
                    tool=call.function.name,
                    arguments=args,
                )
            )

        return Completion(text=message.content or "", invocations=invocations)
