"""定时任务 Cron 引擎（aimate/web/scheduler）—— 纯 stdlib。

信创红线：零第三方依赖。用 threading.Timer 调度 + 极简 cron 表达式解析 +
sqlite 持久化任务。任务可附加动作（如调用 LLM / 执行命令 / 发 webhook）。

cron 字段支持常见 5 段式：`分 时 日 月 周`（* 匹配全部；可用逗号列表与
`*/n` 步进；支持 `-` 范围）。简化实现，够日常定时巡检/日报/告警用。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Callable

_DB_NAME = "aimate_scheduler.db"


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """解析单个 cron 字段为允许值集合。"""
    allowed: set[int] = set()
    field = field.strip()
    if field in ("", "*"):
        return set(range(lo, hi + 1))
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            for v in range(a, b + 1, step):
                if lo <= v <= hi:
                    allowed.add(v)
        else:
            if part == "*":
                vals = range(lo, hi + 1)
            else:
                vals = [int(part)]
            for v in vals:
                if lo <= v <= hi and (part == "*" or True):
                    if part == "*" or (v - (int(part) if part.isdigit() and "-" not in part
                                           else 0)) % step == 0:
                        allowed.add(v)
            if part.isdigit():
                allowed.add(int(part))
    return allowed


class CronExp:
    """cron 表达式解析与匹配。"""

    def __init__(self, expr: str) -> None:
        expr = expr.strip() or "* * * * *"
        parts = [p for p in expr.split() if p]
        # 不足 5 段按从右补齐（分钟 秒 时 日 月 周 简化：假定 5 段 = 分 时 日 月 周）
        while len(parts) < 5:
            parts.insert(0, "*")
        if len(parts) > 5:
            parts = parts[-5:]
        self.minute = _parse_field(parts[0], 0, 59)
        self.hour = _parse_field(parts[1], 0, 23)
        self.day = _parse_field(parts[2], 1, 31)
        self.month = _parse_field(parts[3], 1, 12)
        self.week = _parse_field(parts[4], 0, 6)  # 0=周日

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minute:
            return False
        if dt.hour not in self.hour:
            return False
        if dt.month not in self.month:
            return False
        if dt.day not in self.day:
            return False
        # 周：0=周日。cron 周逢 7 映射 0
        w = dt.weekday()  # 0=周一..6=周日
        w_cron = (w + 1) % 7  # 周一0->1...周日6->0
        if w_cron not in self.week:
            return False
        return True


class Scheduler:
    """Cron 任务调度器：线程化轮询 + sqlite 持久化。"""

    def __init__(self, db_dir: str = ".", run_hook: Callable[[dict], Any] | None = None) -> None:
        self._db = sqlite3.connect(f"{db_dir}/{_DB_NAME}", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""CREATE TABLE IF NOT EXISTS cron_jobs(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, expr TEXT NOT NULL,
            action TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'enabled',
            created_at REAL, last_run REAL, next_run REAL, total_runs INTEGER DEFAULT 0)""")
        self._db.commit()
        self.run_hook = run_hook
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick = -1

    # ---- CRUD ----
    def add_job(self, name: str, expr: str, action: dict, job_id: str | None = None) -> dict:
        import uuid
        jid = job_id or uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO cron_jobs(id,name,expr,action,state,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (jid, name, expr, json.dumps(action, ensure_ascii=False), "enabled",
                 time.time()))
            self._db.commit()
        return self.get_job(jid) or {"id": jid}

    def get_job(self, jid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM cron_jobs WHERE id=?", (jid,)).fetchone()
        return self._row(r) if r else None

    def list_jobs(self) -> list[dict]:
        return [self._row(r) for r in self._db.execute(
            "SELECT * FROM cron_jobs ORDER BY created_at DESC").fetchall()]

    def set_state(self, jid: str, state: str) -> None:
        self._db.execute("UPDATE cron_jobs SET state=? WHERE id=?", (state, jid))
        self._db.commit()

    def remove_job(self, jid: str) -> None:
        self._db.execute("DELETE FROM cron_jobs WHERE id=?", (jid,))
        self._db.commit()

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["action"] = json.loads(d["action"])
        except Exception:
            pass
        return d

    # ---- 运行循环 ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            tick = int(now // 60)
            if tick != self._last_tick:
                self._last_tick = tick
                try:
                    self._tick(datetime.fromtimestamp(now))
                except Exception:
                    pass
            time.sleep(1)

    def _tick(self, dt: datetime) -> None:
        jobs = [j for j in self.list_jobs() if j["state"] == "enabled"]
        for j in jobs:
            try:
                ce = CronExp(j["expr"])
            except Exception:
                continue
            if not ce.matches(dt):
                continue
            with self._lock:
                self._db.execute(
                    "UPDATE cron_jobs SET last_run=?, total_runs=total_runs+1 WHERE id=?",
                    (time.time(), j["id"]))
                self._db.commit()
            if self.run_hook:
                try:
                    self.run_hook({"id": j["id"], "name": j["name"],
                                   "action": j["action"]})
                except Exception:
                    pass

    # ---- 手动触发（测试用） ----
    def fire(self, jid: str) -> None:
        j = self.get_job(jid)
        if not j:
            return
        with self._lock:
            self._db.execute(
                "UPDATE cron_jobs SET last_run=?, total_runs=total_runs+1 WHERE id=?",
                (time.time(), jid))
            self._db.commit()
        if self.run_hook:
            self.run_hook({"id": jid, "name": j["name"], "action": j["action"]})
