"""触发规则：该不该接话。"""

from __future__ import annotations

from robot.config import Settings, TriggerSettings
from robot.core.event import Segment
from robot.plugins.builtin.chat import evaluate_trigger
from tests.conftest import build_event


def make_settings(**trigger: object) -> Settings:
    return Settings(trigger=TriggerSettings(**trigger))


def test_private_replies_when_enabled() -> None:
    event = build_event(text="在吗")
    assert evaluate_trigger(event, make_settings()) == "在吗"


def test_private_silent_when_disabled() -> None:
    event = build_event(text="在吗")
    assert evaluate_trigger(event, make_settings(private=False)) is None


def test_group_ignored_without_mention_or_prefix() -> None:
    event = build_event(text="今天好热", message_type="group", group_id=1)
    assert evaluate_trigger(event, make_settings()) is None


def test_group_replies_when_mentioned() -> None:
    event = build_event(
        text="在吗",
        message_type="group",
        group_id=1,
        extra=(Segment(type="at", data={"qq": "999"}),),
    )
    result = evaluate_trigger(event, make_settings())
    assert result is not None
    assert "在吗" in result
    assert "@你" not in result


def test_group_replies_on_wake_word() -> None:
    event = build_event(text="机器人 讲个笑话", message_type="group", group_id=1)
    assert evaluate_trigger(event, make_settings()) == "讲个笑话"


def test_wake_word_alone_returns_none() -> None:
    event = build_event(text="机器人", message_type="group", group_id=1)
    assert evaluate_trigger(event, make_settings()) is None


def test_group_blacklist_blocks_even_when_mentioned() -> None:
    event = build_event(
        text="在吗",
        message_type="group",
        group_id=5,
        extra=(Segment(type="at", data={"qq": "999"}),),
    )
    assert evaluate_trigger(event, make_settings(group_blacklist=[5])) is None


def test_group_whitelist_limits_scope() -> None:
    event = build_event(
        text="在吗",
        message_type="group",
        group_id=5,
        extra=(Segment(type="at", data={"qq": "999"}),),
    )
    assert evaluate_trigger(event, make_settings(group_whitelist=[6])) is None
    assert evaluate_trigger(event, make_settings(group_whitelist=[5])) is not None


def test_probability_uses_injected_rng() -> None:
    event = build_event(text="今天好热", message_type="group", group_id=1)
    settings = make_settings(group_probability=0.5)
    assert evaluate_trigger(event, settings, rng=lambda: 0.1) == "今天好热"
    assert evaluate_trigger(event, settings, rng=lambda: 0.9) is None
