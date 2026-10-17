"""OneBot v11 事件解析（协议边界，做完整校验）。"""

from __future__ import annotations

from typing import Any

from robot.core.event import MessageEvent, Segment
from robot.log import get_logger

logger = get_logger(__name__)


def parse_segments(raw: Any) -> tuple[Segment, ...]:
    """把 OneBot 的 message 字段转成消息段元组。

    支持数组格式；字符串格式（CQ 码）只当作纯文本处理，配置 NapCat 时请选 array。

    @param raw: 原始 message 字段。
    @returns: 消息段元组，无法识别的内容会被丢弃。
    """
    if isinstance(raw, str):
        return (Segment(type="text", data={"text": raw}),)
    if not isinstance(raw, list):
        return ()

    segments: list[Segment] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        seg_type = item.get("type")
        if not isinstance(seg_type, str):
            continue
        data = item.get("data")
        segments.append(Segment(type=seg_type, data=dict(data) if isinstance(data, dict) else {}))
    return tuple(segments)


def parse_message_event(
    payload: dict[str, Any], *, default_self_id: int = 0
) -> MessageEvent | None:
    """把 OneBot 上报事件解析成 MessageEvent。

    @param payload: WebSocket 收到的一帧 JSON。
    @param default_self_id: 事件里没带 self_id 时使用。
    @returns: 消息事件；非消息事件返回 None。
    """
    if payload.get("post_type") != "message":
        return None

    message_type = payload.get("message_type")
    if message_type not in ("private", "group"):
        return None

    self_id = _as_int(payload.get("self_id"), default_self_id)
    user_id = _as_int(payload.get("user_id"), 0)
    message_id = _as_int(payload.get("message_id"), 0)
    group_id = _as_int(payload.get("group_id"), 0) if message_type == "group" else None

    if user_id == 0 or (message_type == "group" and not group_id):
        logger.debug("忽略缺少必要字段的消息事件：%s", payload)
        return None

    sender = payload.get("sender")
    sender = sender if isinstance(sender, dict) else {}
    sender_name = str(
        sender.get("card") or sender.get("nickname") or sender.get("user_id") or user_id
    )

    return MessageEvent(
        self_id=self_id,
        message_type="group" if message_type == "group" else "private",
        user_id=user_id,
        message_id=message_id,
        segments=parse_segments(payload.get("message")),
        raw=payload,
        sender_name=sender_name,
        group_id=group_id,
        time=_as_int(payload.get("time"), 0),
    )


def _as_int(value: Any, default: int) -> int:
    """把协议里的数字（可能是字符串）安全转成 int。

    @param value: 原始值。
    @param default: 转换失败时的返回值。
    @returns: 整数。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
