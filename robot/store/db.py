"""SQLite 持久化：会话消息、滚动摘要、长期事实。

单连接 + 线程锁 + asyncio.to_thread，避免引入额外的异步驱动依赖，
也避免每次读写都开连接。
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key, id);

CREATE TABLE IF NOT EXISTS sessions (
    session_key TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    ts REAL NOT NULL,
    UNIQUE(scope, content)
);
"""


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """一条落库的消息。"""

    id: int
    role: str
    name: str
    content: str


class Database:
    """同步 SQLite 的异步封装。所有公开方法都是协程。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- 消息 ----

    async def append(self, session_key: str, role: str, name: str, content: str) -> None:
        """追加一条消息。

        @param session_key: 会话键。
        @param role: "user" 或 "assistant"。
        @param name: 说话人显示名。
        @param content: 文本内容。
        """
        await asyncio.to_thread(self._append_sync, session_key, role, name, content)

    def _append_sync(self, session_key: str, role: str, name: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(session_key, role, name, content, ts) VALUES (?,?,?,?,?)",
                (session_key, role, name, content, time.time()),
            )
            self._conn.commit()

    async def recent(self, session_key: str, limit: int) -> list[StoredMessage]:
        """取最近 N 条消息，按时间正序返回。

        @param session_key: 会话键。
        @param limit: 条数上限。
        @returns: 消息列表，索引 0 最早。
        """
        return await asyncio.to_thread(self._recent_sync, session_key, limit)

    def _recent_sync(self, session_key: str, limit: int) -> list[StoredMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, name, content FROM messages "
                "WHERE session_key = ? ORDER BY id DESC LIMIT ?",
                (session_key, limit),
            ).fetchall()
        return [StoredMessage(r["id"], r["role"], r["name"], r["content"]) for r in reversed(rows)]

    async def oldest(self, session_key: str, limit: int) -> list[StoredMessage]:
        """取最早的 N 条消息（摘要压缩用）。

        @param session_key: 会话键。
        @param limit: 条数上限。
        @returns: 消息列表，索引 0 最早。
        """
        return await asyncio.to_thread(self._oldest_sync, session_key, limit)

    def _oldest_sync(self, session_key: str, limit: int) -> list[StoredMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, role, name, content FROM messages "
                "WHERE session_key = ? ORDER BY id ASC LIMIT ?",
                (session_key, limit),
            ).fetchall()
        return [StoredMessage(r["id"], r["role"], r["name"], r["content"]) for r in rows]

    async def count(self, session_key: str) -> int:
        """统计会话消息数。

        @param session_key: 会话键。
        @returns: 条数。
        """
        return await asyncio.to_thread(self._count_sync, session_key)

    def _count_sync(self, session_key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE session_key = ?", (session_key,)
            ).fetchone()
        return int(row["n"])

    async def delete_through(self, session_key: str, message_id: int) -> int:
        """删除某会话中 id 不大于给定值的消息（摘要后清账用）。

        @param session_key: 会话键。
        @param message_id: 边界 id。
        @returns: 删除条数。
        """
        return await asyncio.to_thread(self._delete_through_sync, session_key, message_id)

    def _delete_through_sync(self, session_key: str, message_id: int) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM messages WHERE session_key = ? AND id <= ?",
                (session_key, message_id),
            )
            self._conn.commit()
            return cursor.rowcount

    async def clear(self, session_key: str) -> None:
        """清空某会话的消息与摘要。

        @param session_key: 会话键。
        """
        await asyncio.to_thread(self._clear_sync, session_key)

    def _clear_sync(self, session_key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_key = ?", (session_key,))
            self._conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))
            self._conn.commit()

    # ---- 摘要 ----

    async def get_summary(self, session_key: str) -> str:
        """取会话的滚动摘要。

        @param session_key: 会话键。
        @returns: 摘要文本，没有则为空串。
        """
        return await asyncio.to_thread(self._get_summary_sync, session_key)

    def _get_summary_sync(self, session_key: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT summary FROM sessions WHERE session_key = ?", (session_key,)
            ).fetchone()
        return str(row["summary"]) if row else ""

    async def set_summary(self, session_key: str, summary: str) -> None:
        """写入会话摘要。

        @param session_key: 会话键。
        @param summary: 摘要文本。
        """
        await asyncio.to_thread(self._set_summary_sync, session_key, summary)

    def _set_summary_sync(self, session_key: str, summary: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions(session_key, summary, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(session_key) DO UPDATE SET summary=excluded.summary, "
                "updated_at=excluded.updated_at",
                (session_key, summary, time.time()),
            )
            self._conn.commit()

    # ---- 长期事实 ----

    async def add_fact(self, scope: str, content: str) -> bool:
        """记录一条长期事实，重复内容会被忽略。

        @param scope: 作用域，例如 "group:123" 或 "user:456"。
        @param content: 事实内容。
        @returns: 新增成功为 True，已存在为 False。
        """
        return await asyncio.to_thread(self._add_fact_sync, scope, content)

    def _add_fact_sync(self, scope: str, content: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO facts(scope, content, ts) VALUES (?,?,?)",
                (scope, content, time.time()),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    async def facts(self, scope: str, limit: int = 50) -> list[str]:
        """读取某作用域下的长期事实。

        @param scope: 作用域。
        @param limit: 条数上限。
        @returns: 事实文本列表。
        """
        return await asyncio.to_thread(self._facts_sync, scope, limit)

    def _facts_sync(self, scope: str, limit: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT content FROM facts WHERE scope = ? ORDER BY id DESC LIMIT ?",
                (scope, limit),
            ).fetchall()
        return [str(r["content"]) for r in reversed(rows)]

    async def clear_facts(self, scope: str) -> None:
        """清空某作用域下的长期事实。

        @param scope: 作用域。
        """
        await asyncio.to_thread(self._clear_facts_sync, scope)

    def _clear_facts_sync(self, scope: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM facts WHERE scope = ?", (scope,))
            self._conn.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        with self._lock:
            self._conn.close()
