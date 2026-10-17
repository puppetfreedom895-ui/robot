"""会话记忆：上下文组装、窗口裁剪与摘要压缩。"""

from __future__ import annotations

from robot.config import Settings
from robot.core.memory import MemoryManager
from robot.llm.fake import ScriptedProvider
from robot.store.db import Database
from tests.conftest import build_event


def make_memory(tmp_path, settings: Settings, provider: ScriptedProvider | None = None):
    db = Database(tmp_path / "test.db")
    memory = MemoryManager(
        db=db,
        provider=provider or ScriptedProvider(replies=["摘要"]),
        settings=settings,
        persona="你是个网友",
    )
    return memory, db


async def test_record_and_build_messages(tmp_path, settings) -> None:
    memory, db = make_memory(tmp_path, settings)
    event = build_event(text="我叫阿伟")
    await memory.record_user(event, "我叫阿伟")

    messages = await memory.build_messages(event.session_key)
    assert messages[0].role == "system"
    assert "你是个网友" in messages[0].content
    assert messages[-1].role == "user"
    assert "小明：我叫阿伟" in messages[-1].content
    db.close()


async def test_history_is_trimmed_to_limit(tmp_path) -> None:
    settings = Settings(base_dir=tmp_path, chat={"history_limit": 4})
    memory, db = make_memory(tmp_path, settings)
    event = build_event()
    for index in range(10):
        await memory.record_user(event, f"消息{index}")

    messages = await memory.build_messages(event.session_key)
    assert len(messages) == 5  # system + 4 条
    assert "消息9" in messages[-1].content
    db.close()


async def test_fact_is_in_system_prompt(tmp_path, settings) -> None:
    memory, db = make_memory(tmp_path, settings)
    event = build_event()
    assert await memory.remember(event.session_key, "阿伟下周三过生日") is True
    assert await memory.remember(event.session_key, "阿伟下周三过生日") is False

    messages = await memory.build_messages(event.session_key)
    assert "阿伟下周三过生日" in messages[0].content
    db.close()


async def test_reset_clears_session_and_facts(tmp_path, settings) -> None:
    memory, db = make_memory(tmp_path, settings)
    event = build_event()
    await memory.record_user(event, "记住我")
    await memory.remember(event.session_key, "事实")
    await memory.reset(event.session_key)

    assert await db.count(event.session_key) == 0
    assert await memory.recall(event.session_key) == []
    db.close()


async def test_summarize_compresses_old_messages(tmp_path) -> None:
    settings = Settings(base_dir=tmp_path, chat={"history_limit": 2, "summary_enabled": True})
    provider = ScriptedProvider(replies=["他们聊了天气和晚饭"])
    memory, db = make_memory(tmp_path, settings, provider)
    event = build_event()
    for index in range(6):
        await memory.record_user(event, f"消息{index}")

    summary = await memory.maybe_summarize(event.session_key)
    assert summary == "他们聊了天气和晚饭"
    assert await db.count(event.session_key) == 2
    assert await db.get_summary(event.session_key) == "他们聊了天气和晚饭"

    messages = await memory.build_messages(event.session_key)
    assert "他们聊了天气和晚饭" in messages[0].content
    db.close()


async def test_summarize_skipped_when_disabled(tmp_path) -> None:
    settings = Settings(base_dir=tmp_path, chat={"history_limit": 2, "summary_enabled": False})
    memory, db = make_memory(tmp_path, settings)
    event = build_event()
    for index in range(6):
        await memory.record_user(event, f"消息{index}")

    assert await memory.maybe_summarize(event.session_key) is None
    assert await db.count(event.session_key) == 6
    db.close()
