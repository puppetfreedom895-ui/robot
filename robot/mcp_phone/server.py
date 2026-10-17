"""把手机能力暴露成 MCP 工具，供 DSH 大脑调用。

设计原则（直接决定 token 消耗）：
- 默认返回结构化界面，不返回图片；
- 每个动作默认顺带返回「界面变化」，一步一次调用，不额外多一轮；
- 截图只返回文件路径，图片不进入模型上下文。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from robot.phone import ui
from robot.phone.device import Device, DeviceError

SERVER_NAME = "phone"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL = "2025-06-18"

# 动作后等界面稳定的默认时长（秒）
SETTLE_SECONDS = 0.6

# 变化太多时改给整屏，免得模型拿到一堆增量拼不出画面
MAX_DIFF_LINES = 8


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """拼一个简单的 JSON Schema。

    @param properties: 字段定义。
    @param required: 必填字段。
    @returns: 对象 schema。
    """
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


TOOLS: list[dict[str, Any]] = [
    {
        "name": "phone_info",
        "description": "看手机现在的状态：机型、当前在哪个应用、电量。",
        "inputSchema": _schema({}),
    },
    {
        "name": "screen",
        "description": "看当前屏幕上有哪些元素，返回带编号的清单；操作时用这些编号。",
        "inputSchema": _schema(
            {
                "mode": {
                    "type": "string",
                    "enum": ["auto", "full", "diff"],
                    "description": "auto=有上次记录就给变化，full=给整屏。",
                }
            }
        ),
    },
    {
        "name": "tap",
        "description": "点屏幕上的东西，优先用 screen 返回的编号。",
        "inputSchema": _schema(
            {
                "index": {"type": "integer", "description": "screen 返回的编号"},
                "text": {"type": "string", "description": "按文字找元素并点它"},
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            }
        ),
    },
    {
        "name": "type_text",
        "description": "往当前输入框里打字。",
        "inputSchema": _schema(
            {
                "text": {"type": "string"},
                "enter": {"type": "boolean", "description": "打完是否按回车"},
                "clear": {"type": "boolean", "description": "先清空原内容"},
            },
            ["text"],
        ),
    },
    {
        "name": "swipe",
        "description": "滑动屏幕，用于翻页和滚动列表。",
        "inputSchema": _schema(
            {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "up=往下翻（内容上移）",
                }
            }
        ),
    },
    {
        "name": "press",
        "description": "按手机上的键：返回、桌面、任务列表等。",
        "inputSchema": _schema(
            {
                "key": {
                    "type": "string",
                    "enum": [
                        "back",
                        "home",
                        "recent",
                        "enter",
                        "wakeup",
                        "volume_up",
                        "volume_down",
                    ],
                }
            },
            ["key"],
        ),
    },
    {
        "name": "open_app",
        "description": "打开一个应用，可用中文名（微信、设置、B站…）或包名。",
        "inputSchema": _schema({"name": {"type": "string"}}, ["name"]),
    },
    {
        "name": "find",
        "description": "在当前界面按文字找元素，返回编号。",
        "inputSchema": _schema({"text": {"type": "string"}}, ["text"]),
    },
    {
        "name": "screenshot",
        "description": "截图存到服务器，只返回路径；平时不用，界面看不懂时再用。",
        "inputSchema": _schema({}),
    },
    {
        "name": "wait",
        "description": "等一下再继续，用于等页面加载。",
        "inputSchema": _schema(
            {"seconds": {"type": "number", "description": "秒数，最多 10"}},
            ["seconds"],
        ),
    },
]

TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS)


class PhoneServer:
    """处理 MCP 请求；只保存「上一次界面」用于做增量对比。"""

    def __init__(
        self,
        device: Device,
        *,
        data_dir: Path,
        max_chars: int = ui.DEFAULT_MAX_CHARS,
        max_nodes: int = ui.DEFAULT_MAX_NODES,
        settle: float = SETTLE_SECONDS,
    ) -> None:
        self._device = device
        self._data_dir = data_dir
        self._max_chars = max_chars
        self._max_nodes = max_nodes
        self._settle = settle
        self._last_nodes: list[ui.UiNode] | None = None
        self._last_package = ""
        self._shot_dir = data_dir / "screens"

    # ---- MCP 协议 ----

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """处理一条 JSON-RPC 请求。

        @param request: 解析后的请求对象。
        @returns: 响应对象；通知类请求返回 None。
        """
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params") or {}

        if request_id is None:
            return None  # 通知，不需要回复

        if method == "initialize":
            return _ok(
                request_id,
                {
                    "protocolVersion": str(params.get("protocolVersion") or DEFAULT_PROTOCOL),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )

        if method == "ping":
            return _ok(request_id, {})

        if method == "tools/list":
            return _ok(request_id, {"tools": TOOLS})

        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            return self._call_tool(
                request_id, name, arguments if isinstance(arguments, dict) else {}
            )

        return _error(request_id, -32601, f"不支持的方法：{method}")

    def _call_tool(self, request_id: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_tool_{name}", None) if name in TOOL_NAMES else None
        if handler is None:
            return _error(request_id, -32602, f"没有这个工具：{name}")
        try:
            text = handler(arguments)
        except DeviceError as exc:
            return _ok(
                request_id, {"content": [{"type": "text", "text": f"失败：{exc}"}], "isError": True}
            )
        except Exception as exc:  # 兜底：一次异常不该打断整条连接
            return _ok(
                request_id,
                {"content": [{"type": "text", "text": f"出错了：{exc}"}], "isError": True},
            )
        return _ok(request_id, {"content": [{"type": "text", "text": text}], "isError": False})

    # ---- 工具实现 ----

    def _tool_phone_info(self, _args: dict[str, Any]) -> str:
        info = self._device.info()
        return (
            f"{info.get('brand')} {info.get('model')} / 安卓 {info.get('android')} / "
            f"电量 {info.get('battery')}%\n"
            f"前台：{info.get('package')} ({info.get('activity')})"
        )

    def _tool_screen(self, args: dict[str, Any]) -> str:
        mode = str(args.get("mode") or "auto")
        previous = self._last_nodes
        nodes, header = self._observe()
        self._last_nodes = nodes

        if mode in ("auto", "diff") and previous is not None and nodes:
            diff = ui.diff_nodes(previous, nodes)
            if "没有变化" in diff or diff.count("\n") <= MAX_DIFF_LINES:
                return f"{header}\n{diff}"

        return ui.format_screen(nodes, header=header, max_chars=self._max_chars, total=len(nodes))

    def _tool_tap(self, args: dict[str, Any]) -> str:
        target = self._resolve_target(args)
        self._device.tap(*target)
        return self._after_action(f"点了 ({target[0]},{target[1]})")

    def _tool_type_text(self, args: dict[str, Any]) -> str:
        text = str(args.get("text") or "")
        if not text:
            raise DeviceError("没有要输入的内容")
        self._device.type_text(text, enter=bool(args.get("enter")), clear=bool(args.get("clear")))
        return self._after_action(f"输入了「{text}」")

    def _tool_swipe(self, args: dict[str, Any]) -> str:
        direction = str(args.get("direction") or "up")
        width, height = self._screen_size()
        cx, cy = width // 2, height // 2
        delta = height // 3
        coords = {
            "up": (cx, cy + delta, cx, cy - delta),
            "down": (cx, cy - delta, cx, cy + delta),
            "left": (width - 100, cy, 100, cy),
            "right": (100, cy, width - 100, cy),
        }.get(direction)
        if coords is None:
            raise DeviceError(f"不认识的滑动方向：{direction}")
        self._device.swipe(*coords, 0.3)
        return self._after_action(f"往{direction}滑了一下")

    def _tool_press(self, args: dict[str, Any]) -> str:
        key = str(args.get("key") or "")
        self._device.press(key)
        return self._after_action(f"按了 {key}")

    def _tool_open_app(self, args: dict[str, Any]) -> str:
        name = str(args.get("name") or "")
        if not name:
            raise DeviceError("没说要打开什么")
        self._device.open_app(name)
        time.sleep(max(self._settle, 0.8))  # 应用启动比普通界面切换慢
        return self._after_action(f"打开了 {name}")

    def _tool_find(self, args: dict[str, Any]) -> str:
        needle = str(args.get("text") or "")
        nodes, header = self._observe()
        hits = [node for node in nodes if needle and needle in node.label]
        if not hits:
            return f"{header}\n没找到「{needle}」"
        return "\n".join([header, *(ui.format_node(node) for node in hits[:10])])

    def _tool_screenshot(self, _args: dict[str, Any]) -> str:
        self._shot_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self._device.screenshot(self._shot_dir / f"{stamp}.png")
        return f"截图已存到 {path}（图片不进上下文，要看就说一声）"

    def _tool_wait(self, args: dict[str, Any]) -> str:
        seconds = min(float(args.get("seconds") or 1.0), 10.0)
        time.sleep(max(seconds, 0.0))
        return f"等了 {seconds:g} 秒"

    # ---- 内部 ----

    def _after_action(self, done: str) -> str:
        """动作回执：一句话 + 界面变化，省掉模型再调一次 screen 的往返。"""
        time.sleep(self._settle)
        previous = self._last_nodes
        previous_package = self._last_package
        nodes, header = self._observe()
        self._last_nodes = nodes
        self._last_package = self._current_package

        if previous is None or self._current_package != previous_package:
            body = ui.format_screen(nodes, header="", max_chars=self._max_chars, total=len(nodes))
        else:
            diff = ui.diff_nodes(previous, nodes)
            if diff.count("\n") > MAX_DIFF_LINES:
                body = ui.format_screen(
                    nodes, header="", max_chars=self._max_chars, total=len(nodes)
                )
            else:
                body = diff
        return f"{done}。\n{header}\n{body}"

    def _observe(self) -> tuple[list[ui.UiNode], str]:
        """读一次界面并生成首行信息，不改缓存。

        @returns: (元素列表, 首行信息)。
        """
        xml = self._device.dump()
        info = self._device.info()
        self._current_package = str(info.get("package") or "")
        nodes = ui.parse_hierarchy(xml, max_nodes=self._max_nodes)
        header = (
            f"{self._current_package or '未知应用'} {time.strftime('%H:%M')}｜{len(nodes)} 个元素"
        )
        return nodes, header

    def _resolve_target(self, args: dict[str, Any]) -> tuple[int, int]:
        """把 index / text / 坐标解析成点击坐标。

        @param args: 工具参数。
        @returns: (x, y)。
        @raises DeviceError: 无法确定目标。
        """
        if isinstance(args.get("x"), int) and isinstance(args.get("y"), int):
            return int(args["x"]), int(args["y"])

        nodes = self._last_nodes
        if nodes is None:
            nodes, _ = self._observe()
            self._last_nodes = nodes

        index = args.get("index")
        if isinstance(index, int):
            for node in nodes or []:
                if node.index == index:
                    return node.center
            raise DeviceError(f"编号 {index} 不在当前界面里，先调 screen 看看")

        text = str(args.get("text") or "")
        if text:
            for node in nodes or []:
                if text in node.label:
                    return node.center
            raise DeviceError(f"界面上没有「{text}」")

        raise DeviceError("要么给 index，要么给 text，要么给 x/y")

    def _screen_size(self) -> tuple[int, int]:
        info = self._device.info()
        try:
            return int(info.get("width") or 1080), int(info.get("height") or 2400)
        except (TypeError, ValueError):
            return 1080, 2400


def _ok(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def build_device_from_env() -> Device:
    """按环境变量决定用真机还是假设备。

    @returns: 设备对象。
    @raises DeviceError: 真机连不上。
    """
    if os.environ.get("PHONE_FAKE") == "1":
        from robot.phone.device import FakeDevice

        return FakeDevice()

    from robot.phone.uiautomator import UiautomatorDevice

    return UiautomatorDevice(os.environ.get("PHONE_SERIAL") or None)


def main() -> int:
    """stdio 模式主循环：一行一个 JSON-RPC 消息。

    @returns: 进程退出码。
    """
    data_dir = Path(os.environ.get("PHONE_DATA_DIR", "data")).resolve()
    max_chars = int(os.environ.get("PHONE_MAX_CHARS", str(ui.DEFAULT_MAX_CHARS)))

    try:
        device = build_device_from_env()
    except DeviceError as exc:
        print(f"[phone-mcp] 启动失败：{exc}", file=sys.stderr)
        return 1

    server = PhoneServer(device, data_dir=data_dir, max_chars=max_chars)
    print(f"[phone-mcp] 就绪，设备={getattr(device, 'serial', '?')}", file=sys.stderr)

    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "解析失败"}})
            continue
        if not isinstance(request, dict):
            _write(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "请求格式不对"}}
            )
            continue

        response = server.handle(request)
        if response is not None:
            _write(response)

    return 0


def _write(payload: dict[str, Any]) -> None:
    """往 stdout 写一帧；stdout 只走协议数据，日志一律走 stderr。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
