import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from kbfromyt.chat.config import ChatConfig
from kbfromyt.chat.contracts import Draft
from kbfromyt.chat.providers.openai import OpenAIProvider, ProviderError
from kbfromyt.chat.tools import tool_schemas


def response_payload(**overrides):
    return {
        "id": "resp_test",
        "created_at": 1,
        "object": "response",
        "status": "completed",
        "model": "gpt-6-luna",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"claims":[],"unanswered":[]}',
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 5,
            "total_tokens": 17,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        **overrides,
    }


def test_real_sdk_contract_uses_custom_endpoint_and_stateless_inputs():
    captured = []

    def handler(request):
        captured.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json=response_payload())

    async def scenario():
        config = ChatConfig(
            api_key="test-secret", base_url="https://gateway.example/v1", model="deployment-name"
        )
        client = AsyncOpenAI(
            api_key="test-secret",
            base_url=config.base_url,
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        provider = OpenAIProvider(config, client)
        try:
            result = await provider.respond(
                [{"role": "user", "content": "q"}],
                "Policy",
                Draft,
                tool_schemas(),
                {"type": "function", "name": "search_transcripts"},
            )
            assert result.input_tokens == 12 and result.output_tokens == 5
            assert json.loads(result.text)["claims"] == []
        finally:
            await provider.close()

    asyncio.run(scenario())
    url, body = captured[0]
    assert url == "https://gateway.example/v1/responses"
    assert body["model"] == "deployment-name"
    assert body["store"] is False
    assert "previous_response_id" not in body and "conversation" not in body
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["parallel_tool_calls"] is False
    assert body["text"]["format"]["strict"]
    assert all(t["strict"] for t in body["tools"])
    assert "test-secret" not in json.dumps(body)


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "incompatible_endpoint"),
        (401, "authentication"),
        (403, "permission"),
        (404, "model_unavailable"),
        (429, "rate_limit"),
        (500, "provider_error"),
    ],
)
def test_provider_errors_are_sanitized_and_never_retried(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"message": "secret-provider-error", "type": "test"}}
        )

    async def scenario():
        config = ChatConfig(api_key="test-secret")
        client = AsyncOpenAI(
            api_key="test-secret",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        provider = OpenAIProvider(config, client)
        try:
            with pytest.raises(ProviderError) as error:
                await provider.respond([], "Policy", Draft, [], "none")
            assert error.value.code == code and "secret" not in str(error.value)
        finally:
            await provider.close()

    asyncio.run(scenario())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload,code",
    [
        (response_payload(status="incomplete"), "incomplete"),
        (
            response_payload(
                output=[
                    {
                        "id": "msg_refused",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "No"}],
                    }
                ]
            ),
            "refusal",
        ),
    ],
)
def test_incomplete_and_refusal_do_not_become_answers(payload, code):
    async def scenario():
        client = AsyncOpenAI(
            api_key="test-secret",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
            ),
        )
        provider = OpenAIProvider(ChatConfig(api_key="test-secret"), client)
        try:
            with pytest.raises(ProviderError) as error:
                await provider.respond([], "Policy", Draft, [], "none")
            assert error.value.code == code
        finally:
            await provider.close()

    asyncio.run(scenario())


def test_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("sensitive transport details", request=request)

    async def scenario():
        client = AsyncOpenAI(
            api_key="test-secret",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        provider = OpenAIProvider(ChatConfig(api_key="test-secret"), client)
        try:
            with pytest.raises(ProviderError) as error:
                await provider.respond([], "Policy", Draft, [], "none")
            assert error.value.code == "provider_timeout"
            assert "sensitive" not in str(error.value)
        finally:
            await provider.close()

    asyncio.run(scenario())
