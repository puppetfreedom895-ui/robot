"""与平台无关的消息事件模型。

OneBot 的原始事件在这里被归一化：插件和对话逻辑只认 :class:`MessageEvent`，
换平台（QQ 频道、Telegram、微信）时只需新写一个适配器，核心代码不用动。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MessageType = Literal["private", "group"]

# OneBot 消息段 → 让模型能读懂的占位符。
_SEGMENT_PLACEHOLDERS: dict[str, str] = {
    "image": "[图片]",
    "face": "[表情]",
    "mface": "[表情]",
    "record": "[语音]",
    "video": "[视频]",
    "file": "[文件]",
    "json": "[卡片消息]",
    "xml": "[卡片消息]",
    "forward": "[聊天记录]",
    "markdown": "[富文本]",
}


@dataclass(frozen=True, slots=True)
class Segment:
    """一段 OneBot 消息段，例如 text、at、image。"""

    type: str
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MessageEvent:
    """归一化后的消息事件。"""

    self_id: int
    message_type: MessageType
    user_id: int
    message_id: int
    segments: tuple[Segment, ...]
    raw: dict[str, Any]
    sender_name: str = ""
    group_id: int | None = None
    time: int = 0
    platform: str = "qq"

    @property
    def is_group(self) -> bool:
        """是否群消息。

        @returns: 群消息为 True。
        """
        return self.message_type == "group"

    @property
    def chat_id(self) -> int:
        """回复目标 id：群消息是 group_id，私聊是 user_id。

        @returns: 目标 id。
        """
        if self.is_group:
            if self.group_id is None:
                raise ValueError("群消息缺少 group_id，无法确定回复目标")
            return self.group_id
        return self.user_id

    @property
    def session_key(self) -> str:
        """会话唯一键，用于隔离记忆与并发锁。

        @returns: 形如 "group:123456" 或 "private:789"。
        """
        return f"{self.message_type}:{self.chat_id}"

    @property
    def text(self) -> str:
        """只取纯文本段，用于命令匹配。

        @returns: 拼接后的文本，已去掉首尾空白。
        """
        parts = [str(seg.data.get("text", "")) for seg in self.segments if seg.type == "text"]
        return "".join(parts).strip()

    @property
    def display_text(self) -> str:
        """给模型看的文本：文本原样，其余消息段转成可读占位符。

        @returns: 首尾去空白后的展示文本。
        """
        parts: list[str] = []
        for seg in self.segments:
            if seg.type == "text":
                parts.append(str(seg.data.get("text", "")))
            elif seg.type == "at":
                qq = str(seg.data.get("qq", ""))
                parts.append("@你 " if qq == str(self.self_id) else f"@{qq} ")
            elif seg.type == "reply":
                continue
            else:
                parts.append(_SEGMENT_PLACEHOLDERS.get(seg.type, f"[{seg.type}]"))
        return "".join(parts).strip()

    @property
    def has_image(self) -> bool:
        """消息里是否带图。

        @returns: 含 image 段为 True。
        """
        return any(seg.type == "image" for seg in self.segments)

    def mentions(self, user_id: int) -> bool:
        """判断是否 @ 了指定账号。

        @param user_id: 被 @ 的 QQ 号。
        @returns: 命中为 True。
        """
        return any(
            seg.type == "at" and str(seg.data.get("qq", "")) == str(user_id)
            for seg in self.segments
        )

    def mentions_me(self) -> bool:
        """判断是否 @ 了机器人自己。

        @returns: 命中为 True。
        """
        return self.mentions(self.self_id)
