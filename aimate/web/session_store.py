"""会话持久化 + 会话搜索（aimate/web/session_store）—— 纯 stdlib sqlite。

信创红线：仅用 stdlib sqlite3（含 FTS5 全文检索），无第三方依赖。

- 会话（session）：id、标题、owner、created/updated、对应工作目录路径
- 消息（message）：session_id、role、content、created_at
- 会话搜索：FTS5 按关键词命中所有会话（按消息正文全文检索）
- 工作目录生命周期：新建会话自动在 workspace/<sid> 创建目录；删除会话递归删除

存储：CWD/.aimate/sessions.sqlite3；工作目录 CWD/workspace/<sid>/。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from typing import Optional


def _dir() -> str:
    d = os.path.join(os.getcwd(), ".aimate")
    os.makedirs(d, exist_ok=True)
    return d


def _workspace_root() -> str:
    root = os.path.join(os.getcwd(), "workspace")
    os.makedirs(root, exist_ok=True)
    return root


class SessionStore:
    def __init__(self, path: Optional[str] = None,
                 workspace_root: Optional[str] = None) -> None:
        self.path = path or os.path.join(_dir(), "sessions.sqlite3")
        self.workspace_root = workspace_root or _workspace_root()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, title TEXT, owner TEXT, cwd TEXT,
                created_at REAL, updated_at REAL)""")
            c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5(
                session_id UNINDEXED, role UNINDEXED, content)""")

    # ---- 会话 CRUD ----
    def create(self, title: str = "新会话", owner: str = "default") -> dict:
        sid = uuid.uuid4().hex[:12]
        cwd = os.path.join(self.workspace_root, sid)
        os.makedirs(cwd, exist_ok=True)
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions(id,title,owner,cwd,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", (sid, title, owner, cwd, now, now))
        out = self.get(sid)
        assert out is not None
        return out

    def get(self, sid: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM sessions WHERE id=?",
                            (sid,)).fetchone()
        return dict(row) if row else None

    def list(self, owner: str = "default", limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM sessions WHERE owner=? ORDER BY updated_at DESC "
                "LIMIT ?", (owner, limit)).fetchall()
        return [dict(r) for r in rows]

    def rename(self, sid: str, title: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET title=?,updated_at=? WHERE id=?",
                      (title, time.time(), sid))

    def touch(self, sid: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?",
                      (time.time(), sid))

    def message_count(self, sid: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT count(*) AS n FROM messages WHERE session_id=?",
                (sid,)).fetchone()
        return int(row["n"]) if row else 0

    def delete(self, sid: str) -> None:
        sess = self.get(sid)
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE id=?", (sid,))
            c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
        if sess and sess.get("cwd") and os.path.isdir(sess["cwd"]):
            shutil.rmtree(sess["cwd"], ignore_errors=True)

    # ---- 消息 ----
    def add_message(self, sid: str, role: str, content: str) -> None:
        content = content or ""
        # FTS5 索引：每行一个消息
        with self._conn() as c:
            c.execute("INSERT INTO messages(session_id,role,content) VALUES(?,?,?)",
                      (sid, role, content))
            # 同时存入会话可见消息量
        self.touch(sid)

    def messages(self, sid: str, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT rowid,session_id,role,content FROM messages "
                "WHERE session_id=? ORDER BY rowid LIMIT ?",
                (sid, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---- 会话搜索（FTS5）----
    def search(self, query: str, owner: str = "default", limit: int = 50
               ) -> list[dict]:
        """按关键词全文检索会话消息，聚合出命中的会话及其片段。"""
        query = (query or "").strip()
        if not query:
            return []
        # FTS5 : 空格分隔的词 AND；加双引号支持精确中的中文（FTS5 对 CJK 按字符跳词，
        # 这里退化为 SQL LIKE 兜底 + FTS 优化命中）
        hits: dict[str, dict] = {}
        like = f"%{self._esc_like(query)}%"
        try:
            with self._conn() as c:
                rows = c.execute(
                    "SELECT session_id,content FROM messages WHERE content LIKE ? "
                    "ORDER BY rowid DESC LIMIT ?", (like, limit * 5)).fetchall()
                for r in rows:
                    if len(hits) >= limit:
                        break
                    d = hits.setdefault(
                        r["session_id"],
                        {"session_id": r["session_id"], "snippets": [], "count": 0})
                    d["snippets"].append(self._snippet(r["content"], query))
                    d["count"] += 1
        except Exception:  # noqa: BLE001
            pass
        out = []
        for sid, d in hits.items():
            sess = self.get(sid)
            if not sess:
                continue
            out.append({
                "session_id": sid, "title": sess["title"], "cwd": sess["cwd"],
                "updated_at": sess["updated_at"], "count": d["count"],
                "snippets": d["snippets"][:3],
            })
        out.sort(key=lambda x: -x["updated_at"])
        return out[:limit]

    @staticmethod
    def _snippet(text: str, query: str, span: int = 60) -> str:
        text = text.replace("\n", " ").strip()
        q = query.strip()
        i = text.lower().find(q.lower())
        if i == -1:
            return text[: span * 2]
        lo = max(0, i - span // 2)
        hi = min(len(text), i + len(q) + span // 2)
        return ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else "")

    @staticmethod
    def _esc_like(s: str) -> str:
        return re.sub(r"[%_\\]", lambda m: "\\" + m.group(0), s)
