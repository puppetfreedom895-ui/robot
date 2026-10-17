"""你在 QQ 跟它说话时，它的状态也会变。

被搭话会没那么无聊，但应付人也要花点精力——这样它的状态是跟真实互动联动的，
而不是只在心跳里自己空转。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from robot.core.event import MessageEvent
from robot.life.state import clamp
from robot.life.store import LifeStore

# 被搭话一次：无聊降多少、精力掉多少
TALK_BOREDOM = 15.0
TALK_ENERGY = 1.5

# 记事件时内容截多长
EVENT_PREVIEW = 30


@dataclass
class LifePresence:
    """把对话事件写进它的生活记录。"""

    store: LifeStore
    owner: int = 0

    async def on_message(self, event: MessageEvent) -> None:
        """收到一条消息时更新状态与事件流。

        @param event: 归一化后的消息事件。
        """
        state = await self.store.load_state()
        updated = replace(
            state,
            boredom=clamp(state.boredom - TALK_BOREDOM),
            energy=clamp(state.energy - TALK_ENERGY),
        )
        await self.store.save_state(updated)

        who = event.sender_name or str(event.user_id)
        preview = event.display_text[:EVENT_PREVIEW]
        await self.store.add_event("talk", f"{who}：{preview}")
