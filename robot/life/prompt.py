"""唤醒提示词：每次醒来它看到的东西。

这段文字每次都进上下文，所以必须短——目标是一百多个 token 说完
「我是谁、我现在什么状态、我最近惦记什么」，剩下的留给模型自己想。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from robot.life.state import LifeState

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

DECISION_FORMAT = (
    "只回一个 JSON，别的话都不要：\n"
    '{"act": false}\n'
    "或\n"
    '{"act": true, "intent": "想做的事，一句话", '
    '"say": "想对主人说的话，没有就空着", "mood": "现在的心情"}'
)


def build_wake_prompt(
    state: LifeState,
    *,
    now: datetime,
    events: Sequence[str] = (),
    goals: Sequence[str] = (),
) -> str:
    """拼出一次唤醒的提示词。

    @param state: 当前自我状态。
    @param now: 现在的时间。
    @param events: 最近做过的事。
    @param goals: 它自己惦记的事。
    @returns: 提示词文本。
    """
    lines = [
        f"你是{state.name}，一个普通网友，现在自己拿着手机待着。",
        f"现在是 {WEEKDAYS[now.weekday()]} {now:%H:%M}。",
        f"你的状态：{state.describe()}。",
    ]

    if goals:
        lines.append("你最近惦记：" + "；".join(goals[:3]))

    if events:
        lines.append("刚才做的事：")
        lines.extend(f"  {event}" for event in events[:4])

    lines.append("没人叫你，你现在想干点什么？不想动就接着待着。")
    lines.append(DECISION_FORMAT)
    return "\n".join(lines)
