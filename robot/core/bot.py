"""平台适配器需要实现的接口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from robot.core.event import MessageEvent, Segment

EventHandler = Callable[[MessageEvent], Awaitable[None]]


@runtime_checkable
class Bot(Protocol):
    """机器人对外的发送与调用能力。

    核心层只依赖这个协议，具体由各平台适配器实现（当前是 OneBot v11）。
    """

    async def send_message(self, event: MessageEvent, segments: list[Segment]) -> None:
        """把消息发回事件来源的会话。"""
        ...

    async def call_api(self, action: str, params: dict[str, Any] | None = None) -> Any:
        """调用平台原生接口，例如 get_group_member_info。"""
        ...
