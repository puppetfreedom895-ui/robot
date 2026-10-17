"""离线假模型：不花钱、不联网，用于本地调试与测试。"""

from __future__ import annotations

from collections.abc import Sequence

from robot.llm.base import ChatMessage, Provider


class ScriptedProvider(Provider):
    """按预设脚本依次返回回复，并记录收到的全部请求。

    脚本用完后重复最后一条，方便长对话调试。
    """

    def __init__(self, replies: Sequence[str] = ("收到",), delay: float = 0.0) -> None:
        if not replies:
            raise ValueError("至少需要一条预设回复")
        self._replies = list(replies)
        self._delay = delay
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        """返回脚本里的下一条回复。

        @param messages: 对话消息，原样记录下来供断言。
        @returns: 预设文本。
        """
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self._replies) - 1)
        return self._replies[index]


class EchoProvider(Provider):
    """把用户最后一句话原样回显，适合验证链路是否打通。"""

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        """回显最后一条非 system 消息。

        @param messages: 对话消息。
        @returns: 最后一条用户消息内容，没有则返回占位文本。
        """
        self.calls.append(list(messages))
        for message in reversed(messages):
            if message.role == "user":
                return f"我听到你说：{message.content}"
        return "我这边什么都没收到"
