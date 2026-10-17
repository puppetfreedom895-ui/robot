"""模型提供方接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """一条送给模型的消息。"""

    role: Role
    content: str

    def to_payload(self) -> dict[str, str]:
        """转成 OpenAI 兼容的消息结构。

        @returns: {"role": ..., "content": ...}。
        """
        return {"role": self.role, "content": self.content}


class LLMError(RuntimeError):
    """模型调用失败。消息内容面向使用者，可直接展示或打日志。"""


class Provider(ABC):
    """大模型提供方。实现这一个方法即可接入任意服务。"""

    @abstractmethod
    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        """生成一次回复。

        @param messages: 完整对话，含 system。
        @returns: 模型输出的纯文本。
        @raises LLMError: 调用失败且无法恢复。
        """
        raise NotImplementedError

    async def close(self) -> None:
        """释放底层连接。默认无事可做。"""
        return None
