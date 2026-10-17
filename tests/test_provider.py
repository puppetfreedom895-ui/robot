"""OpenAI 兼容提供方：请求体、返回解析与错误处理。"""

from __future__ import annotations

import json

import httpx
import pytest

from robot.config import LLMSettings
from robot.llm.base import ChatMessage, LLMError
from robot.llm.openai_compat import OpenAICompatProvider

MESSAGES = [ChatMessage("system", "你是网友"), ChatMessage("user", "小明：在吗")]


def make_provider(handler, *, max_retries: int = 0, api_key: str = "test-key"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = LLMSettings(api_key=api_key, model="test-model", max_retries=max_retries)
    return OpenAICompatProvider(settings, client=client)


def test_payload_contains_model_and_messages() -> None:
    provider = make_provider(lambda request: httpx.Response(200, json={}))
    payload = provider.build_payload(MESSAGES)
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": "你是网友"}


async def test_complete_strips_content() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": " 在的 "}}]})

    provider = make_provider(handler)
    assert await provider.complete(MESSAGES) == "在的"
    assert seen[0]["messages"][1]["content"] == "小明：在吗"


async def test_missing_api_key_raises_before_request() -> None:
    provider = make_provider(lambda request: httpx.Response(200, json={}), api_key="")
    with pytest.raises(LLMError, match="API Key"):
        await provider.complete(MESSAGES)


async def test_client_error_is_reported() -> None:
    provider = make_provider(lambda request: httpx.Response(400, text="bad request"))
    with pytest.raises(LLMError, match="400"):
        await provider.complete(MESSAGES)


async def test_malformed_body_raises() -> None:
    provider = make_provider(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMError, match="格式异常"):
        await provider.complete(MESSAGES)


async def test_empty_content_raises() -> None:
    provider = make_provider(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})
    )
    with pytest.raises(LLMError, match="空内容"):
        await provider.complete(MESSAGES)


async def test_retries_on_rate_limit_then_succeeds(monkeypatch) -> None:
    import asyncio

    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "好了"}}]})

    provider = make_provider(handler, max_retries=1)
    assert await provider.complete(MESSAGES) == "好了"
    assert len(attempts) == 2


async def test_gives_up_after_retries(monkeypatch) -> None:
    import asyncio

    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    provider = make_provider(lambda request: httpx.Response(503, text="down"), max_retries=1)
    with pytest.raises(LLMError, match="503"):
        await provider.complete(MESSAGES)
