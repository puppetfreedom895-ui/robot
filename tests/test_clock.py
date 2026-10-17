"""时区：服务器多半是 UTC，作息和日记要按本地时间算。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from robot.life.brain import Decision
from robot.life.clock import UnknownZone, resolve_zone, to_local
from robot.life.loop import LifeLoop
from robot.life.store import LifeStore

# 2026-05-01 16:30 UTC = 2026-05-02 00:30 北京
CROSS_MIDNIGHT_TS = datetime(2026, 5, 1, 16, 30, tzinfo=UTC).timestamp()
# 2026-05-01 17:00 UTC = 2026-05-02 01:00 北京（免打扰时段内）
QUIET_TS = datetime(2026, 5, 1, 17, 0, tzinfo=UTC).timestamp()


class _Brain:
    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self.calls = 0

    async def decide(self, prompt, state):
        self.calls += 1
        return self._decision


class _Runner:
    def __init__(self) -> None:
        self.intents: list[str] = []

    async def run(self, intent: str) -> str:
        self.intents.append(intent)
        return "做完了"


def make_loop(tmp_path, *, moment: float, timezone_name: str, **kwargs):
    store = LifeStore(tmp_path / "life.db", timezone=timezone_name)
    brain = _Brain(Decision(act=True, intent="刷会儿手机"))
    runner = _Runner()
    loop = LifeLoop(
        store=store,
        brain=brain,
        runner=runner,
        clock=lambda: moment,
        timezone=timezone_name,
        **kwargs,
    )
    return loop, store, brain, runner


# ---- 解析 ----


def test_shanghai_is_ahead_of_utc() -> None:
    local = to_local(CROSS_MIDNIGHT_TS, resolve_zone("Asia/Shanghai"))
    assert local.hour == 0
    assert local.minute == 30
    assert local.strftime("%Y-%m-%d") == "2026-05-02"


def test_empty_timezone_means_system_local() -> None:
    assert resolve_zone("") is None


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(UnknownZone, match="Asia/Shanghai"):
        resolve_zone("Mars/Olympus")


# ---- 心跳 ----


async def test_quiet_hours_follow_configured_timezone(tmp_path) -> None:
    """UTC 17:00 是北京 01:00，应该睡觉——按 UTC 算会误判成白天。"""
    loop, store, brain, _runner = make_loop(
        tmp_path, moment=QUIET_TS, timezone_name="Asia/Shanghai", quiet_hours=(1, 7)
    )
    result = await loop.tick()

    assert result.slept is True
    assert brain.calls == 0
    store.close()


async def test_same_instant_is_awake_under_utc(tmp_path) -> None:
    """同一时刻按 UTC 算是 17:00，不该睡。"""
    loop, store, _brain, _runner = make_loop(
        tmp_path, moment=QUIET_TS, timezone_name="UTC", quiet_hours=(1, 7)
    )
    result = await loop.tick()

    assert result.slept is False
    store.close()


async def test_ledger_and_diary_use_local_day(tmp_path) -> None:
    """跨零点时，token 账要和日记记在北京日期下，而不是 UTC 日期。"""
    loop, store, _brain, _runner = make_loop(
        tmp_path,
        moment=CROSS_MIDNIGHT_TS,
        timezone_name="Asia/Shanghai",
        quiet_hours=(1, 7),
    )
    result = await loop.tick()

    assert result.acted is True
    assert await store.tokens_on("2026-05-02") > 0
    assert await store.tokens_on("2026-05-01") == 0
    diary = await store.recent_diary(1)
    assert diary and "2026-05-02" in diary[0]
    store.close()


def test_snapshot_reports_local_today(tmp_path) -> None:
    import asyncio

    from robot.life.clock import today_of

    store = LifeStore(tmp_path / "life.db", timezone="Asia/Shanghai")
    asyncio.run(store.note_tokens(today_of(resolve_zone("Asia/Shanghai")), 321))
    assert store.snapshot()["tokens_today"] == 321
    store.close()
