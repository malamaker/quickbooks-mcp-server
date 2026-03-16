"""SQLite database layer using aiosqlite with WAL mode."""

import os
import aiosqlite
import bcrypt
from datetime import datetime, timezone
from pathlib import Path
from crypto import encrypt, decrypt

_db_path = None


def get_db_path() -> str:
    global _db_path
    if _db_path is None:
        data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        _db_path = str(data_dir / "quickbooks_mcp.db")
    return _db_path


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_db_path(), timeout=30)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = aiosqlite.Row
    return db


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS scheduler_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL DEFAULT 0,
    schedule_cron TEXT NOT NULL DEFAULT '0 23 * * *',
    anthropic_api_key TEXT,
    last_run_at TEXT,
    last_run_status TEXT,
    last_run_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL CHECK (rule_type IN (
        'vendor_category', 'always_ignore', 'threshold_flag', 'personal_card_exclude'
    )),
    pattern TEXT NOT NULL,
    category TEXT,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'learned')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL DEFAULT (datetime('now')),
    triggered_by TEXT NOT NULL CHECK (triggered_by IN ('scheduler', 'manual')),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    transactions_processed INTEGER DEFAULT 0,
    transactions_categorized INTEGER DEFAULT 0,
    transactions_flagged INTEGER DEFAULT 0,
    summary_text TEXT,
    duration_seconds REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS flagged_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES run_history(id),
    transaction_id TEXT,
    transaction_date TEXT,
    vendor TEXT,
    amount REAL,
    reason_flagged TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved', 'ignored')),
    resolved_at TEXT,
    resolution_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title TEXT NOT NULL DEFAULT 'New Conversation',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool_call', 'tool_result')),
    content TEXT NOT NULL,
    tool_name TEXT,
    tool_call_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db():
    """Create all tables and seed defaults."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA_SQL)

        # Seed default admin user if none exist
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        if row[0] == 0:
            pw_hash = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
            await db.execute(
                "INSERT INTO users (username, password_hash, must_change_password) VALUES (?, ?, 1)",
                ("admin", pw_hash),
            )

        # Seed default scheduler_config row
        cursor = await db.execute("SELECT COUNT(*) FROM scheduler_config")
        row = await cursor.fetchone()
        if row[0] == 0:
            await db.execute(
                "INSERT INTO scheduler_config (id, enabled, schedule_cron) VALUES (1, 0, '0 23 * * *')"
            )

        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def get_user(username: str) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def verify_password(username: str, password: str) -> dict | None:
    user = await get_user(username)
    if user and bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        db = await get_db()
        try:
            await db.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), user["id"]),
            )
            await db.commit()
        finally:
            await db.close()
        return user
    return None


async def change_password(user_id: int, new_password: str):
    pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (pw_hash, user_id),
        )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Scheduler Config
# ---------------------------------------------------------------------------

async def get_scheduler_config() -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM scheduler_config WHERE id = 1")
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            if d.get("anthropic_api_key"):
                try:
                    d["anthropic_api_key"] = decrypt(d["anthropic_api_key"])
                except Exception:
                    pass
            return d
        return None
    finally:
        await db.close()


async def update_scheduler_config(**kwargs):
    db = await get_db()
    try:
        if "anthropic_api_key" in kwargs and kwargs["anthropic_api_key"]:
            kwargs["anthropic_api_key"] = encrypt(kwargs["anthropic_api_key"])
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values())
        await db.execute(f"UPDATE scheduler_config SET {sets} WHERE id = 1", vals)
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

async def get_rules(enabled_only: bool = False) -> list[dict]:
    db = await get_db()
    try:
        sql = "SELECT * FROM rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY rule_type, pattern"
        cursor = await db.execute(sql)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_rule(rule_id: int) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_rule(rule_type: str, pattern: str, category: str = None,
                      description: str = None, source: str = "manual") -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO rules (rule_type, pattern, category, description, source) VALUES (?, ?, ?, ?, ?)",
            (rule_type, pattern, category, description, source),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_rule(rule_id: int, **kwargs):
    db = await get_db()
    try:
        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [rule_id]
        await db.execute(f"UPDATE rules SET {sets} WHERE id = ?", vals)
        await db.commit()
    finally:
        await db.close()


async def delete_rule(rule_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        await db.commit()
    finally:
        await db.close()


async def toggle_rule(rule_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE rules SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END, updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), rule_id),
        )
        await db.commit()
    finally:
        await db.close()


async def import_rules(rules_list: list[dict]):
    """Import rules from a JSON list, replacing all existing rules."""
    db = await get_db()
    try:
        await db.execute("DELETE FROM rules")
        for r in rules_list:
            await db.execute(
                "INSERT INTO rules (rule_type, pattern, category, description, enabled, source) VALUES (?, ?, ?, ?, ?, ?)",
                (r["rule_type"], r["pattern"], r.get("category"), r.get("description"),
                 r.get("enabled", 1), r.get("source", "manual")),
            )
        await db.commit()
    finally:
        await db.close()


async def export_rules() -> list[dict]:
    rules = await get_rules()
    return [
        {k: r[k] for k in ("rule_type", "pattern", "category", "description", "enabled", "source")}
        for r in rules
    ]


# ---------------------------------------------------------------------------
# Run History
# ---------------------------------------------------------------------------

async def create_run(triggered_by: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO run_history (triggered_by, status) VALUES (?, 'running')",
            (triggered_by,),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def update_run(run_id: int, **kwargs):
    db = await get_db()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [run_id]
        await db.execute(f"UPDATE run_history SET {sets} WHERE id = ?", vals)
        await db.commit()
    finally:
        await db.close()


async def get_recent_runs(limit: int = 20) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM run_history ORDER BY run_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Flagged Items
# ---------------------------------------------------------------------------

async def create_flagged_item(run_id: int, transaction_id: str, transaction_date: str,
                               vendor: str, amount: float, reason_flagged: str) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO flagged_items (run_id, transaction_id, transaction_date, vendor, amount, reason_flagged)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, transaction_id, transaction_date, vendor, amount, reason_flagged),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_flagged_items(status_filter: str = None) -> list[dict]:
    db = await get_db()
    try:
        sql = "SELECT f.*, r.run_at FROM flagged_items f LEFT JOIN run_history r ON f.run_id = r.id"
        params = []
        if status_filter:
            sql += " WHERE f.status = ?"
            params.append(status_filter)
        sql += " ORDER BY f.created_at DESC"
        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def resolve_flagged_item(item_id: int, status: str, notes: str = None):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE flagged_items SET status = ?, resolved_at = ?, resolution_notes = ? WHERE id = ?",
            (status, datetime.now(timezone.utc).isoformat(), notes, item_id),
        )
        await db.commit()
    finally:
        await db.close()


async def bulk_resolve_flagged(item_ids: list[int], status: str, notes: str = None):
    db = await get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        for item_id in item_ids:
            await db.execute(
                "UPDATE flagged_items SET status = ?, resolved_at = ?, resolution_notes = ? WHERE id = ?",
                (status, now, notes, item_id),
            )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Settings (encrypted values)
# ---------------------------------------------------------------------------

async def get_setting(key: str) -> str | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row and row["value"]:
            try:
                return decrypt(row["value"])
            except Exception:
                return row["value"]
        return None
    finally:
        await db.close()


async def set_setting(key: str, value: str):
    db = await get_db()
    try:
        encrypted = encrypt(value) if value else None
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, encrypted, now),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_settings() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        result = {}
        for row in rows:
            if row["value"]:
                try:
                    result[row["key"]] = decrypt(row["value"])
                except Exception:
                    result[row["key"]] = row["value"]
            else:
                result[row["key"]] = None
        return result
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Conversations & Chat Messages
# ---------------------------------------------------------------------------

async def create_conversation(user_id: int, title: str = "New Conversation") -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
            (user_id, title),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_conversations(user_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_conversation(conversation_id: int, user_id: int) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_conversation_title(conversation_id: int, title: str):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, datetime.now(timezone.utc).isoformat(), conversation_id),
        )
        await db.commit()
    finally:
        await db.close()


async def delete_conversation(conversation_id: int, user_id: int):
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        await db.commit()
    finally:
        await db.close()


async def touch_conversation(conversation_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), conversation_id),
        )
        await db.commit()
    finally:
        await db.close()


async def add_chat_message(conversation_id: int, role: str, content: str,
                           tool_name: str = None, tool_call_id: str = None) -> int:
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO chat_messages (conversation_id, role, content, tool_name, tool_call_id) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, tool_name, tool_call_id),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_chat_messages(conversation_id: int) -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Stats (for dashboard)
# ---------------------------------------------------------------------------

async def get_dashboard_stats() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM flagged_items WHERE status = 'pending'")
        pending = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM run_history")
        total_runs = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT SUM(transactions_categorized) FROM run_history WHERE status = 'completed'")
        row = await cursor.fetchone()
        total_categorized = row[0] or 0

        cursor = await db.execute("SELECT COUNT(*) FROM rules WHERE enabled = 1")
        active_rules = (await cursor.fetchone())[0]

        return {
            "pending_flagged": pending,
            "total_runs": total_runs,
            "total_categorized": total_categorized,
            "active_rules": active_rules,
        }
    finally:
        await db.close()
