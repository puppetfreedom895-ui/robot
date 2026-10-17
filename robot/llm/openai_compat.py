"""OpenAI 兼容接口实现：DeepSeek、OpenAI、通义、本地 vLLM/Ollama 都能用。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from robot.config import LLMSettings
from robot.llm.base import ChatMessage, LLMError, Provider
from robot.log import get_logger

logger = get_logger(__name__)

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class OpenAICompatProvider(Provider):
    """通过 /chat/completions 调用模型。

    构造时可注入 httpx.AsyncClient，测试里传 MockTransport 即可离线验证请求体。
    """

    def __init__(
        self,
        settings: LLMSettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout),
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def endpoint(self) -> str:
        """补全后的 chat/completions 地址。

        @returns: 完整 URL。
        """
        return f"{self._settings.base_url.rstrip('/')}/chat/completions"

    def build_payload(self, messages: Sequence[ChatMessage]) -> dict[str, object]:
        """组装请求体，便于测试直接断言。

        @param messages: 对话消息。
        @returns: 请求体字典。
        """
        return {
            "model": self._settings.model,
            "messages": [message.to_payload() for message in messages],
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
            "stream": False,
        }

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        """调用模型取一次回复，遇到限流或 5xx 会退避重试。

        @param messages: 对话消息。
        @returns: 模型文本。
        @raises LLMError: 重试后仍失败，或返回体不符合预期。
        """
        if not self._settings.api_key:
            raise LLMError(
                "没有配置 API Key：请在 config.toml 的 [llm] api_key "
                "或环境变量 ROBOT_API_KEY 里填写"
            )

        payload = self.build_payload(messages)
        last_error = "未知错误"

        for attempt in range(self._settings.max_retries + 1):
            try:
                response = await self._client.post(
                    self.endpoint, json=payload, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                last_error = f"网络错误：{exc}"
                logger.warning("模型请求失败（第 %d 次）：%s", attempt + 1, exc)
            else:
                if response.status_code in _RETRY_STATUS:
                    last_error = f"服务返回 {response.status_code}"
                    logger.warning("模型限流或服务异常（第 %d 次）：%s", attempt + 1, last_error)
                elif response.status_code >= 400:
                    raise LLMError(f"模型返回 {response.status_code}：{response.text[:300]}")
                else:
                    return self._extract(response.json())

            if attempt < self._settings.max_retries:
                await asyncio.sleep(min(2.0**attempt, 8.0))

        raise LLMError(last_error)

    @staticmethod
    def _extract(data: object) -> str:
        """从返回体里取出文本内容。

        @param data: 解析后的 JSON。
        @returns: 去空白后的模型文本。
        @raises LLMError: 结构不符合 OpenAI 兼容格式，或内容为空。
        """
        try:
            choices = data["choices"]  # type: ignore[index]
            content = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"模型返回体格式异常：{str(data)[:300]}") from exc

        text = str(content or "").strip()
        if not text:
            raise LLMError("模型返回了空内容")
        return text

    async def close(self) -> None:
        """关闭自建的 HTTP 客户端。"""
        if self._owns_client:
            await self._client.aclose()
