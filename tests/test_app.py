"""端到端：从消息事件到模型回复再到落库。"""

from __future__ import annotations

from collections.abc import Sequence

from robot.app import RobotApp
from robot.config import Settings
from robot.llm.base import ChatMessage, LLMError, Provider
from robot.llm.fake import ScriptedProvider
from tests.conftest import FakeBot, build_event


def make_app(tmp_path, **chat: object) -> tuple[RobotApp, FakeBot, ScriptedProvider]:
    settings = Settings(base_dir=tmp_path, llm={"api_key": "k"}, chat=chat)
    provider = ScriptedProvider(replies=["**在的**，咋了"])
    app = RobotApp(settings, provider=provider)
    bot = FakeBot()
    app.adapter = bot  # type: ignore[assignment]
    return app, bot, provider


async def test_private_message_gets_cleaned_reply(tmp_path) -> None:
    app, bot, provider = make_app(tmp_path)
    await app._on_event(build_event(text="在吗"))

    assert bot.texts == ["在的，咋了"]
    history = await app.db.recent("private:111", 10)
    assert [item.role for item in history] == ["user", "assistant"]
    assert history[0].content == "在吗"
    assert len(provider.calls) == 1
    assert provider.calls[0][0].role == "system"
    app.db.close()


async def test_group_message_ignored_without_trigger(tmp_path) -> None:
    app, bot, _ = make_app(tmp_path)
    await app._on_event(build_event(text="今天吃啥", message_type="group", group_id=1))
    assert bot.texts == []
    app.db.close()


async def test_group_message_replies_when_mentioned(tmp_path) -> None:
    from robot.core.event import Segment

    app, bot, _ = make_app(tmp_path)
    event = build_event(
        text="在吗",
        message_type="group",
        group_id=1,
        extra=(Segment(type="at", data={"qq": "999"}),),
    )
    await app._on_event(event)
    assert bot.texts == ["在的，咋了"]
    app.db.close()


async def test_help_command_does_not_reach_model(tmp_path) -> None:
    app, bot, provider = make_app(tmp_path)
    await app._on_event(build_event(text="/help"))

    assert provider.calls == []
    assert "记住" in bot.texts[0]
    app.db.close()


async def test_remember_command_stores_fact(tmp_path) -> None:
    app, bot, _ = make_app(tmp_path)
    await app._on_event(build_event(text="/记住 阿伟下周三过生日"))

    assert bot.texts == ["记住了。"]
    assert await app.db.facts("private:111") == ["阿伟下周三过生日"]
    app.db.close()


async def test_cooldown_suppresses_second_reply(tmp_path) -> None:
    app, bot, _ = make_app(tmp_path)
    app.settings.trigger.cooldown = 60.0

    await app._on_event(build_event(text="第一次"))
    await app._on_event(build_event(text="第二次"))
    assert len(bot.texts) == 1
    app.db.close()


async def test_model_failure_sends_fallback(tmp_path) -> None:
    class BrokenProvider(Provider):
        async def complete(self, messages: Sequence[ChatMessage]) -> str:
            raise LLMError("服务不可用")

    settings = Settings(base_dir=tmp_path, llm={"api_key": "k"})
    app = RobotApp(settings, provider=BrokenProvider())
    bot = FakeBot()
    app.adapter = bot  # type: ignore[assignment]

    await app._on_event(build_event(text="在吗"))
    assert "有点卡" in bot.texts[0]
    app.db.close()


async def test_owner_can_reset_session(tmp_path) -> None:
    app, bot, _ = make_app(tmp_path)
    app.settings.admin.owners = [111]

    await app._on_event(build_event(text="在吗"))
    await app._on_event(build_event(text="/reset"))

    assert await app.db.count("private:111") == 0
    assert "清空" in bot.texts[-1]
    app.db.close()


async def test_non_owner_cannot_reset(tmp_path) -> None:
    app, bot, _ = make_app(tmp_path)
    app.settings.admin.owners = [999999]
    await app._on_event(build_event(text="/reset"))
    assert "只有管理员" in bot.texts[0]
    app.db.close()
