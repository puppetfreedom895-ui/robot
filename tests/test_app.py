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


# ---- 兜底回复：发消息一定要有回应 ----


def _fallback_context(settings, *, handled: bool, failures: int, group: bool):
    from robot.core.context import Context
    from robot.core.event import Segment
    from robot.core.runtime import Runtime

    extra = (Segment(type="at", data={"qq": "999"}),) if group else ()
    event = build_event(
        text="在吗",
        message_type="group" if group else "private",
        group_id=1 if group else None,
        extra=extra,
    )
    runtime = Runtime(settings=settings, memory=None, llm=None)  # type: ignore[arg-type]
    return Context(
        event=event, bot=FakeBot(), runtime=runtime, handled=handled, failures=failures
    ), event


def test_needs_fallback_only_when_broken_and_unanswered(settings) -> None:
    from robot.app import _needs_fallback

    ctx, event = _fallback_context(settings, handled=False, failures=1, group=False)
    assert _needs_fallback(ctx, event) is True

    answered, answered_event = _fallback_context(settings, handled=True, failures=1, group=False)
    assert _needs_fallback(answered, answered_event) is False

    healthy, healthy_event = _fallback_context(settings, handled=False, failures=0, group=False)
    assert _needs_fallback(healthy, healthy_event) is False


def test_needs_fallback_respects_group_mention(settings) -> None:
    from robot.app import _needs_fallback
    from robot.core.context import Context
    from robot.core.event import Segment
    from robot.core.runtime import Runtime

    runtime = Runtime(settings=settings, memory=None, llm=None)  # type: ignore[arg-type]

    mentioned = build_event(
        text="在吗",
        message_type="group",
        group_id=1,
        extra=(Segment(type="at", data={"qq": "999"}),),
    )
    assert (
        _needs_fallback(
            Context(event=mentioned, bot=FakeBot(), runtime=runtime, failures=1), mentioned
        )
        is True
    )

    quiet = build_event(text="今天吃啥", message_type="group", group_id=1)
    assert (
        _needs_fallback(Context(event=quiet, bot=FakeBot(), runtime=runtime, failures=1), quiet)
        is False
    )


async def test_private_message_still_answers_when_handler_crashes(tmp_path) -> None:
    from robot.core.bus import HandlerSpec

    app, bot, _provider = make_app(tmp_path)

    async def boom(ctx):
        raise RuntimeError("插件炸了")

    app.registry._handlers = [
        spec for spec in app.registry._handlers if spec.name != "chat.reply"
    ] + [HandlerSpec(name="chat.reply", priority=100, func=boom)]

    await app._on_event(build_event(text="在吗"))
    assert bot.texts == ["我这会儿有点问题，等下再问我一次？"]
    app.db.close()
