"""只读管理台：快照、令牌校验与路径防护。"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from robot.life.state import LifeState
from robot.life.store import LifeStore
from robot.web.dashboard import Dashboard


def http_get(url: str) -> tuple[int, bytes]:
    """发一个 GET，返回状态码和正文，4xx 也让测试拿到。

    @param url: 完整地址。
    @returns: (状态码, 正文字节)。
    """
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def seed(store: LifeStore) -> None:
    """塞一点可读的数据进去。"""
    today = time.strftime("%Y-%m-%d")
    asyncio.run(store.save_state(LifeState(energy=70, boredom=20, mood="不错", focus="想学做饭")))
    asyncio.run(store.add_event("act", "看了会儿剧"))
    asyncio.run(store.add_event("talk", "主人：在干嘛"))
    asyncio.run(store.add_diary(today, "14:00 看了会儿剧"))
    asyncio.run(store.add_goal("把剧看完"))
    asyncio.run(store.note_tokens(today, 1234))


def make_board(tmp_path: Path, *, token: str = "") -> tuple[Dashboard, LifeStore]:
    """起一个监听随机端口的管理台。"""
    store = LifeStore(tmp_path / "life.db")
    seed(store)
    screens = tmp_path / "screens"
    screens.mkdir()
    (screens / "20260101-120000.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    board = Dashboard(store, port=0, token=token, screens_dir=screens)
    board.start()
    return board, store


@pytest.fixture
def board(tmp_path):
    dashboard, store = make_board(tmp_path)
    yield dashboard, store
    dashboard.stop()
    store.close()


# ---- 快照 ----


def test_snapshot_has_state_events_diary_goals(tmp_path) -> None:
    store = LifeStore(tmp_path / "life.db")
    seed(store)
    snap = store.snapshot()

    assert snap["state"]["energy"] == 70
    assert snap["state"]["focus"] == "想学做饭"
    assert any("看了会儿剧" in item["content"] for item in snap["events"])
    assert snap["goals"] == ["把剧看完"]
    assert snap["diary"] and snap["diary"][0]["lines"]
    assert snap["tokens_today"] == 1234
    store.close()


def test_snapshot_is_safe_on_empty_database(tmp_path) -> None:
    store = LifeStore(tmp_path / "empty.db")
    snap = store.snapshot()
    assert snap["state"]["name"] == "小七"
    assert snap["events"] == []
    assert snap["goals"] == []
    store.close()


# ---- HTTP ----


def test_index_page_is_served(board) -> None:
    dashboard, _store = board
    status, body = http_get(f"http://127.0.0.1:{dashboard.port}/")
    assert status == 200
    assert "它今天干了什么".encode() in body


def test_api_snapshot_returns_json(board) -> None:
    dashboard, _store = board
    status, body = http_get(f"http://127.0.0.1:{dashboard.port}/api/snapshot")
    assert status == 200
    payload = json.loads(body)
    assert payload["state"]["mood"] == "不错"
    assert payload["events"]


def test_healthz_needs_no_token(tmp_path) -> None:
    dashboard, store = make_board(tmp_path, token="s3cret")
    try:
        status, body = http_get(f"http://127.0.0.1:{dashboard.port}/healthz")
        assert status == 200
        assert body == b"ok"
    finally:
        dashboard.stop()
        store.close()


def test_token_is_enforced(tmp_path) -> None:
    dashboard, store = make_board(tmp_path, token="s3cret")
    base = f"http://127.0.0.1:{dashboard.port}"
    try:
        assert http_get(f"{base}/api/snapshot")[0] == 401
        assert http_get(f"{base}/api/snapshot?t=wrong")[0] == 401
        assert http_get(f"{base}/api/snapshot?t=s3cret")[0] == 200
        assert http_get(f"{base}/?t=s3cret")[0] == 200
    finally:
        dashboard.stop()
        store.close()


def test_unknown_path_is_404(board) -> None:
    dashboard, _store = board
    assert http_get(f"http://127.0.0.1:{dashboard.port}/nope")[0] == 404


def test_screenshot_is_served(board) -> None:
    dashboard, _store = board
    status, body = http_get(f"http://127.0.0.1:{dashboard.port}/api/shot/20260101-120000.png")
    assert status == 200
    assert body.startswith(b"\x89PNG")


def test_screenshot_list(board) -> None:
    dashboard, _store = board
    status, body = http_get(f"http://127.0.0.1:{dashboard.port}/api/shots")
    assert status == 200
    assert json.loads(body)["shots"] == ["20260101-120000.png"]


def test_path_traversal_is_blocked(board) -> None:
    dashboard, _store = board
    base = f"http://127.0.0.1:{dashboard.port}"
    assert http_get(f"{base}/api/shot/..%2f..%2flife.db")[0] == 404
    assert http_get(f"{base}/api/shot/%2e%2e%2fsecret.png")[0] == 404


def test_non_png_is_rejected(board) -> None:
    dashboard, _store = board
    status, _body = http_get(f"http://127.0.0.1:{dashboard.port}/api/shot/secret.txt")
    assert status == 404


def test_dashboard_reports_assigned_port(board) -> None:
    dashboard, _store = board
    assert dashboard.port > 0
    assert dashboard.running is True
