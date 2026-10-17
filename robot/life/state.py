"""自我状态：它此刻是谁、有多想动。

状态是"它像个人"的底层——同样是收到一条消息，无聊度高和刚睡醒的反应不一样。
每次醒来先读状态，状态决定它想干什么。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# 每做一件事、每闲一次，状态怎么变
ACTION_ENERGY = 8.0
ACTION_BOREDOM = 25.0
REST_ENERGY = 4.0
REST_BOREDOM = 5.0

STATE_MAX = 100.0


def clamp(value: float, low: float = 0.0, high: float = STATE_MAX) -> float:
    """把数值夹到合法范围内。

    @param value: 原值。
    @param low: 下限。
    @param high: 上限。
    @returns: 夹紧后的值。
    """
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class LifeState:
    """一次唤醒时它读到的自己。"""

    name: str = "小七"
    energy: float = 80.0
    mood: str = "还行"
    boredom: float = 30.0
    focus: str = ""
    updated_at: float = 0.0

    def acted(self, intent: str = "") -> LifeState:
        """做完一件事之后：更累，也没那么无聊了。

        @param intent: 刚做的事，会变成「最近在琢磨」的线索。
        @returns: 新状态。
        """
        return replace(
            self,
            energy=clamp(self.energy - ACTION_ENERGY),
            boredom=clamp(self.boredom - ACTION_BOREDOM),
            focus=(intent[:20] if intent else self.focus),
        )

    def rested(self, energy_gain: float = REST_ENERGY) -> LifeState:
        """闲下来或睡了一觉之后：回血，但更无聊。

        @param energy_gain: 回复的精力。
        @returns: 新状态。
        """
        return replace(
            self,
            energy=clamp(self.energy + energy_gain),
            boredom=clamp(self.boredom + REST_BOREDOM),
        )

    def describe(self) -> str:
        """给模型看的自述，尽量短。

        @returns: 一行状态描述。
        """
        parts = [
            f"精力 {self.energy:.0f}/100",
            f"无聊 {self.boredom:.0f}/100",
            f"心情 {self.mood}",
        ]
        if self.focus:
            parts.append(f"最近在琢磨 {self.focus}")
        return "，".join(parts)
