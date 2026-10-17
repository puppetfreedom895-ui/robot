"""心跳循环：醒 → 读状态 → 决定 → 过护栏 → 做 → 记下来。

这是"它不是被叫才动"的地方。没人理它的时候，它自己在跑这个循环。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from robot.life import policy
from robot.life.brain import Brain
from robot.life.clock import resolve_zone, to_local
from robot.life.prompt import build_wake_prompt
from robot.life.runner import Runner
from robot.life.state import LifeState
from robot.life.store import LifeStore

# 心跳提示词大约这么多 token（估算，用于记账）
PROMPT_OVERHEAD_TOKENS = 60


class Notifier(Protocol):
    """它主动说话时用的出口。现在接控制台，之后接 QQ。"""

    async def notify(self, text: str) -> None:
        """把一句话发出去。"""
        ...


@dataclass(frozen=True, slots=True)
class TickResult:
    """一次心跳的结果，用于日志和演示。"""

    acted: bool
    intent: str = ""
    narration: str = ""
    say: str = ""
    slept: bool = False
    blocked: str = ""


def estimate_tokens(text: str) -> int:
    """粗估一段中文文本的 token 数（1 字约 1 token）。

    @param text: 文本。
    @returns: 估算值。
    """
    return max(1, len(text))


def in_quiet_hours(now: datetime, quiet_hours: tuple[int, int]) -> bool:
    """判断此刻是否在免打扰时段。

    @param now: 当前时间。
    @param quiet_hours: (开始小时, 结束小时)，支持跨零点。
    @returns: 在时段内为 True。
    """
    start, end = quiet_hours
    hour = now.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class LifeLoop:
    """一次心跳的全部逻辑。"""

    def __init__(
        self,
        *,
        store: LifeStore,
        brain: Brain,
        runner: Runner,
        notifier: Notifier | None = None,
        clock: Callable[[], float] = time.time,
        timezone: str = "",
        quiet_hours: tuple[int, int] = (1, 7),
        min_energy: float = 20.0,
        daily_budget_tokens: int = 0,
    ) -> None:
        self._store = store
        self._brain = brain
        self._runner = runner
        self._notifier = notifier
        self._clock = clock
        self._zone = resolve_zone(timezone)
        self._quiet_hours = quiet_hours
        self._min_energy = min_energy
        self._budget = daily_budget_tokens

    async def tick(self) -> TickResult:
        """醒一次，做一次判断。

        @returns: 本轮结果。
        """
        now = to_local(self._clock(), self._zone)
        day = now.strftime("%Y-%m-%d")
        state = await self._store.load_state()

        # 夜里和没电的时候不思考，省掉整次模型调用
        if in_quiet_hours(now, self._quiet_hours):
            slept = state.rested(6.0)
            await self._store.save_state(slept)
            await self._store.add_event("sleep", "夜里在睡")
            return TickResult(acted=False, slept=True, narration="夜里在睡")

        if state.energy < self._min_energy:
            rested = state.rested(5.0)
            await self._store.save_state(rested)
            await self._store.add_event("idle", "太累了，歇着")
            return TickResult(acted=False, narration="太累了，歇着")

        used = await self._store.tokens_on(day)
        if self._budget and used >= self._budget:
            rested = state.rested(2.0)
            await self._store.save_state(rested)
            return TickResult(acted=False, narration="今天额度用完了，先待着")

        prompt = build_wake_prompt(
            state,
            now=now,
            events=await self._store.recent_events(4),
            goals=await self._store.open_goals(3),
        )
        decision = await self._brain.decide(prompt, state)
        await self._store.note_tokens(day, estimate_tokens(prompt) + PROMPT_OVERHEAD_TOKENS)

        if not decision.act:
            rested = state.rested(2.0)
            await self._store.save_state(rested)
            await self._store.add_event("idle", "什么也没干")
            return TickResult(acted=False, narration="什么也没干")

        try:
            policy.check(decision.intent)
        except policy.PolicyBlocked as exc:
            await self._store.add_event("blocked", decision.intent)
            message = f"我想「{decision.intent}」，但这个得你点头。"
            if self._notifier is not None:
                await self._notifier.notify(message)
            return TickResult(acted=False, intent=decision.intent, blocked=str(exc), say=message)

        narration = await self._runner.run(decision.intent)

        acted = state.acted(decision.intent)
        if decision.mood:
            acted = replace(acted, mood=decision.mood)
        await self._store.save_state(acted)
        await self._store.add_event("act", decision.intent)
        await self._store.add_diary(day, f"{now:%H:%M} {decision.intent}")

        if decision.say and self._notifier is not None:
            await self._notifier.notify(decision.say)

        return TickResult(
            acted=True,
            intent=decision.intent,
            narration=narration,
            say=decision.say,
        )

    async def run(self, *, ticks: int = 0, interval_seconds: float = 600.0) -> None:
        """一直醒着，按间隔跑心跳。

        @param ticks: 跑多少次，0 表示不停。
        @param interval_seconds: 两次心跳的间隔。
        """
        count = 0
        while ticks <= 0 or count < ticks:
            await self.tick()
            count += 1
            if ticks > 0 and count >= ticks:
                break
            await asyncio.sleep(interval_seconds)


def describe(state: LifeState) -> str:
    """给日志用的状态摘要。

    @param state: 自我状态。
    @returns: 一行文本。
    """
    return f"{state.describe()}｜{state.updated_at:.0f}"
