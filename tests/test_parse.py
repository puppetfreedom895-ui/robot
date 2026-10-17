"""OneBot 事件解析（协议边界的校验行为）。"""

from __future__ import annotations

from robot.adapters.onebot.parse import parse_message_event, parse_segments

GROUP_PAYLOAD = {
    "time": 1710000000,
    "self_id": 999,
    "post_type": "message",
    "message_type": "group",
    "sub_type": "normal",
    "message_id": 42,
    "group_id": 888,
    "user_id": 111,
    "message": [
        {"type": "at", "data": {"qq": "999"}},
        {"type": "text", "data": {"text": " 在吗"}},
    ],
    "sender": {"user_id": 111, "nickname": "小明", "card": "小明同学"},
}


def test_parse_group_message() -> None:
    event = parse_message_event(GROUP_PAYLOAD)
    assert event is not None
    assert event.self_id == 999
    assert event.group_id == 888
    assert event.user_id == 111
    assert event.message_id == 42
    assert event.sender_name == "小明同学"
    assert event.mentions_me() is True
    assert event.text == "在吗"


def test_parse_private_uses_nickname_when_no_card() -> None:
    payload = {
        "self_id": 999,
        "post_type": "message",
        "message_type": "private",
        "message_id": 1,
        "user_id": 222,
        "message": "你好",
        "sender": {"nickname": "小红"},
    }
    event = parse_message_event(payload)
    assert event is not None
    assert event.message_type == "private"
    assert event.sender_name == "小红"
    assert event.display_text == "你好"


def test_non_message_post_type_ignored() -> None:
    assert parse_message_event({"post_type": "meta_event", "meta_event_type": "heartbeat"}) is None


def test_unknown_message_type_ignored() -> None:
    assert parse_message_event({"post_type": "message", "message_type": "guild"}) is None


def test_group_message_without_group_id_ignored() -> None:
    payload = dict(GROUP_PAYLOAD)
    payload.pop("group_id")
    assert parse_message_event(payload) is None


def test_missing_self_id_falls_back_to_default() -> None:
    payload = dict(GROUP_PAYLOAD)
    payload.pop("self_id")
    event = parse_message_event(payload, default_self_id=777)
    assert event is not None
    assert event.self_id == 777


def test_parse_segments_skips_invalid_items() -> None:
    segments = parse_segments([{"type": "text", "data": {"text": "a"}}, "junk", {"no_type": 1}, 5])
    assert len(segments) == 1
    assert segments[0].type == "text"


def test_parse_segments_handles_missing_data() -> None:
    segments = parse_segments([{"type": "image"}])
    assert segments[0].data == {}
