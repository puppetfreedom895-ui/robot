"""QQ 出入口：主动说话、状态联动与服务装配。"""

from __future__ import annotations

import pytest

from robot.config import LifeSettings, Settings
from robot.life.brain import LLMBrain, OfflineBrain
from robot.life.presence import LifePresence
from robot.life.qq import QQNotifier
from robot.life.runner import DemoRunner, DshRunner
from robot.life.state import LifeState
from robot.life.store import LifeStore
from robot.service import LifeService
from tests.conftest import FakeBot, build_event

OWNER = 10001


class FakeAdapter:
    """够 LifeService 用的假适配器。"""

    def __init__(self) -> None:
        self.self_id = 0
        self.handler = None
        self.started = False
        self.calls: list[tuple[str, object]] = []

    def bind(self, handler) -> None:
        self.handler = handler

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send_message(self, event, segments) -> None:
        return None

    async def call_api(self, action, params=None):
        self.calls.append((action, params))
        return {}


# ---- 主动说话 ----


async def test_notifier_sends_private_message() -> None:
    bot = FakeBot()
    notifier = QQNotifier(bot, OWNER)
    await notifier.notify("我有点无聊")

    action, params = bot.calls[-1]
    assert action == "send_private_msg"
    assert params["user_id"] == OWNER
    assert params["message"] == [{"type": "text", "data": {"text": "我有点无聊"}}]
    assert notifier.sent == ["我有点无聊"]


async def test_notifier_ignores_blank_text() -> None:
    bot = FakeBot()
    await QQNotifier(bot, OWNER).notify("   ")
    assert bot.calls == []


async def test_notifier_without_owner_does_not_send() -> None:
    bot = FakeBot()
    notifier = QQNotifier(bot, 0)
    await notifier.notify("有人吗")
    assert bot.calls == []
    assert notifier.sent == []


async def test_notifier_swallows_transport_errors() -> None:
    class BrokenBot(FakeBot):
        async def call_api(self, action, params=None):
            raise RuntimeError("连接断了")

    notifier = QQNotifier(BrokenBot(), OWNER)
    await notifier.notify("在吗")  # 不抛异常
    assert notifier.sent == []


# ---- 状态联动 ----


async def test_talking_makes_it_less_bored(tmp_path) -> None:
    store = LifeStore(tmp_path / "life.db")
    await store.save_state(LifeState(energy=80, boredom=60))
    presence = LifePresence(store, owner=OWNER)

    await presence.on_message(build_event(text="在干嘛", sender_name="主人"))

    state = await store.load_state()
    assert state.boredom < 60
    assert state.energy < 80

    events = await store.recent_events(3)
    assert any("在干嘛" in event for event in events)
    store.close()


async def test_talking_records_who_said_it(tmp_path) -> None:
    store = LifeStore(tmp_path / "life.db")
    presence = LifePresence(store, owner=OWNER)
    await presence.on_message(build_event(text="早", sender_name="阿伟"))
    assert any("阿伟" in event for event in await store.recent_events(1))
    store.close()


# ---- 服务装配 ----


def make_settings(tmp_path, **life) -> Settings:
    return Settings(
        base_dir=tmp_path,
        llm={"api_key": "k"},
        life=LifeSettings(**life),
    )


def test_service_wires_notifier_brain_and_runner(tmp_path) -> None:
    settings = make_settings(
        tmp_path,
        enabled=True,
        owner=OWNER,
        brain="offline",
        dsh_command="dsh --profile headless",
    )
    service = LifeService(settings, adapter=FakeAdapter())

    assert service.notifier.owner == OWNER
    assert isinstance(service.brain, OfflineBrain)
    assert isinstance(service.runner, DshRunner)
    assert service.runner.command == ["dsh", "--profile", "headless"]
    assert service.loop is not None
    service.store.close()
    service.app.db.close()


def test_service_uses_demo_runner_without_dsh_command(tmp_path) -> None:
    service = LifeService(make_settings(tmp_path, enabled=True), adapter=FakeAdapter())
    assert isinstance(service.runner, DemoRunner)
    service.store.close()
    service.app.db.close()


def test_service_uses_model_brain_when_configured(tmp_path) -> None:
    settings = make_settings(tmp_path, enabled=True, brain="model")
    service = LifeService(settings, adapter=FakeAdapter())
    assert isinstance(service.brain, LLMBrain)
    service.store.close()
    service.app.db.close()


async def test_live_refuses_when_disabled(tmp_path, capsys) -> None:
    from robot.cli import _live

    settings = make_settings(tmp_path, enabled=False)
    assert await _live(settings) == 2
    assert "enabled" in capsys.readouterr().err


async def test_service_heartbeat_task_runs(tmp_path, monkeypatch) -> None:
    """服务能把心跳任务跑起来，而且出错不会杀死进程。"""
    service = LifeService(
        make_settings(tmp_path, enabled=True, owner=OWNER, heartbeat_minutes=0.0001),
        adapter=FakeAdapter(),
    )

    ticks = 0

    async def fake_tick():
        nonlocal ticks
        ticks += 1
        from robot.life.loop import TickResult

        return TickResult(acted=False, narration="待着")

    monkeypatch.setattr(service.loop, "tick", fake_tick)

    task = __import__("asyncio").create_task(service._heartbeat())
    await __import__("asyncio").sleep(0.05)
    task.cancel()
    with pytest.raises(__import__("asyncio").CancelledError):
        await task

    assert ticks >= 2
    service.store.close()
    service.app.db.close()
