"""决策：把模型的输出变成一个可执行的选择。

模型输出是外部输入，必须在边界上校验——宁可当作"不想动"，
也不能拿一段没解析出来的文字去驱动真实操作。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from robot.life.state import LifeState
from robot.llm.base import ChatMessage, LLMError, Provider

# 心跳只该产出一个 JSON，多一个字都是在烧钱
SYSTEM_HINT = "你只输出 JSON，不要任何解释。"


@dataclass(frozen=True, slots=True)
class Decision:
    """它这一轮的决定。"""

    act: bool
    intent: str = ""
    say: str = ""
    mood: str = ""


class Brain(Protocol):
    """大脑接口：DSH、假大脑都实现这一个方法。"""

    async def decide(self, prompt: str, state: LifeState) -> Decision:
        """根据唤醒提示词做决定。"""
        ...


def parse_decision(text: str) -> Decision:
    """从模型返回的文本里解析决定。

    @param text: 模型原始输出。
    @returns: 决定；解析不出来时返回「不想动」。
    """
    payload = _extract_json(text)
    if payload is None:
        return Decision(act=False)

    act = payload.get("act")
    if isinstance(act, str):
        act = act.strip().lower() in ("true", "yes", "1")
    if not isinstance(act, bool):
        return Decision(act=False)

    return Decision(
        act=act,
        intent=_clean(payload.get("intent")),
        say=_clean(payload.get("say")),
        mood=_clean(payload.get("mood")),
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    """从可能夹着解释文字的输出里抠出第一个 JSON 对象。

    @param text: 模型输出。
    @returns: 解析后的字典，失败返回 None。
    """
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _clean(value: Any, limit: int = 80) -> str:
    """把字段规整成短字符串。

    @param value: 原始字段。
    @param limit: 最大长度。
    @returns: 干净字符串。
    """
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


class ScriptedBrain:
    """按脚本返回决定，用于测试和演示。"""

    def __init__(self, decisions: Sequence[Decision]) -> None:
        if not decisions:
            raise ValueError("至少需要一个决定")
        self._decisions = list(decisions)
        self.calls = 0

    async def decide(self, prompt: str, state: LifeState) -> Decision:
        """返回脚本里的下一条。

        @param prompt: 唤醒提示词（这里不看）。
        @param state: 当前状态（这里不看）。
        @returns: 预设决定。
        """
        decision = self._decisions[min(self.calls, len(self._decisions) - 1)]
        self.calls += 1
        return decision


class OfflineBrain:
    """没有模型时用的规则版大脑。

    它按状态决定：太累就歇着，够无聊就找点事做。用于本地演示，
    和真正的模型相比只是不会说人话。
    """

    def __init__(self, intents: Sequence[str] | None = None) -> None:
        self._intents = list(intents or ("刷会儿手机", "随便逛逛", "看下有没有新消息"))
        self._cursor = 0
        self.calls = 0

    async def decide(self, prompt: str, state: LifeState) -> Decision:
        """按精力与无聊度给一个决定。

        @param prompt: 唤醒提示词（规则版不看）。
        @param state: 当前状态。
        @returns: 决定。
        """
        self.calls += 1
        if state.energy < 40:
            return Decision(act=False)
        if state.boredom < 60:
            return Decision(act=False)

        intent = self._intents[self._cursor % len(self._intents)]
        self._cursor += 1
        return Decision(act=True, intent=intent, mood="有点无聊")


class LLMBrain:
    """用一次普通对话做决定。

    刻意不带工具、不带历史：心跳每次只有一两百 token，
    真要动手才交给 DSH。这是整个成本模型的地基。
    """

    def __init__(self, provider: Provider, *, system: str = SYSTEM_HINT) -> None:
        self._provider = provider
        self._system = system
        self.calls = 0

    async def decide(self, prompt: str, state: LifeState) -> Decision:
        """问一次模型，拿到决定。

        @param prompt: 唤醒提示词。
        @param state: 当前状态（模型自己会在 prompt 里看到）。
        @returns: 决定；模型出错时当作「不想动」。
        """
        self.calls += 1
        try:
            text = await self._provider.complete(
                [ChatMessage("system", self._system), ChatMessage("user", prompt)]
            )
        except LLMError:
            return Decision(act=False)
        return parse_decision(text)
