"""把配置、存储、模型、插件和平台适配器组装成一个可运行的机器人。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from robot.adapters.onebot.client import OneBotAdapter
from robot.config import Settings
from robot.core.bus import Bus, Registry
from robot.core.context import Context
from robot.core.event import MessageEvent, Segment
from robot.core.memory import MemoryManager
from robot.core.persona import load_persona
from robot.core.runtime import Runtime
from robot.llm.base import Provider
from robot.llm.openai_compat import OpenAICompatProvider
from robot.log import get_logger
from robot.plugins.base import Plugin
from robot.plugins.loader import load_plugins
from robot.store.db import Database

logger = get_logger(__name__)

IDENTITY_POLL_SECONDS = 1.0
IDENTITY_TIMEOUT_SECONDS = 60.0

# 处理链全崩时发这个，保证「发消息一定有回应」
FALLBACK_REPLY = "我这会儿有点问题，等下再问我一次？"


def _needs_fallback(context: Context, event: MessageEvent) -> bool:
    """判断要不要发兜底回复。

    条件：该回话、却因为处理函数报错而一个字都没发出去。

    @param context: 处理上下文。
    @param event: 收到的事件。
    @returns: 需要兜底为 True。
    """
    if context.handled or context.failures == 0:
        return False
    if event.is_group:
        return event.mentions_me()
    return bool(context.settings.trigger.private)


class RobotApp:
    """一个机器人实例。构造即完成装配，run() 开始收发消息。"""

    def __init__(
        self,
        settings: Settings,
        provider: Provider | None = None,
        *,
        adapter: OneBotAdapter | None = None,
        observers: list[Callable[[MessageEvent], Awaitable[None]]] | None = None,
    ) -> None:
        self.settings = settings
        self.db = Database(settings.path_of(settings.database))
        self.provider: Provider = provider or OpenAICompatProvider(settings.llm)
        self.persona = load_persona(settings.path_of(settings.chat.persona_file))
        self.memory = MemoryManager(
            db=self.db,
            provider=self.provider,
            settings=settings,
            persona=self.persona,
        )
        self.runtime = Runtime(settings=settings, memory=self.memory, llm=self.provider)
        self.registry = Registry()
        self.plugins: list[Plugin] = load_plugins(
            self.registry, settings.path_of(settings.plugins_dir)
        )
        self.runtime.state["plugins"] = self.plugins
        self.runtime.state["started_at"] = time.time()
        self.bus = Bus(self.registry)
        self.adapter = adapter or OneBotAdapter(settings.onebot, self._on_event)
        self.adapter.bind(self._on_event)
        self._observers = list(observers or [])
        self._locks: dict[str, asyncio.Lock] = {}

    async def run(self) -> None:
        """启动适配器并阻塞运行，直到被取消。"""
        logger.info(
            "机器人启动：模型=%s 模式=%s 插件=%d",
            self.settings.llm.model,
            self.settings.onebot.mode,
            len(self.plugins),
        )
        adapter_task = asyncio.create_task(self.adapter.start(), name="onebot")
        identity_task = asyncio.create_task(self._discover_identity(), name="identity")
        try:
            await adapter_task
        except asyncio.CancelledError:
            logger.info("收到停止信号，正在关闭")
            raise
        finally:
            identity_task.cancel()
            await self.shutdown()

    async def shutdown(self) -> None:
        """释放连接与资源。"""
        await self.adapter.stop()
        await self.provider.close()
        self.db.close()

    # ---- 内部 ----

    async def _on_event(self, event: MessageEvent) -> None:
        """事件入口：同一会话串行处理，避免多条回复交错。"""
        lock = self._locks.setdefault(event.session_key, asyncio.Lock())
        async with lock:
            if not self.adapter.self_id and event.self_id:
                self.adapter.self_id = event.self_id
            context = Context(event=event, bot=self.adapter, runtime=self.runtime)
            await self.bus.dispatch(context)
            if _needs_fallback(context, event):
                await self._send_fallback(event)

        for observer in self._observers:
            try:
                await observer(event)
            except Exception:  # 观察者出错不能影响回复
                logger.exception("事件观察者执行失败")

    async def _send_fallback(self, event: MessageEvent) -> None:
        """处理链全崩时也必须给个回应，不能让人干等。

        @param event: 收到的事件。
        """
        logger.warning("这次没回出正常内容，发兜底回复")
        try:
            await self.adapter.send_message(
                event, [Segment(type="text", data={"text": FALLBACK_REPLY})]
            )
        except Exception:  # 连兜底都发不出去，只能记日志
            logger.exception("兜底回复也发送失败")

    async def _discover_identity(self) -> None:
        """连上后取一次登录账号的昵称，用于人设里的自我指代。"""
        deadline = time.monotonic() + IDENTITY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(IDENTITY_POLL_SECONDS)
            try:
                data: Any = await self.adapter.call_api("get_login_info")
            except Exception:  # 还没连上就继续等
                continue
            if isinstance(data, dict) and data.get("nickname"):
                nickname = str(data["nickname"])
                self.runtime.bot_name = nickname
                self.memory.bot_name = nickname
                logger.info("登录账号：%s（%s）", nickname, data.get("user_id"))
                return
        logger.debug("未能取到登录账号昵称，使用默认称呼")
