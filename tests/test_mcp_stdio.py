"""端到端：真的把 MCP 服务端当子进程跑起来，走 stdio 协议。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_server(frames: list[dict]) -> list[dict]:
    """启动子进程，喂若干帧，回收响应。

    @param frames: 要发送的 JSON-RPC 请求。
    @returns: 解析后的响应列表。
    """
    payload = "".join(json.dumps(frame, ensure_ascii=False) + "\n" for frame in frames)
    env = dict(os.environ, PHONE_FAKE="1", PHONE_DATA_DIR=str(ROOT / "pytest-of-fake" / "phone"))
    completed = subprocess.run(
        [sys.executable, "-m", "robot.mcp_phone"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def test_initialize_and_list_tools_over_stdio() -> None:
    responses = run_server(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2026-07-28", "capabilities": {}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )

    assert len(responses) == 2  # 通知不产生响应
    assert responses[0]["result"]["serverInfo"]["name"] == "phone"
    assert "screen" in [tool["name"] for tool in responses[1]["result"]["tools"]]


def test_tool_call_over_stdio_returns_text() -> None:
    responses = run_server(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "phone_info", "arguments": {}},
            }
        ]
    )
    assert responses[0]["result"]["isError"] is False
    assert "Fake" in responses[0]["result"]["content"][0]["text"]


def test_broken_frame_does_not_kill_server() -> None:
    env = dict(os.environ, PHONE_FAKE="1", PHONE_DATA_DIR=str(ROOT / "pytest-of-fake" / "phone"))
    payload = "这不是 JSON\n" + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + "\n"
    completed = subprocess.run(
        [sys.executable, "-m", "robot.mcp_phone"],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
        timeout=60,
        check=False,
    )
    lines = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["id"] == 3
