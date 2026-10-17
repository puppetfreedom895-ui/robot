"""生命内核的持久化：状态、做过的事、日记、目标、token 额度。

和对话记忆分库：这里的记录是"它自己的经历"，不是聊天记录。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

from robot.life.state import LifeState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL DEFAULT '',
    energy REAL NOT NULL DEFAULT 80,
    mood TEXT NOT NULL DEFAULT '还行',
    boredom REAL NOT NULL DEFAULT 30,
    focus TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
    day TEXT PRIMARY KEY,
    tokens INTEGER NOT NULL DEFAULT 0
);
"""


class LifeStore:
    """同步 SQLite 的异步封装。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- 状态 ----

    async def load_state(self) -> LifeState:
        """读当前状态，没有记录时返回默认值。

        @returns: 自我状态。
        """
        return await asyncio.to_thread(self._load_state_sync)

    def _load_state_sync(self) -> LifeState:
        with self._lock:
            row = self._conn.execute(
                "SELECT name, energy, mood, boredom, focus, updated_at FROM state WHERE id = 1"
            ).fetchone()
        if row is None:
            return LifeState()
        return LifeState(
            name=row["name"] or "小七",
            energy=float(row["energy"]),
            mood=row["mood"],
            boredom=float(row["boredom"]),
            focus=row["focus"],
            updated_at=float(row["updated_at"]),
        )

    async def save_state(self, state: LifeState) -> None:
        """写入当前状态。

        @param state: 要保存的状态。
        """
        await asyncio.to_thread(self._save_state_sync, state)

    def _save_state_sync(self, state: LifeState) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO state(id, name, energy, mood, boredom, focus, updated_at) "
                "VALUES (1, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, energy=excluded.energy, "
                "mood=excluded.mood, boredom=excluded.boredom, focus=excluded.focus, "
                "updated_at=excluded.updated_at",
                (
                    state.name,
                    state.energy,
                    state.mood,
                    state.boredom,
                    state.focus,
                    time.time(),
                ),
            )
            self._conn.commit()

    # ---- 事件 ----

    async def add_event(self, kind: str, content: str) -> None:
        """记一条它做过的事。

        @param kind: 类别，如 act、idle、sleep、blocked。
        @param content: 内容。
        """
        await asyncio.to_thread(self._add_event_sync, kind, content)

    def _add_event_sync(self, kind: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(kind, content, created_at) VALUES (?, ?, ?)",
                (kind, content, time.time()),
            )
            self._conn.commit()

    async def recent_events(self, limit: int = 5) -> list[str]:
        """取最近做过的事，格式化成 "HH:MM 内容"。

        @param limit: 条数。
        @returns: 事件列表，按时间正序。
        """
        return await asyncio.to_thread(self._recent_events_sync, limit)

    def _recent_events_sync(self, limit: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, content, created_at FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            f"{time.strftime('%H:%M', time.localtime(row['created_at']))} {row['content']}"
            for row in reversed(rows)
        ]

    # ---- 日记 ----

    async def add_diary(self, day: str, content: str) -> None:
        """给某天加一行日记。

        @param day: 日期，如 2026-05-01。
        @param content: 一行内容。
        """
        await asyncio.to_thread(self._add_diary_sync, day, content)

    def _add_diary_sync(self, day: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO diary(day, content, created_at) VALUES (?, ?, ?)",
                (day, content, time.time()),
            )
            self._conn.commit()

    async def recent_diary(self, limit: int = 3) -> list[str]:
        """取最近几天的日记。

        @param limit: 天数。
        @returns: 形如 "2026-05-01：..." 的列表。
        """
        return await asyncio.to_thread(self._recent_diary_sync, limit)

    def _recent_diary_sync(self, limit: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT day, content FROM diary ORDER BY id DESC").fetchall()

        days: list[str] = []
        grouped: dict[str, list[str]] = {}
        for row in rows:
            day = str(row["day"])
            if day not in grouped:
                if len(days) >= limit:
                    continue
                grouped[day] = []
                days.append(day)
            grouped[day].append(str(row["content"]))

        # rows 是倒序，每天内部再翻回来，读起来像正常的时间线
        return [f"{day}：" + "；".join(reversed(grouped[day][:5])) for day in days]

    # ---- 目标 ----

    async def add_goal(self, text: str) -> None:
        """加一条它自己惦记的事。

        @param text: 目标内容。
        """
        await asyncio.to_thread(self._add_goal_sync, text)

    def _add_goal_sync(self, text: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO goals(text, created_at) VALUES (?, ?)", (text, time.time())
            )
            self._conn.commit()

    async def open_goals(self, limit: int = 3) -> list[str]:
        """取还没完成的惦记。

        @param limit: 条数。
        @returns: 目标文本列表。
        """
        return await asyncio.to_thread(self._open_goals_sync, limit)

    def _open_goals_sync(self, limit: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT text FROM goals WHERE status = 'open' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [str(row["text"]) for row in reversed(rows)]

    async def close_goal(self, text: str) -> None:
        """把某条惦记标记成已完成。

        @param text: 目标文本。
        """
        await asyncio.to_thread(self._close_goal_sync, text)

    def _close_goal_sync(self, text: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET status = 'done' WHERE text = ? AND status = 'open'", (text,)
            )
            self._conn.commit()

    # ---- 额度 ----

    async def tokens_on(self, day: str) -> int:
        """查某天已经花掉的 token。

        @param day: 日期。
        @returns: token 数。
        """
        return await asyncio.to_thread(self._tokens_on_sync, day)

    def _tokens_on_sync(self, day: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT tokens FROM ledger WHERE day = ?", (day,)).fetchone()
        return int(row["tokens"]) if row else 0

    async def note_tokens(self, day: str, tokens: int) -> int:
        """累加当天的 token 用量。

        @param day: 日期。
        @param tokens: 本次用量。
        @returns: 当天累计用量。
        """
        return await asyncio.to_thread(self._note_tokens_sync, day, tokens)

    def _note_tokens_sync(self, day: str, tokens: int) -> int:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ledger(day, tokens) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET tokens = tokens + excluded.tokens",
                (day, max(tokens, 0)),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT tokens FROM ledger WHERE day = ?", (day,)).fetchone()
        return int(row["tokens"]) if row else 0

    def close(self) -> None:
        """关闭连接。"""
        with self._lock:
            self._conn.close()
