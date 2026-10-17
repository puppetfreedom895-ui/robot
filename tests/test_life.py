"""生命内核：状态、护栏、决策解析与心跳循环。"""

from __future__ import annotations

from datetime import datetime

import pytest

from robot.life.brain import Decision, OfflineBrain, ScriptedBrain, parse_decision
from robot.life.loop import LifeLoop, in_quiet_hours
from robot.life.policy import PolicyBlocked, check, classify
from robot.life.prompt import build_wake_prompt
from robot.life.state import LifeState
from robot.life.store import LifeStore

DAY = "2026-05-01"
AFTERNOON = datetime(2026, 5, 1, 14, 0)
NIGHT = datetime(2026, 5, 1, 3, 0)


class FixedClock:
    """固定在一个时刻的时钟。"""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> float:
        return self.moment.timestamp()


class RecordingRunner:
    """记录被执行的意图，不碰任何真实设备。"""

    def __init__(self, narration: str = "做完了") -> None:
        self.intents: list[str] = []
        self._narration = narration

    async def run(self, intent: str) -> str:
        self.intents.append(intent)
        return self._narration


class CollectingNotifier:
    """收集它主动说的话。"""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def notify(self, text: str) -> None:
        self.messages.append(text)


def make_loop(tmp_path, *, moment=AFTERNOON, decisions=None, runner=None, notifier=None, **kwargs):
    store = LifeStore(tmp_path / "life.db")
    brain = ScriptedBrain(decisions or [Decision(act=False)])
    runner = runner or RecordingRunner()
    notifier = notifier or CollectingNotifier()
    loop = LifeLoop(
        store=store,
        brain=brain,
        runner=runner,
        notifier=notifier,
        clock=FixedClock(moment),
        **kwargs,
    )
    return loop, store, brain, runner, notifier


# ---- 状态 ----


def test_acting_costs_energy_and_kills_boredom() -> None:
    state = LifeState(energy=50, boredom=80)
    acted = state.acted("刷了会儿手机")
    assert acted.energy < state.energy
    assert acted.boredom < state.boredom
    assert acted.focus == "刷了会儿手机"


def test_state_values_stay_in_range() -> None:
    drained = LifeState(energy=1, boredom=1).acted("很累的事")
    assert drained.energy == 0
    assert drained.boredom == 0

    full = LifeState(energy=100, boredom=100).rested(20)
    assert full.energy == 100
    assert full.boredom == 100


def test_describe_mentions_focus() -> None:
    text = LifeState(energy=70, boredom=40, focus="想学做饭").describe()
    assert "精力 70" in text
    assert "想学做饭" in text


# ---- 护栏 ----


def test_classify_levels() -> None:
    assert classify("刷会儿手机") == "L1"
    assert classify("私聊问一下他") == "L2"
    assert classify("转账五块钱") == "L3"


def test_check_blocks_spending() -> None:
    with pytest.raises(PolicyBlocked):
        check("帮她下单买杯咖啡")


def test_check_allows_reading_and_talking() -> None:
    assert check("看看微博") == "L1"
    assert check("发消息问候一下") == "L2"


# ---- 决策解析 ----


def test_parse_plain_json() -> None:
    decision = parse_decision('{"act": true, "intent": "看视频", "mood": "放松"}')
    assert decision.act is True
    assert decision.intent == "看视频"
    assert decision.mood == "放松"


def test_parse_json_wrapped_in_chatter() -> None:
    decision = parse_decision('好的，我决定：\n{"act": false}\n就这样。')
    assert decision.act is False


def test_parse_garbage_falls_back_to_resting() -> None:
    assert parse_decision("我不想回 JSON").act is False
    assert parse_decision("").act is False
    assert parse_decision("{坏的}").act is False


def test_parse_accepts_string_boolean() -> None:
    assert parse_decision('{"act": "true", "intent": "散步"}').act is True


def test_parse_without_act_key_rests() -> None:
    assert parse_decision('{"intent": "看视频"}').act is False


def test_parse_truncates_long_fields() -> None:
    decision = parse_decision('{"act": true, "intent": "' + "很" * 200 + '"}')
    assert len(decision.intent) == 80


# ---- 提示词 ----


def test_prompt_is_short_and_self_contained() -> None:
    prompt = build_wake_prompt(
        LifeState(name="小七", energy=70, boredom=45, focus="想学做饭"),
        now=AFTERNOON,
        events=["13:50 刷了会儿手机"],
        goals=["把昨天的剧看完"],
    )
    assert "小七" in prompt
    assert "周五" in prompt
    assert "想学做饭" in prompt
    assert "把昨天的剧看完" in prompt
    assert '"act"' in prompt
    assert len(prompt) < 600  # 每次都进上下文，必须短


def test_quiet_hours_handles_midnight_wrap() -> None:
    assert in_quiet_hours(datetime(2026, 5, 1, 23, 0), (22, 6)) is True
    assert in_quiet_hours(datetime(2026, 5, 1, 3, 0), (22, 6)) is True
    assert in_quiet_hours(datetime(2026, 5, 1, 12, 0), (22, 6)) is False
    assert in_quiet_hours(datetime(2026, 5, 1, 12, 0), (5, 5)) is False


# ---- 心跳 ----


async def test_night_sleeps_without_calling_model(tmp_path) -> None:
    loop, store, brain, runner, _ = make_loop(tmp_path, moment=NIGHT)
    result = await loop.tick()

    assert result.slept is True
    assert brain.calls == 0  # 夜里不烧 token
    assert runner.intents == []
    store.close()


async def test_low_energy_rests_without_calling_model(tmp_path) -> None:
    loop, store, brain, _runner, _ = make_loop(tmp_path)
    await store.save_state(LifeState(energy=5, boredom=90))
    result = await loop.tick()

    assert result.acted is False
    assert brain.calls == 0
    store.close()


async def test_budget_exhausted_stops_thinking(tmp_path) -> None:
    loop, store, brain, _runner, _ = make_loop(tmp_path, daily_budget_tokens=100)
    await store.save_state(LifeState(energy=90, boredom=90))
    await store.note_tokens(DAY, 500)

    result = await loop.tick()
    assert result.acted is False
    assert brain.calls == 0
    assert "额度" in result.narration
    store.close()


async def test_acting_runs_intent_and_records_it(tmp_path) -> None:
    loop, store, brain, runner, _ = make_loop(
        tmp_path, decisions=[Decision(act=True, intent="刷会儿手机", mood="有点无聊")]
    )
    await store.save_state(LifeState(energy=90, boredom=80))

    result = await loop.tick()
    assert result.acted is True
    assert runner.intents == ["刷会儿手机"]
    assert brain.calls == 1

    state = await store.load_state()
    assert state.energy < 90
    assert state.mood == "有点无聊"

    events = await store.recent_events(5)
    assert any("刷会儿手机" in event for event in events)
    diary = await store.recent_diary(1)
    assert any("刷会儿手机" in line for line in diary)
    store.close()


async def test_idle_tick_recovers_a_little(tmp_path) -> None:
    loop, store, _brain, runner, _ = make_loop(tmp_path, decisions=[Decision(act=False)])
    await store.save_state(LifeState(energy=50, boredom=20))

    result = await loop.tick()
    assert result.acted is False
    assert runner.intents == []
    assert (await store.load_state()).energy > 50
    store.close()


async def test_l3_intent_is_blocked_and_reported(tmp_path) -> None:
    loop, store, _brain, runner, notifier = make_loop(
        tmp_path, decisions=[Decision(act=True, intent="给她转账五十块")]
    )
    await store.save_state(LifeState(energy=90, boredom=80))

    result = await loop.tick()
    assert result.acted is False
    assert result.blocked
    assert runner.intents == []  # 没有真的执行
    assert any("点头" in message for message in notifier.messages)

    events = await store.recent_events(5)
    assert any("转账" in event for event in events)
    store.close()


async def test_say_is_delivered_to_notifier(tmp_path) -> None:
    loop, store, _brain, _runner, notifier = make_loop(
        tmp_path, decisions=[Decision(act=True, intent="看看手机", say="我有点无聊")]
    )
    await store.save_state(LifeState(energy=90, boredom=80))

    await loop.tick()
    assert notifier.messages == ["我有点无聊"]
    store.close()


async def test_tokens_are_accounted(tmp_path) -> None:
    loop, store, _brain, _runner, _ = make_loop(tmp_path, decisions=[Decision(act=False)])
    await loop.tick()
    assert await store.tokens_on(DAY) > 0
    store.close()


# ---- 存储 ----


async def test_goals_roundtrip(tmp_path) -> None:
    store = LifeStore(tmp_path / "life.db")
    await store.add_goal("把昨天的剧看完")
    await store.add_goal("研究一下怎么煎蛋")
    assert await store.open_goals() == ["把昨天的剧看完", "研究一下怎么煎蛋"]

    await store.close_goal("把昨天的剧看完")
    assert await store.open_goals() == ["研究一下怎么煎蛋"]
    store.close()


async def test_diary_groups_by_day(tmp_path) -> None:
    store = LifeStore(tmp_path / "life.db")
    await store.add_diary("2026-04-30", "10:00 看了会儿书")
    await store.add_diary("2026-05-01", "14:00 刷了会儿手机")
    lines = await store.recent_diary(2)
    assert len(lines) == 2
    assert "2026-05-01" in lines[0]
    store.close()


async def test_offline_brain_waits_until_bored() -> None:
    brain = OfflineBrain(intents=["刷会儿手机"])
    calm = await brain.decide("", LifeState(energy=90, boredom=10))
    bored = await brain.decide("", LifeState(energy=90, boredom=70))
    tired = await brain.decide("", LifeState(energy=10, boredom=90))

    assert calm.act is False
    assert bored.act is True
    assert bored.intent == "刷会儿手机"
    assert tired.act is False
