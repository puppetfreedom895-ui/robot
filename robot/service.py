"""把 QQ、心跳和手机执行器装进一个常驻进程。

一个进程干三件事：
1. 收 QQ 消息并回话（RobotApp + 插件）
2. 每 N 分钟醒一次（LifeLoop 心跳）
3. 决定做事时调 DSH 去操作手机（DshRunner）

跑起来：``python -m robot live``
"""

from __future__ import annotations

import asyncio

from robot.adapters.onebot.client import OneBotAdapter
from robot.app import RobotApp
from robot.config import Settings
from robot.life.brain import Brain, LLMBrain, OfflineBrain
from robot.life.loop import LifeLoop, TickResult
from robot.life.presence import LifePresence
from robot.life.qq import QQNotifier
from robot.life.runner import DemoRunner, DshRunner, Runner, parse_command
from robot.life.store import LifeStore
from robot.llm.base import Provider
from robot.llm.openai_compat import OpenAICompatProvider
from robot.log import get_logger
from robot.web.dashboard import Dashboard

logger = get_logger(__name__)

# 心跳只要一个 JSON，输出压到最小
HEARTBEAT_MAX_TOKENS = 200


class LifeService:
    """常驻的完整机器人。"""

    def __init__(
        self,
        settings: Settings,
        *,
        provider: Provider | None = None,
        adapter: OneBotAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.store = LifeStore(
            settings.path_of(settings.life.database), timezone=settings.life.timezone
        )
        self.presence = LifePresence(self.store, owner=settings.life.owner)

        self.app = RobotApp(
            settings,
            provider=provider,
            adapter=adapter,
            observers=[self.presence.on_message],
        )
        self.notifier = QQNotifier(self.app.adapter, settings.life.owner)

        self._brain_provider: Provider | None = None
        self.brain: Brain = self._build_brain()
        self.runner: Runner = self._build_runner()
        self.loop = LifeLoop(
            store=self.store,
            brain=self.brain,
            runner=self.runner,
            notifier=self.notifier,
            timezone=settings.life.timezone,
            quiet_hours=(settings.life.quiet_start, settings.life.quiet_end),
            daily_budget_tokens=settings.life.daily_budget_tokens,
        )
        self.dashboard: Dashboard | None = (
            Dashboard(
                self.store,
                host=settings.web.host,
                port=settings.web.port,
                token=settings.web.token,
                screens_dir=settings.path_of(settings.web.screens_dir),
            )
            if settings.web.enabled
            else None
        )

    def _build_brain(self) -> Brain:
        """按配置选大脑。

        @returns: 大脑实现。
        """
        if self.settings.life.brain != "model":
            return OfflineBrain()

        llm = self.settings.llm.model_copy(update={"max_tokens": HEARTBEAT_MAX_TOKENS})
        self._brain_provider = OpenAICompatProvider(llm)
        return LLMBrain(self._brain_provider)

    def _build_runner(self) -> Runner:
        """按配置选执行器。

        @returns: 执行器实现。
        """
        command = parse_command(self.settings.life.dsh_command)
        if not command:
            logger.warning("没配置 [life] dsh_command，动作用占位执行器，不会真的操作手机")
            return DemoRunner()
        return DshRunner(command, timeout=self.settings.life.dsh_timeout)

    async def run(self) -> None:
        """启动 QQ 连接与心跳，一直跑到被取消。"""
        logger.info(
            "常驻启动：心跳 %g 分钟｜大脑=%s｜执行=%s｜主人=%s",
            self.settings.life.heartbeat_minutes,
            type(self.brain).__name__,
            type(self.runner).__name__,
            self.settings.life.owner or "未配置",
        )
        heartbeat = asyncio.create_task(self._heartbeat(), name="life")
        if self.dashboard is not None:
            self.dashboard.start()
        try:
            await self.app.run()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            await self.close()

    async def close(self) -> None:
        """释放心跳与管理台的资源。"""
        if self.dashboard is not None:
            self.dashboard.stop()
        if self._brain_provider is not None:
            await self._brain_provider.close()
        self.store.close()

    async def _heartbeat(self) -> None:
        """按固定间隔醒一次，永远不停（除非被取消）。"""
        interval = self.settings.life.heartbeat_minutes * 60
        while True:
            try:
                result = await self.loop.tick()
                _log_tick(result)
            except asyncio.CancelledError:
                raise
            except Exception:  # 单次心跳出错不该结束整条命
                logger.exception("心跳执行失败")
            await asyncio.sleep(interval)


def _log_tick(result: TickResult) -> None:
    """把一次心跳写进日志。

    @param result: 心跳结果。
    """
    if result.slept:
        logger.debug("睡觉中")
    elif result.blocked:
        logger.info("拦住一个越界念头：%s", result.intent)
    elif result.acted:
        logger.info("它去做了：%s", result.intent)
    else:
        logger.debug("这一轮没动：%s", result.narration)
