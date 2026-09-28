"""AWS Bedrock backend using the Converse API.

Authentication is resolved in this order:

1. ``api_key`` — a Bedrock bearer token (Console -> Bedrock -> API keys),
   passed to boto3 via the ``AWS_BEARER_TOKEN_BEDROCK`` environment variable
   (requires ``boto3 >= 1.38``).
2. Explicit IAM credentials (access key / secret / optional session token).
3. The default boto3 credential chain (profiles, instance roles, env vars).
"""

from __future__ import annotations

import os
from typing import Any

from .base import ChatBackend
from .messages import Completion, Conversation, Role, ToolInvocation

_BEARER_ENV = "AWS_BEARER_TOKEN_BEDROCK"


def _tool_schema(tools: list[dict]) -> list[dict]:
    return [
        {
            "toolSpec": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": {
                    "json": tool.get("parameters", {"type": "object", "properties": {}})
                },
            }
        }
        for tool in tools
    ]


def _serialise(conversation: Conversation) -> list[dict]:
    """Convert to Converse format.

    Converse requires that all tool results following an assistant turn are
    grouped into a single ``user`` message, so consecutive TOOL turns are
    coalesced here.
    """
    wire: list[dict] = []
    turns = conversation.turns
    index = 0

    while index < len(turns):
        turn = turns[index]

        if turn.role is Role.TOOL:
            results: list[dict] = []
            while index < len(turns) and turns[index].role is Role.TOOL:
                current = turns[index]
                results.append(
                    {
                        "toolResult": {
                            "toolUseId": current.responds_to or "unknown",
                            "content": [{"text": current.text}],
                        }
                    }
                )
                index += 1
            wire.append({"role": "user", "content": results})
            continue

        if turn.role is Role.ASSISTANT and turn.invocations:
            content: list[dict] = []
            if turn.text:
                content.append({"text": turn.text})
            for inv in turn.invocations:
                content.append(
                    {
                        "toolUse": {
                            "toolUseId": inv.call_id,
                            "name": inv.tool,
                            "input": inv.arguments,
                        }
                    }
                )
            wire.append({"role": "assistant", "content": content})
            index += 1
            continue

        wire.append({"role": turn.role.value, "content": [{"text": turn.text}]})
        index += 1

    return wire


class BedrockBackend(ChatBackend):
    def __init__(
        self,
        model_id: str,
        region: str,
        *,
        api_key: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
    ) -> None:
        import boto3

        self._model_id = model_id

        if api_key:
            os.environ[_BEARER_ENV] = api_key
        elif _BEARER_ENV in os.environ:
            # Clear a stale token so IAM credentials can take over.
            del os.environ[_BEARER_ENV]

        session_kwargs: dict[str, Any] = {"region_name": region}
        if access_key_id:
            session_kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            session_kwargs["aws_secret_access_key"] = secret_access_key
        if session_token:
            session_kwargs["aws_session_token"] = session_token

        self._client = boto3.Session(**session_kwargs).client("bedrock-runtime")

    @property
    def label(self) -> str:
        return "AWS Bedrock"

    @property
    def model(self) -> str:
        return self._model_id

    def complete(
        self,
        conversation: Conversation,
        tools: list[dict],
        system_prompt: str,
    ) -> Completion:
        request: dict[str, Any] = {
            "modelId": self._model_id,
            "messages": _serialise(conversation),
            "inferenceConfig": {"maxTokens": 4096, "temperature": 0},
        }
        if system_prompt:
            request["system"] = [{"text": system_prompt}]
        if tools:
            request["toolConfig"] = {"tools": _tool_schema(tools)}

        try:
            response = self._client.converse(**request)
        except Exception as exc:  # noqa: BLE001 - re-raised with guidance
            raise self._explain(exc) from exc

        message = response["output"]["message"]
        text = ""
        invocations: list[ToolInvocation] = []

        for block in message.get("content", []):
            if "text" in block:
                text += block["text"]
            elif "toolUse" in block:
                use = block["toolUse"]
                invocations.append(
                    ToolInvocation(
                        call_id=use["toolUseId"],
                        tool=use["name"],
                        arguments=use.get("input", {}),
                    )
                )

        return Completion(text=text, invocations=invocations)

    def _explain(self, exc: Exception) -> Exception:
        """Turn common Bedrock errors into actionable messages."""
        detail = str(exc)
        if "Invalid API Key format" in detail or "pre-defined prefix" in detail:
            return RuntimeError(
                "Bedrock rejected the bearer token. Paste it exactly as shown in "
                "AWS Console -> Amazon Bedrock -> API keys, or clear it and use IAM "
                "credentials (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY) instead."
            )
        if "inference profile" in detail.lower() or "on-demand throughput" in detail:
            return RuntimeError(
                f"Model '{self._model_id}' needs a cross-region inference profile. "
                "Use the 'us.'-prefixed model id."
            )
        return exc
