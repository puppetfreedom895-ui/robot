"""OneBot v11 WebSocket 适配器。

两种连接方式都支持：
- client：连到 NapCat 的 WebSocket 服务端；
- server：监听端口，让 NapCat 以「WebSocket 客户端」反连进来。

断线自动重连（指数退避），动作调用用 echo 匹配响应。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import connect as ws_connect
from websockets.asyncio.server import serve as ws_serve

from robot.adapters.onebot.parse import parse_message_event
from robot.config import OneBotSettings
from robot.core.event import MessageEvent, Segment
from robot.log import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[MessageEvent], Awaitable[None]]


class OneBotError(RuntimeError):
    """与 OneBot 实现交互失败。"""


class _Connection:
    """一条 WebSocket 连接及其未完成的动作调用。"""

    def __init__(self, socket: Any) -> None:
        self.socket = socket
        self.pending: dict[str, asyncio.Future[Any]] = {}
        self.closed = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self.socket.send(json.dumps(payload, ensure_ascii=False))

    async def call(self, action: str, params: dict[str, Any] | None, limit: float = 30.0) -> Any:
        """发一个动作请求并等待响应。

        @param action: OneBot action 名。
        @param params: 参数。
        @param limit: 等待响应的最长秒数。
        @returns: 响应里的 data 字段。
        @raises OneBotError: 连接已断开、超时或返回失败。
        """
        if self.closed:
            raise OneBotError("连接已断开")

        echo = uuid.uuid4().hex
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.send_json({"action": action, "params": params or {}, "echo": echo})
            response = await asyncio.wait_for(future, timeout=limit)
        except TimeoutError as exc:
            raise OneBotError(f"调用 {action} 超时") from exc
        finally:
            self.pending.pop(echo, None)

        if not isinstance(response, dict):
            raise OneBotError(f"调用 {action} 返回格式异常")
        if response.get("status") == "failed" or response.get("retcode") not in (0, 1, None):
            detail = response.get("message") or response.get("wording")
            raise OneBotError(f"调用 {action} 失败：retcode={response.get('retcode')} msg={detail}")
        return response.get("data")

    def resolve_echo(self, payload: dict[str, Any]) -> bool:
        """如果这一帧是某个动作的响应，就唤醒等待者。

        @param payload: 收到的一帧 JSON。
        @returns: 命中等待中的调用返回 True。
        """
        echo = payload.get("echo")
        if not isinstance(echo, str):
            return False
        future = self.pending.get(echo)
        if future is None:
            return False
        if not future.done():
            future.set_result(payload)
        return True


class OneBotAdapter:
    """把 OneBot v11 的事件与接口接到机器人核心。"""

    def __init__(self, settings: OneBotSettings, on_event: EventHandler) -> None:
        self.settings = settings
        self._on_event = on_event
        self.self_id = 0
        self._connections: list[_Connection] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._server: Any = None
        self._stop_event = asyncio.Event()
        self._stopping = False

    def bind(self, handler: EventHandler) -> None:
        """换掉事件处理函数。

        适配器可能先于上层装配创建，等上层就绪后再绑定。

        @param handler: 新的处理函数。
        """
        self._on_event = handler

    # ---- 生命周期 ----

    async def start(self) -> None:
        """启动连接。会一直运行到 stop() 被调用。"""
        self._stopping = False
        self._stop_event.clear()
        if self.settings.mode == "server":
            await self._serve()
        else:
            await self._connect_forever()

    async def stop(self) -> None:
        """关闭所有连接并停止后台任务。"""
        self._stopping = True
        self._stop_event.set()
        for connection in list(self._connections):
            await self._drop(connection, reason="主动停止")
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    # ---- 发送 ----

    def _current(self) -> _Connection:
        """取一条可用连接。"""
        for connection in self._connections:
            if not connection.closed:
                return connection
        raise OneBotError("当前没有可用的 OneBot 连接，检查 NapCat 是否在运行")

    async def send_message(self, event: MessageEvent, segments: list[Segment]) -> None:
        """把消息发回事件来源会话。

        @param event: 触发回复的事件。
        @param segments: 消息段。
        @raises OneBotError: 没有可用连接或发送失败。
        """
        payload = [segment.data | {"type": segment.type} for segment in segments]
        if event.is_group:
            action = "send_group_msg"
            params: dict[str, Any] = {"group_id": event.chat_id, "message": payload}
        else:
            action = "send_private_msg"
            params = {"user_id": event.chat_id, "message": payload}
        await self._current().call(action, params)

    async def call_api(self, action: str, params: dict[str, Any] | None = None) -> Any:
        """调用任意 OneBot 接口。

        @param action: 接口名。
        @param params: 参数。
        @returns: 接口 data。
        @raises OneBotError: 没有可用连接或调用失败。
        """
        return await self._current().call(action, params)

    async def fetch_self_id(self) -> int:
        """用 get_login_info 取登录账号，顺便验证链路是否通。

        @returns: 登录 QQ 号，取不到时返回 0。
        """
        try:
            data = await self.call_api("get_login_info")
        except OneBotError as exc:
            logger.debug("get_login_info 失败：%s", exc)
            return 0
        if isinstance(data, dict):
            self.self_id = int(data.get("user_id") or 0)
        return self.self_id

    # ---- client 模式 ----

    async def _connect_forever(self) -> None:
        delay = self.settings.reconnect_min
        while not self._stopping:
            headers = {}
            if self.settings.token:
                headers["Authorization"] = f"Bearer {self.settings.token}"
            try:
                async with ws_connect(
                    self.settings.url,
                    additional_headers=headers or None,
                    max_size=None,
                    ping_interval=20,
                ) as socket:
                    logger.info("已连接 NapCat：%s", self.settings.url)
                    delay = self.settings.reconnect_min
                    await self._serve_connection(socket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 网络抖动、NapCat 未启动等都走重连
                if self._stopping:
                    break
                logger.warning("连接 %s 失败：%s，%.1fs 后重试", self.settings.url, exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.settings.reconnect_max)

    # ---- server 模式 ----

    async def _serve(self) -> None:
        async def handler(socket: Any, *_: Any) -> None:
            if not self._authorized(socket):
                logger.warning("拒绝了一个令牌不匹配的反向连接")
                await socket.close(code=1008, reason="unauthorized")
                return
            logger.info("NapCat 已反连（%s）", self._remote(socket))
            await self._serve_connection(socket)

        self._server = await ws_serve(
            handler,
            self.settings.host,
            self.settings.port,
            max_size=None,
            ping_interval=20,
        )
        logger.info(
            "等待 NapCat 连接：ws://%s:%d%s",
            self.settings.host,
            self.settings.port,
            self.settings.path,
        )
        await self._stop_event.wait()

    def _authorized(self, socket: Any) -> bool:
        """校验反连令牌。配置为空表示不校验。

        @param socket: 连接对象。
        @returns: 是否放行。
        """
        if not self.settings.token:
            return True
        request = getattr(socket, "request", None)
        headers = getattr(request, "headers", {})
        auth = headers.get("Authorization", "")
        if auth == f"Bearer {self.settings.token}":
            return True
        path = getattr(request, "path", "") or ""
        return f"access_token={self.settings.token}" in path

    @staticmethod
    def _remote(socket: Any) -> str:
        request = getattr(socket, "request", None)
        client = getattr(request, "remote_address", None)
        return str(client) if client else "未知地址"

    # ---- 共用：读帧 ----

    async def _serve_connection(self, socket: Any) -> None:
        connection = _Connection(socket)
        self._connections.append(connection)
        try:
            await self._drain(connection)
        finally:
            await self._drop(connection, reason="连接结束")

    async def _drain(self, connection: _Connection) -> None:
        async for raw in connection.socket:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("收到非 JSON 帧，已忽略：%r", raw[:200])
                continue
            if not isinstance(payload, dict):
                continue
            await self._handle_payload(connection, payload)

    async def _handle_payload(self, connection: _Connection, payload: dict[str, Any]) -> None:
        if connection.resolve_echo(payload):
            return

        post_type = payload.get("post_type")
        if post_type == "meta_event":
            self._handle_meta(payload)
            return
        if post_type == "message_sent":
            return  # 自己发出的消息回声，忽略
        if post_type != "message":
            return

        event = parse_message_event(payload, default_self_id=self.self_id)
        if event is None:
            return
        if event.self_id and not self.self_id:
            self.self_id = event.self_id
        await self._on_event(event)

    def _handle_meta(self, payload: dict[str, Any]) -> None:
        """处理生命周期与心跳事件，记录 self_id。"""
        event = payload.get("meta_event_type")
        if event in ("lifecycle", "heartbeat"):
            self_id = payload.get("self_id")
            if isinstance(self_id, int) and self_id:
                if self.self_id != self_id:
                    logger.info("登录账号：%s", self_id)
                self.self_id = self_id

    async def _drop(self, connection: _Connection, *, reason: str) -> None:
        """标记连接不可用并让所有等待中的调用失败。"""
        if connection.closed:
            return
        connection.closed = True
        for future in connection.pending.values():
            if not future.done():
                future.set_exception(OneBotError(f"连接断开：{reason}"))
        connection.pending.clear()
        if connection in self._connections:
            self._connections.remove(connection)
        try:
            await connection.socket.close()
        except Exception:  # 关闭失败无需处理
            logger.debug("关闭连接时出错", exc_info=True)
