"""测试共用的构造器。"""

from __future__ import annotations

from typing import Any

import pytest

from robot.config import Settings
from robot.core.event import MessageEvent, Segment


class FakeBot:
    """记录发送内容的假适配器，实现 Bot 协议。"""

    def __init__(self, self_id: int = 999) -> None:
        self.self_id = self_id
        self.sent: list[list[Segment]] = []
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def send_message(self, event: MessageEvent, segments: list[Segment]) -> None:
        self.sent.append(list(segments))

    async def call_api(self, action: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((action, params))
        return {}

    @property
    def texts(self) -> list[str]:
        """已发送消息的纯文本列表。

        @returns: 每个消息段的 text 字段。
        """
        return ["".join(str(seg.data.get("text", "")) for seg in batch) for batch in self.sent]


def build_event(
    *,
    text: str = "你好",
    user_id: int = 111,
    self_id: int = 999,
    message_type: str = "private",
    group_id: int | None = None,
    sender_name: str = "小明",
    extra: tuple[Segment, ...] = (),
) -> MessageEvent:
    """造一条消息事件，默认私聊纯文本。

    @param text: 文本内容。
    @param user_id: 发送者。
    @param self_id: 机器人自己。
    @param message_type: "private" 或 "group"。
    @param group_id: 群号。
    @param sender_name: 显示名。
    @param extra: 追加的消息段。
    @returns: 事件对象。
    """
    segments: list[Segment] = []
    if text:
        segments.append(Segment(type="text", data={"text": text}))
    segments.extend(extra)
    return MessageEvent(
        self_id=self_id,
        message_type="group" if message_type == "group" else "private",
        user_id=user_id,
        message_id=1,
        segments=tuple(segments),
        raw={},
        sender_name=sender_name,
        group_id=group_id,
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    """一份带临时目录的最小配置。"""
    return Settings(base_dir=tmp_path)
