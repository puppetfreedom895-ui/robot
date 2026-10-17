"""事件模型的归一化行为。"""

from __future__ import annotations

from robot.core.event import MessageEvent, Segment
from tests.conftest import build_event


def test_private_session_key_and_chat_id() -> None:
    event = build_event(user_id=42)
    assert event.session_key == "private:42"
    assert event.chat_id == 42
    assert event.is_group is False


def test_group_session_key_and_chat_id() -> None:
    event = build_event(message_type="group", group_id=888, user_id=42)
    assert event.session_key == "group:888"
    assert event.chat_id == 888
    assert event.is_group is True


def test_text_only_joins_text_segments() -> None:
    event = MessageEvent(
        self_id=1,
        message_type="group",
        user_id=2,
        message_id=3,
        segments=(
            Segment(type="text", data={"text": "你好"}),
            Segment(type="image", data={"file": "a.jpg"}),
            Segment(type="text", data={"text": "看这个"}),
        ),
        raw={},
        group_id=9,
    )
    assert event.text == "你好看这个"


def test_display_text_marks_media_and_mentions() -> None:
    event = MessageEvent(
        self_id=1,
        message_type="group",
        user_id=2,
        message_id=3,
        segments=(
            Segment(type="at", data={"qq": "1"}),
            Segment(type="text", data={"text": " 帮我看下"}),
            Segment(type="image", data={"file": "a.jpg"}),
            Segment(type="record", data={"file": "a.amr"}),
        ),
        raw={},
        group_id=9,
    )
    assert event.display_text == "@你  帮我看下[图片][语音]"
    assert event.has_image is True


def test_mentions_me_detects_self() -> None:
    event = MessageEvent(
        self_id=1,
        message_type="group",
        user_id=2,
        message_id=3,
        segments=(
            Segment(type="at", data={"qq": "1"}),
            Segment(type="text", data={"text": "在吗"}),
        ),
        raw={},
        group_id=9,
    )
    assert event.mentions_me() is True
    assert event.mentions(2) is False


def test_reply_segment_is_dropped_from_display() -> None:
    event = MessageEvent(
        self_id=1,
        message_type="group",
        user_id=2,
        message_id=3,
        segments=(
            Segment(type="reply", data={"id": "77"}),
            Segment(type="text", data={"text": "接着说"}),
        ),
        raw={},
        group_id=9,
    )
    assert event.display_text == "接着说"
