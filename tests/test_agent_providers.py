import json
import os

import httpx
import pytest

from researchdesk.agents.providers import ClaudeCLIProvider, OpenAIProvider, ProviderConfig


def test_openai_replays_native_reasoning_and_actual_tool_result(monkeypatch):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "id": "r1",
                    "output": [
                        {
                            "type": "reasoning",
                            "id": "reason",
                            "summary": [],
                            "encrypted_content": "fixture",
                        },
                        {
                            "type": "function_call",
                            "id": "fc",
                            "call_id": "c1",
                            "name": "inspect",
                            "arguments": '{"x": 2}',
                        },
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "id": "r2",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Result 4"}],
                    }
                ],
            },
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond))
    )
    provider = OpenAIProvider(ProviderConfig("openai", "fixture-model", "fixture-key"))
    messages = [{"role": "user", "content": "Calculate"}]
    first = provider.complete(messages, [], "Instruction")
    assert first.tool_calls[0].arguments == {"x": 2}
    messages += [
        first.message(),
        {"role": "tool", "tool_call_id": "c1", "content": {"ok": True, "data": 4}},
    ]
    assert provider.complete(messages, [], "Instruction").text == "Result 4"
    assert requests[1]["input"][1]["type"] == "reasoning"
    assert requests[1]["input"][-1]["type"] == "function_call_output"
    assert json.loads(requests[1]["input"][-1]["output"])["data"] == 4
    assert requests[1]["store"] is False


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("RESEARCHDESK_LIVE_CLAUDE") != "1",
    reason="Explicit real-provider smoke opt-in required",
)
def test_authenticated_claude_requests_and_consumes_application_tool():
    provider = ClaudeCLIProvider(
        ProviderConfig(
            provider="claude_cli",
            model="haiku",
            claude_binary=os.environ.get("CLAUDE_BINARY", "claude"),
            timeout_seconds=120,
        )
    )
    tools = [
        {
            "type": "function",
            "name": "lookup_value",
            "description": "Retrieve the actual opaque test value",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        }
    ]
    messages = [
        {
            "role": "user",
            "content": "Call lookup_value, then report its exact opaque value. Do not guess.",
        }
    ]
    first = provider.complete(messages, tools, "Use the application registry for every lookup.")
    assert len(first.tool_calls) == 1 and first.tool_calls[0].name == "lookup_value"
    value = "verified-" + os.urandom(8).hex()
    messages += [
        first.message(),
        {
            "role": "tool",
            "tool_call_id": first.tool_calls[0].id,
            "content": {"ok": True, "data": {"value": value}},
        },
    ]
    final = provider.complete(messages, tools, "Use the application registry for every lookup.")
    assert not final.tool_calls and value in final.text
