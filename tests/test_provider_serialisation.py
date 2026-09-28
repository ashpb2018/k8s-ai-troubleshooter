"""Conversation → wire-format translation for each backend.

These exercise the pure serialisation functions without touching any SDK.
"""

from __future__ import annotations

from kubemedic.providers.bedrock_backend import _serialise as bedrock_serialise
from kubemedic.providers.messages import Conversation, ToolInvocation, Turn
from kubemedic.providers.ollama_backend import _serialise as ollama_serialise
from kubemedic.providers.openai_backend import _serialise as openai_serialise


def _conversation_with_tool_round() -> Conversation:
    convo = Conversation()
    convo.add(Turn.user("what is wrong?"))
    convo.add(
        Turn.assistant(
            "let me look",
            [ToolInvocation(call_id="c1", tool="list_pods", arguments={"namespace": "prod"})],
        )
    )
    convo.add(Turn.tool_result("c1", "list_pods", "pod output"))
    return convo


def test_openai_serialisation_shapes():
    wire = openai_serialise(_conversation_with_tool_round(), "system text")
    assert wire[0] == {"role": "system", "content": "system text"}
    assert wire[1]["role"] == "user"
    assistant = wire[2]
    assert assistant["tool_calls"][0]["function"]["name"] == "list_pods"
    tool = wire[3]
    assert tool["role"] == "tool"
    assert tool["tool_call_id"] == "c1"


def test_ollama_serialisation_shapes():
    wire = ollama_serialise(_conversation_with_tool_round(), "system text")
    assert wire[0]["role"] == "system"
    assistant = next(m for m in wire if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["function"]["name"] == "list_pods"
    assert any(m["role"] == "tool" for m in wire)


def test_bedrock_merges_consecutive_tool_results():
    convo = Conversation()
    convo.add(
        Turn.assistant(
            "",
            [
                ToolInvocation(call_id="a", tool="list_pods", arguments={}),
                ToolInvocation(call_id="b", tool="list_nodes", arguments={}),
            ],
        )
    )
    convo.add(Turn.tool_result("a", "list_pods", "pods"))
    convo.add(Turn.tool_result("b", "list_nodes", "nodes"))

    wire = bedrock_serialise(convo)
    # The two tool results collapse into a single user message.
    user_turns = [m for m in wire if m["role"] == "user"]
    assert len(user_turns) == 1
    tool_results = user_turns[0]["content"]
    assert {tr["toolResult"]["toolUseId"] for tr in tool_results} == {"a", "b"}
