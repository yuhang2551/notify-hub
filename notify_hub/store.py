"""发件箱：每条消息先写进 SQLite，再发送。断网、程序崩了都不丢，下次 flush 接着发。

状态：
- pending  等着发（新消息，或者失败后等下一次重试）
- sending  某个进程正在发；超过 5 分钟还没结果就当它崩了，重新可以发
- sent     发出去了
- digest   进了汇总（digest 级别，或者被限流）
- skipped  重复，没有发
- failed   重试太久，放弃了
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .models import Level, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    source TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    link TEXT,
    msg_key TEXT,
    dedup_key TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL,
    claimed_at REAL,
    sent_at REAL,
    last_error TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_due ON messages (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_messages_dedup ON messages (dedup_key, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages (source, created_at);
"""

STALE_SENDING = 300  # 秒：sending 超过这么久没结果，当成发送的进程崩了


class Outbox:
    def __init__(self, path: Path | str):
        self.path = path
        if str(path) != ":memory:":
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # 先按 600 建好文件，里面有消息内容，只给自己读
            os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
            os.chmod(path, 0o600)
        self.conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 10000")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- 写入 ----

    def add(self, msg: Message, *, dedup_key: str, status: str, now: float, note: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (created_at, source, level, title, body, link, msg_key, dedup_key, status, next_attempt_at, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now, msg.source, msg.level.value, msg.title, msg.body, msg.link, msg.key, dedup_key, status,
             now if status == "pending" else None, note),
        )
        return int(cur.lastrowid)

    def claim(self, message_id: int, now: float) -> bool:
        """把一条 pending（或卡住的 sending）标成 sending。返回 False 说明别的进程已经拿走了。"""
        cur = self.conn.execute(
            "UPDATE messages SET status = 'sending', claimed_at = ?"
            " WHERE id = ? AND (status = 'pending' OR (status = 'sending' AND claimed_at < ?))",
            (now, message_id, now - STALE_SENDING),
        )
        return cur.rowcount == 1

    def mark_sent(self, message_id: int, now: float) -> None:
        self.conn.execute(
            "UPDATE messages SET status = 'sent', sent_at = ?, attempts = attempts + 1, last_error = NULL WHERE id = ?",
            (now, message_id),
        )

    def mark_retry(self, message_id: int, *, error: str, next_attempt_at: float) -> None:
        self.conn.execute(
            "UPDATE messages SET status = 'pending', attempts = attempts + 1, last_error = ?, next_attempt_at = ? WHERE id = ?",
            (error, next_attempt_at, message_id),
        )

    def give_up_older_than(self, cutoff: float) -> int:
        cur = self.conn.execute(
            "UPDATE messages SET status = 'failed', note = '重试太久，放弃'"
            " WHERE status IN ('pending', 'sending') AND created_at < ?",
            (cutoff,),
        )
        return cur.rowcount

    # ---- 查询 ----

    def get(self, message_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()

    def recent_duplicate(self, dedup_key: str, since: float) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM messages WHERE dedup_key = ? AND created_at >= ?"
            " AND status IN ('pending', 'sending', 'sent', 'digest') ORDER BY id DESC LIMIT 1",
            (dedup_key, since),
        ).fetchone()

    def pushed_count(self, source: str, since: float) -> int:
        """这个来源最近推了（或正在推）几条，限流用。进汇总、重复、放弃的不算。"""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE source = ? AND created_at >= ? AND status IN ('pending', 'sending', 'sent')",
            (source, since),
        ).fetchone()
        return int(row[0])

    def due(self, now: float, limit: int = 50) -> list[int]:
        rows = self.conn.execute(
            "SELECT id FROM messages WHERE (status = 'pending' AND next_attempt_at <= ?)"
            " OR (status = 'sending' AND claimed_at < ?) ORDER BY id LIMIT ?",
            (now, now - STALE_SENDING, limit),
        ).fetchall()
        return [int(r[0]) for r in rows]

    def counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.conn.execute("SELECT status, COUNT(*) AS n FROM messages GROUP BY status")}

    def recent_problems(self, limit: int = 5) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM messages WHERE status IN ('pending', 'sending', 'failed') AND last_error IS NOT NULL"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def oldest_waiting(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM messages WHERE status IN ('pending', 'sending') ORDER BY created_at LIMIT 1"
        ).fetchone()


def row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        title=row["title"],
        body=row["body"],
        level=Level(row["level"]),
        source=row["source"],
        link=row["link"],
        key=row["msg_key"],
        created_at=row["created_at"],
    )
