"""演示：假装是 NapCat，给机器人发一句话，看它怎么回。

    python scripts/demo_chat.py

不需要 QQ、不需要扫码、不花钱（没配密钥时用假模型）。
用来确认「你给它发消息，它一定回」这条链路是通的。
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import Any

from websockets.asyncio.server import serve as ws_serve

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from robot.config import LifeSettings, OneBotSettings, Settings  # noqa: E402
from robot.llm.fake import ScriptedProvider  # noqa: E402
from robot.service import LifeService  # noqa: E402

OWNER = 10001


class FakeNapCat:
    """最小 OneBot 服务端：收动作、回响应、推事件。"""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.ready = asyncio.Event()
        self.ws: Any = None

    async def start(self) -> int:
        """启动并返回端口。"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.setblocking(False)
        self.port = int(sock.getsockname()[1])
        self.server = await ws_serve(self._handle, sock=sock)
        return self.port

    async def _handle(self, websocket: Any) -> None:
        self.ws = websocket
        self.ready.set()
        async for raw in websocket:
            frame = json.loads(raw)
            self.frames.append(frame)
            echo = frame.get("echo")
            if echo is not None:
                await websocket.send(
                    json.dumps({"status": "ok", "retcode": 0, "data": {}, "echo": echo})
                )

    async def say(self, text: str) -> None:
        """像用户一样发一条私聊。"""
        await self.ws.send(
            json.dumps(
                {
                    "post_type": "message",
                    "message_type": "private",
                    "self_id": 999,
                    "user_id": OWNER,
                    "message_id": 1,
                    "message": [{"type": "text", "data": {"text": text}}],
                    "sender": {"nickname": "主人"},
                },
                ensure_ascii=False,
            )
        )

    def replies(self) -> list[str]:
        """机器人发回来的文本。"""
        texts: list[str] = []
        for frame in self.frames:
            if frame.get("action") != "send_private_msg":
                continue
            for segment in frame["params"]["message"]:
                if segment.get("type") == "text":
                    texts.append(segment["data"]["text"])
        return texts

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()


async def main() -> int:
    napcat = FakeNapCat()
    port = await napcat.start()

    settings = Settings(
        base_dir=ROOT,
        llm={"api_key": "demo"},
        onebot=OneBotSettings(mode="client", url=f"ws://127.0.0.1:{port}", reconnect_min=0.05),
        life=LifeSettings(enabled=True, owner=OWNER, heartbeat_minutes=600),
    )
    service = LifeService(settings, provider=ScriptedProvider(["在的，刚刷完手机，咋了"]))
    runner = asyncio.create_task(service.run())

    try:
        await asyncio.wait_for(napcat.ready.wait(), timeout=10)
        await napcat.say("在干嘛")
        await asyncio.sleep(1.0)

        replies = napcat.replies()
        print("你发给它：在干嘛")
        print(f"它回你：{replies[-1] if replies else '（没回！）'}")
        events = await service.store.recent_events(5)
        print(f"它记下的事：{events}")
        return 0 if replies else 1
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        await napcat.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
