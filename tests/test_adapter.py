"""OneBot 适配器：动作调用、echo 匹配与发送路径。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from robot.adapters.onebot.client import OneBotAdapter, OneBotError, _Connection
from robot.config import OneBotSettings
from robot.core.event import Segment
from tests.conftest import build_event


class FakeSocket:
    """记录发出的帧，可手动回灌响应。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.frames.append(json.loads(raw))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


def make_adapter() -> OneBotAdapter:
    async def on_event(event) -> None:  # pragma: no cover - 占位
        return None

    return OneBotAdapter(OneBotSettings(), on_event)


async def test_call_resolves_via_echo() -> None:
    socket = FakeSocket()
    connection = _Connection(socket)

    task = asyncio.create_task(connection.call("get_login_info", {}))
    await asyncio.sleep(0)
    echo = socket.frames[0]["echo"]
    assert connection.resolve_echo(
        {"status": "ok", "retcode": 0, "data": {"user_id": 1}, "echo": echo}
    )
    assert await task == {"user_id": 1}


async def test_call_raises_on_failed_status() -> None:
    socket = FakeSocket()
    connection = _Connection(socket)

    task = asyncio.create_task(connection.call("send_group_msg", {}))
    await asyncio.sleep(0)
    echo = socket.frames[0]["echo"]
    connection.resolve_echo(
        {"status": "failed", "retcode": 100, "message": "no permission", "echo": echo}
    )
    with pytest.raises(OneBotError, match="no permission"):
        await task


async def test_resolve_echo_ignores_unknown_echo() -> None:
    connection = _Connection(FakeSocket())
    assert connection.resolve_echo({"echo": "不存在"}) is False
    assert connection.resolve_echo({"post_type": "message"}) is False


async def test_call_raises_when_connection_closed() -> None:
    connection = _Connection(FakeSocket())
    connection.closed = True
    with pytest.raises(OneBotError, match="断开"):
        await connection.call("anything", {})


async def test_send_group_message_builds_action_payload() -> None:
    adapter = make_adapter()
    socket = FakeSocket()
    connection = _Connection(socket)
    adapter._connections.append(connection)

    event = build_event(message_type="group", group_id=888)
    task = asyncio.create_task(
        adapter.send_message(event, [Segment(type="text", data={"text": "在的"})])
    )
    await asyncio.sleep(0)
    frame = socket.frames[0]
    assert frame["action"] == "send_group_msg"
    assert frame["params"]["group_id"] == 888
    assert frame["params"]["message"] == [{"type": "text", "data": {"text": "在的"}}]

    connection.resolve_echo(
        {"status": "ok", "retcode": 0, "data": {"message_id": 1}, "echo": frame["echo"]}
    )
    await task


async def test_send_private_message_uses_user_id() -> None:
    adapter = make_adapter()
    socket = FakeSocket()
    connection = _Connection(socket)
    adapter._connections.append(connection)

    event = build_event(message_type="private", user_id=111)
    task = asyncio.create_task(
        adapter.send_message(event, [Segment(type="text", data={"text": "嗯"})])
    )
    await asyncio.sleep(0)
    frame = socket.frames[0]
    assert frame["action"] == "send_private_msg"
    assert frame["params"]["user_id"] == 111

    connection.resolve_echo({"status": "ok", "retcode": 0, "data": {}, "echo": frame["echo"]})
    await task


async def test_send_without_connection_raises() -> None:
    adapter = make_adapter()
    with pytest.raises(OneBotError, match="没有可用的 OneBot 连接"):
        await adapter.send_message(build_event(), [Segment(type="text", data={"text": "hi"})])


async def test_message_event_is_forwarded() -> None:
    received = []

    async def on_event(event) -> None:
        received.append(event)

    adapter = OneBotAdapter(OneBotSettings(), on_event)

    payload = {
        "post_type": "message",
        "message_type": "private",
        "self_id": 999,
        "user_id": 111,
        "message_id": 1,
        "message": [{"type": "text", "data": {"text": "在吗"}}],
        "sender": {"nickname": "小明"},
    }
    await adapter._handle_payload(payload)
    assert len(received) == 1
    assert received[0].text == "在吗"
    assert adapter.self_id == 999


async def test_message_sent_echo_is_ignored() -> None:
    received = []

    async def on_event(event) -> None:
        received.append(event)

    adapter = OneBotAdapter(OneBotSettings(), on_event)
    await adapter._handle_payload({"post_type": "message_sent"})
    assert received == []


async def test_meta_event_records_self_id() -> None:
    adapter = make_adapter()
    await adapter._handle_payload(
        {"post_type": "meta_event", "meta_event_type": "lifecycle", "self_id": 4242},
    )
    assert adapter.self_id == 4242
