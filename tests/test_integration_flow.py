"""端到端：假装成 NapCat 的服务端，验证整条链路真的通。

链路：假 NapCat 推一条私聊 → OneBot 适配器解析 → 插件分发 → 聊天回复
      → 动作帧回到 NapCat → 状态联动写入生活库。

全程不联网、不花钱、不需要真机。
"""

from __future__ import annotations

import asyncio
import json
import socket
from typing import Any

from websockets.asyncio.server import serve as ws_serve

from robot.config import LifeSettings, OneBotSettings, Settings
from robot.life.store import LifeStore
from robot.service import LifeService


class FakeNapCat:
    """最小可用的 OneBot v11 服务端：收动作、回 ok、推事件。"""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.connected = asyncio.Event()
        self._socket: socket.socket | None = None
        self._server: Any = None
        self._ws: Any = None
        self.port = 0

    async def start(self) -> None:
        """在随机端口上监听。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        self._socket = sock
        self.port = int(sock.getsockname()[1])
        self._server = await ws_serve(self._handle, sock=sock)

    async def _handle(self, websocket: Any) -> None:
        self._ws = websocket
        self.connected.set()
        async for raw in websocket:
            frame = json.loads(raw)
            self.received.append(frame)
            echo = frame.get("echo")
            if echo is not None:
                await websocket.send(
                    json.dumps({"status": "ok", "retcode": 0, "data": {}, "echo": echo})
                )

    async def push(self, payload: dict[str, Any]) -> None:
        """向机器人推一条事件。"""
        assert self._ws is not None, "还没有连接"
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def wait_for_action(self, action: str, limit: float = 5.0) -> dict[str, Any]:
        """等某个动作帧出现。

        @param action: 动作名，如 send_private_msg。
        @param limit: 最长等待秒数。
        @returns: 动作帧。
        @raises AssertionError: 超时没等到。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + limit
        while loop.time() < deadline:
            for frame in self.received:
                if frame.get("action") == action:
                    return frame
            await asyncio.sleep(0.02)
        raise AssertionError(
            f"没等到动作 {action}，收到的是 {[f.get('action') for f in self.received]}"
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


def make_settings(port: int, tmp_path) -> Settings:
    """指向假 NapCat 的配置。"""
    return Settings(
        base_dir=tmp_path,
        llm={"api_key": "test"},
        onebot=OneBotSettings(
            mode="client",
            url=f"ws://127.0.0.1:{port}",
            reconnect_min=0.05,
            reconnect_max=0.2,
        ),
        life=LifeSettings(enabled=True, owner=10001, heartbeat_minutes=60),
    )


PRIVATE_MESSAGE = {
    "time": 1710000000,
    "self_id": 999,
    "post_type": "message",
    "message_type": "private",
    "sub_type": "friend",
    "message_id": 1,
    "user_id": 10001,
    "message": [{"type": "text", "data": {"text": "在干嘛"}}],
    "sender": {"user_id": 10001, "nickname": "主人"},
}


async def test_private_message_gets_reply_over_websocket(tmp_path) -> None:
    from robot.llm.fake import ScriptedProvider

    napcat = FakeNapCat()
    await napcat.start()
    service = LifeService(
        make_settings(napcat.port, tmp_path),
        provider=ScriptedProvider(["在的，刚刷完手机"]),
    )

    runner = asyncio.create_task(service.run())
    try:
        await asyncio.wait_for(napcat.connected.wait(), timeout=10)
        await napcat.push(PRIVATE_MESSAGE)

        frame = await napcat.wait_for_action("send_private_msg")
        assert frame["params"]["user_id"] == 10001
        assert frame["params"]["message"][0]["data"]["text"] == "在的，刚刷完手机"

        # 状态联动在回复之后写入，这里等它落库
        events: list[str] = []
        for _ in range(100):
            events = await service.store.recent_events(10)
            if any("在干嘛" in event for event in events):
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError(f"没有记下这次对话，事件是 {events}")
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        await napcat.stop()


async def test_reconnects_after_napcat_restart(tmp_path) -> None:
    """NapCat 重启后应该自己连回来，而不是等人插手。"""
    from robot.llm.fake import ScriptedProvider

    napcat = FakeNapCat()
    await napcat.start()
    port = napcat.port

    service = LifeService(
        make_settings(port, tmp_path),
        provider=ScriptedProvider(["嗯"]),
    )
    runner = asyncio.create_task(service.run())
    try:
        await asyncio.wait_for(napcat.connected.wait(), timeout=10)
        await napcat.stop()
        await asyncio.sleep(0.3)

        again = FakeNapCat()
        again.port = port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen()
        sock.setblocking(False)
        again._socket = sock
        again._server = await ws_serve(again._handle, sock=sock)

        await asyncio.wait_for(again.connected.wait(), timeout=10)
        await again.stop()
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_life_store_snapshot_reflects_activity(tmp_path) -> None:
    store = LifeStore(tmp_path / "life.db")
    from robot.life.state import LifeState

    await store.save_state(LifeState(energy=66, boredom=12, mood="还行", focus="看剧"))
    snap = store.snapshot()
    assert snap["state"]["energy"] == 66
    assert snap["state"]["focus"] == "看剧"
    store.close()
