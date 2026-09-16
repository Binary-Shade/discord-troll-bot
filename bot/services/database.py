"""SQLite persistence layer with async method boundaries.

Stores only what's needed for behavior: per-channel enable state, per-server
humor mode/cooldown overrides, opt-outs, and a small rolling log of "running
jokes" / notable exchanges. Message content is NOT stored indefinitely —
conversation context is kept in-memory (see context_manager.py) and only
short joke summaries are persisted here.
"""
import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_settings (
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    humor_mode TEXT NOT NULL DEFAULT 'genz_commentator',
    response_probability REAL NOT NULL DEFAULT 0.35,
    cooldown_seconds INTEGER NOT NULL DEFAULT 8
);

CREATE TABLE IF NOT EXISTS opt_outs (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS running_jokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    async def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    # ---- channel settings ----
    async def is_channel_enabled(self, guild_id: int, channel_id: int) -> bool:
        async with self._lock:
            cur = self._require_conn().execute(
                "SELECT enabled FROM channel_settings WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            )
            row = cur.fetchone()
            return bool(row[0]) if row else True

    async def set_channel_enabled(self, guild_id: int, channel_id: int, enabled: bool):
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                """INSERT INTO channel_settings (guild_id, channel_id, enabled)
                   VALUES (?, ?, ?)
                   ON CONFLICT(guild_id, channel_id) DO UPDATE SET enabled=excluded.enabled""",
                (guild_id, channel_id, int(enabled)),
            )
            conn.commit()

    # ---- guild settings ----
    async def get_guild_settings(self, guild_id: int) -> dict:
        async with self._lock:
            cur = self._require_conn().execute(
                "SELECT humor_mode, response_probability, cooldown_seconds FROM guild_settings WHERE guild_id=?",
                (guild_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"humor_mode": "genz_commentator", "response_probability": 0.35, "cooldown_seconds": 8}
            return {"humor_mode": row[0], "response_probability": row[1], "cooldown_seconds": row[2]}

    async def update_guild_settings(self, guild_id: int, **kwargs):
        async with self._lock:
            conn = self._require_conn()
            cur = conn.execute(
                "SELECT humor_mode, response_probability, cooldown_seconds FROM guild_settings WHERE guild_id=?",
                (guild_id,),
            )
            row = cur.fetchone()
            current = (
                {"humor_mode": row[0], "response_probability": row[1], "cooldown_seconds": row[2]}
                if row
                else {"humor_mode": "genz_commentator", "response_probability": 0.35, "cooldown_seconds": 8}
            )
            current.update(kwargs)
            conn.execute(
                """INSERT INTO guild_settings (guild_id, humor_mode, response_probability, cooldown_seconds)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET
                     humor_mode=excluded.humor_mode,
                     response_probability=excluded.response_probability,
                     cooldown_seconds=excluded.cooldown_seconds""",
                (guild_id, current["humor_mode"], current["response_probability"], current["cooldown_seconds"]),
            )
            conn.commit()

    # ---- opt-outs ----
    async def opt_out(self, guild_id: int, user_id: int):
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                "INSERT OR IGNORE INTO opt_outs (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id)
            )
            conn.commit()

    async def opt_in(self, guild_id: int, user_id: int):
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                "DELETE FROM opt_outs WHERE guild_id=? AND user_id=?", (guild_id, user_id)
            )
            conn.commit()

    async def is_opted_out(self, guild_id: int, user_id: int) -> bool:
        async with self._lock:
            cur = self._require_conn().execute(
                "SELECT 1 FROM opt_outs WHERE guild_id=? AND user_id=?", (guild_id, user_id)
            )
            return cur.fetchone() is not None

    # ---- running jokes (lightweight memory) ----
    async def add_running_joke(self, guild_id: int, summary: str, max_keep: int = 25):
        async with self._lock:
            conn = self._require_conn()
            conn.execute(
                "INSERT INTO running_jokes (guild_id, summary, created_at) VALUES (?, ?, ?)",
                (guild_id, summary, time.time()),
            )
            # prune to most recent max_keep per guild
            conn.execute(
                """DELETE FROM running_jokes WHERE guild_id=? AND id NOT IN (
                     SELECT id FROM running_jokes WHERE guild_id=? ORDER BY id DESC LIMIT ?
                   )""",
                (guild_id, guild_id, max_keep),
            )
            conn.commit()

    async def get_running_jokes(self, guild_id: int, limit: int = 8) -> list[str]:
        async with self._lock:
            cur = self._require_conn().execute(
                "SELECT summary FROM running_jokes WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (guild_id, limit),
            )
            rows = cur.fetchall()
            return [r[0] for r in rows]

    async def clear_memory(self, guild_id: int):
        async with self._lock:
            conn = self._require_conn()
            conn.execute("DELETE FROM running_jokes WHERE guild_id=?", (guild_id,))
            conn.commit()
