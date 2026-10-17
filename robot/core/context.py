"""处理函数拿到的上下文对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from robot.core.bot import Bot
from robot.core.event import MessageEvent, Segment
from robot.log import get_logger

logger = get_logger(__name__)


@dataclass
class Context:
    """一次消息处理中传给插件的全部信息与能力。

    插件通过它读事件、回复消息、访问记忆和大模型。

    Attributes:
        event: 归一化后的事件。
        bot: 当前平台适配器。
        runtime: 运行期依赖（配置、记忆、模型）。
        handled: 已有处理函数响应过时为 True，后续低优先级处理函数可据此退让。
        failures: 本次处理中抛异常的处理函数个数，用于兜底判断。
    """

    event: MessageEvent
    bot: Bot
    runtime: Any
    handled: bool = False
    failures: int = 0
    _locks: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def settings(self) -> Any:
        """当前配置。

        @returns: Settings 对象。
        """
        return self.runtime.settings

    @property
    def memory(self) -> Any:
        """会话记忆管理器。

        @returns: MemoryManager 对象。
        """
        return self.runtime.memory

    @property
    def session_key(self) -> str:
        """会话唯一键。

        @returns: 形如 "group:123"。
        """
        return self.event.session_key

    async def reply(self, text: str) -> None:
        """以纯文本回复当前会话。

        @param text: 要发送的文本，为空则跳过。
        """
        if not text.strip():
            return
        await self.send([Segment(type="text", data={"text": text})])
        self.handled = True

    async def send(self, segments: list[Segment]) -> None:
        """发送任意消息段组合。

        @param segments: OneBot 消息段列表。
        """
        await self.bot.send_message(self.event, segments)

    async def call(self, action: str, params: dict[str, Any] | None = None) -> Any:
        """调用平台原生接口。

        @param action: OneBot action 名。
        @param params: 参数。
        @returns: 平台返回的数据。
        """
        return await self.bot.call_api(action, params)

    async def get_member_name(self, user_id: int) -> str:
        """尽量取到群名片/昵称，取不到就返回 QQ 号。

        @param user_id: 目标 QQ 号。
        @returns: 显示名。
        """
        try:
            if self.event.is_group:
                data = await self.call(
                    "get_group_member_info",
                    {"group_id": self.event.chat_id, "user_id": user_id, "no_cache": True},
                )
            else:
                data = await self.call("get_stranger_info", {"user_id": user_id})
        except Exception as exc:  # 拿不到昵称不影响主流程
            logger.debug("获取昵称失败 %s: %s", user_id, exc)
            return str(user_id)
        if isinstance(data, dict):
            return str(data.get("card") or data.get("nickname") or user_id)
        return str(user_id)
