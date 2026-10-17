"""手机 MCP 服务端：协议、工具调用与回执长度。"""

from __future__ import annotations

import json

from robot.mcp_phone.server import TOOLS, PhoneServer
from robot.phone.device import FakeDevice
from tests.test_ui import SCREEN_XML

CLOCK_XML = SCREEN_XML.replace("WLAN", "蓝牙")


def make_server(tmp_path, screens=None):
    device = FakeDevice(screens or [SCREEN_XML, SCREEN_XML])
    return PhoneServer(device, data_dir=tmp_path, settle=0.0), device


def call(server, name, arguments=None, request_id=1):
    return server.handle(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )


def text_of(response) -> str:
    return response["result"]["content"][0]["text"]


def test_initialize_echoes_protocol_version(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2026-07-28", "capabilities": {}},
        }
    )
    assert response["result"]["protocolVersion"] == "2026-07-28"
    assert "tools" in response["result"]["capabilities"]
    assert response["result"]["serverInfo"]["name"] == "phone"


def test_notification_gets_no_response(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_matches_declarations(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == [tool["name"] for tool in TOOLS]
    assert "screen" in names and "tap" in names


def test_unknown_tool_returns_error(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    response = call(server, "launch_rocket")
    assert response["error"]["code"] == -32602


def test_screen_returns_numbered_elements(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    body = text_of(call(server, "screen"))
    assert "com.example.app" in body
    assert "#1 输入框「搜索设置」" in body
    assert "#3 按钮「关闭」" in body


def test_screen_second_call_reports_no_change(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    call(server, "screen")
    assert "没有变化" in text_of(call(server, "screen"))


def test_tap_by_index_uses_cached_bounds(tmp_path) -> None:
    server, device = make_server(tmp_path)
    call(server, "screen")
    call(server, "tap", {"index": 2})
    taps = [payload for name, payload in device.calls if name == "tap"]
    assert taps == [{"x": 540, "y": 350}]


def test_tap_by_text_finds_element(tmp_path) -> None:
    server, device = make_server(tmp_path)
    call(server, "screen")
    call(server, "tap", {"text": "关闭"})
    taps = [payload for name, payload in device.calls if name == "tap"]
    assert taps == [{"x": 900, "y": 550}]


def test_tap_unknown_index_fails_clearly(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    call(server, "screen")
    response = call(server, "tap", {"index": 99})
    assert response["result"]["isError"] is True
    assert "编号 99" in text_of(response)


def test_tap_without_target_fails(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    response = call(server, "tap", {})
    assert response["result"]["isError"] is True


def test_type_text_forwards_flags(tmp_path) -> None:
    server, device = make_server(tmp_path)
    call(server, "type_text", {"text": "你好", "enter": True, "clear": True})
    calls = [payload for name, payload in device.calls if name == "type_text"]
    assert calls == [{"text": "你好", "enter": True, "clear": True}]


def test_type_text_rejects_empty(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    response = call(server, "type_text", {"text": ""})
    assert response["result"]["isError"] is True


def test_action_receipt_stays_small(tmp_path) -> None:
    """动作回执是每步都进上下文的东西，必须短。"""
    server, _ = make_server(tmp_path, screens=[SCREEN_XML, SCREEN_XML])
    call(server, "screen")
    body = text_of(call(server, "tap", {"index": 3}))
    assert len(body) < 300


def test_open_app_and_press_are_forwarded(tmp_path) -> None:
    server, device = make_server(tmp_path)
    call(server, "open_app", {"name": "设置"})
    call(server, "press", {"key": "back"})
    names = [name for name, _payload in device.calls]
    assert "open_app" in names
    assert "press" in names


def test_swipe_uses_screen_size(tmp_path) -> None:
    server, device = make_server(tmp_path)
    call(server, "swipe", {"direction": "up"})
    swipes = [payload for name, payload in device.calls if name == "swipe"]
    assert swipes[0]["x1"] == 540
    assert swipes[0]["y1"] > swipes[0]["y2"]


def test_screenshot_returns_path_only(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    body = text_of(call(server, "screenshot"))
    assert "screens" in body
    assert "base64" not in body
    saved = list((tmp_path / "screens").glob("*.png"))
    assert len(saved) == 1


def test_find_reports_hits(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    body = text_of(call(server, "find", {"text": "关闭"}))
    assert "关闭" in body


def test_find_reports_miss(tmp_path) -> None:
    server, _ = make_server(tmp_path)
    body = text_of(call(server, "find", {"text": "不存在的按钮"}))
    assert "没找到" in body


def test_stdio_frames_are_single_line_json(tmp_path) -> None:
    """stdio 传输要求一帧一行，换行必须被转义。"""
    server, _ = make_server(tmp_path)
    response = call(server, "screen")
    encoded = json.dumps(response, ensure_ascii=False)
    assert "\n" not in encoded
