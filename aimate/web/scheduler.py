"""定时任务 Cron 引擎（aimate/web/scheduler）—— 纯 stdlib。

信创红线：零第三方依赖。参考 hermes-agent（cron/jobs.py + cron/scheduler.py +
cron/executions.py）的工程模式：用统一 compute_next_run 计算下次触发、tick 轮询
主循环（非每任务一个 Timer）、任务运行防重（_running 集合 + 锁，避免慢任务重叠）、
暂停用 state 字段而非删任务、执行历史落库（cron_runs）。

cron 表达式支持常见 5 段式：`分 时 日 月 周`（0=周日）。字段支持 `*` / 逗号列表 /
`-` 范围 / `*/n` 步进。动作支持：call_llm / exec / webhook / log。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

_DB_NAME = "aimate_scheduler.db"


# ---- cron 字段解析 ----
def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """解析单个 cron 字段为允许值集合，支持 `*` / 列表 / 范围 / 步进。"""
    allowed: set[int] = set()
    field = field.strip() or "*"
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        body = part
        if "/" in part:
            body, step_s = part.split("/", 1)
            if step_s:
                step = int(step_s)
        if body == "*":
            vals = list(range(lo, hi + 1))
        elif "-" in body:
            a, b = body.split("-", 1)
            vals = list(range(int(a), int(b) + 1))
        else:
            vals = [int(body)]
        for v in vals:
            if lo <= v <= hi and (v - lo) % step == 0:
                allowed.add(v)
    return allowed


class CronExp:
    """cron 表达式解析与匹配。"""

    def __init__(self, expr: str) -> None:
        expr = expr.strip() or "* * * * *"
        parts = [p for p in expr.split() if p]
        if len(parts) != 5:
            raise ValueError(f"cron 需 5 段(分 时 日 月 周): {expr!r}")
        self.minute = _parse_field(parts[0], 0, 59)
        self.hour = _parse_field(parts[1], 0, 23)
        self.day = _parse_field(parts[2], 1, 31)
        self.month = _parse_field(parts[3], 1, 12)
        self.week = _parse_field(parts[4], 0, 6)  # 0=周日

    def matches(self, dt: datetime) -> bool:
        if dt.minute not in self.minute or dt.hour not in self.hour:
            return False
        if dt.month not in self.month or dt.day not in self.day:
            return False
        w_cron = (dt.weekday() + 1) % 7  # 周一0->1 … 周日6->0
        if w_cron not in self.week:
            return False
        return True


def compute_next_run(expr: str, after: datetime | None = None) -> datetime | None:
    """从 after（默认 now）起找下一个命中分钟；找不到返回 None。"""
    ce = CronExp(expr)
    cur = (after or datetime.now()).replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 366):  # 扫一年足够
        if ce.matches(cur):
            return cur
        cur += timedelta(minutes=1)
    return None


# ---- 动作分发 ----
def dispatch(job: dict, run_id: str, llm=None) -> dict:
    """执行任务动作，返回 {ok, output}。支持 call_llm / exec / webhook / log。"""
    action = job.get("action") or {}
    atype = action.get("type", "log")
    if atype == "exec":
        cmd = action.get("cmd", "")
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=int(action.get("timeout", 60)))
            return {"ok": r.returncode == 0,
                    "output": (r.stdout or r.stderr or "").strip()[:2000]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "output": str(e)[:1000]}
    if atype == "call_llm" and llm:
        prompt = action.get("prompt", job.get("name", ""))
        try:
            text = llm(action.get("prompt", prompt)) if callable(llm) else str(llm)
            return {"ok": bool(text.strip()), "output": text[:2000]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "output": str(e)[:1000]}
    if atype == "webhook":
        url = action.get("url", "")
        payload = json.dumps(action.get("payload") or {"job": job.get("name")},
                             ensure_ascii=False).encode()
        try:
            import urllib.request
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=int(action.get("timeout", 15))) as r:
                return {"ok": True, "output": r.read().decode("utf-8", "replace")[:1000]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "output": str(e)[:1000]}
    return {"ok": True, "output": f"log trigger: {job.get('name')}"}


class Scheduler:
    """Cron 任务调度器：tick 轮询 + sqlite 持久化 + 运行防重。"""

    def __init__(self, db_dir: str = ".", run_hook: Callable[[dict], Any] | None = None) -> None:
        self._db = sqlite3.connect(f"{db_dir}/{_DB_NAME}", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""CREATE TABLE IF NOT EXISTS cron_jobs(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, expr TEXT NOT NULL,
            action TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'enabled',
            created_at REAL, last_run REAL, next_run REAL, total_runs INTEGER DEFAULT 0)""")
        self._db.execute("""CREATE TABLE IF NOT EXISTS cron_runs(
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, ts REAL, ok INTEGER,
            output TEXT)""")
        self._db.commit()
        self.run_hook = run_hook
        self._lock = threading.Lock()
        self._running: set[str] = set()  # 运行中任务，防重
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick = -1

    # ---- CRUD ----
    def add_job(self, name: str, expr: str, action: dict,
                job_id: str | None = None, state: str = "enabled") -> dict:
        if "type" not in action:
            action = {**action, "type": "log"}
        jid = job_id or uuid.uuid4().hex[:12]
        nxt = compute_next_run(expr)
        with self._lock:
            self._db.execute(
                "INSERT INTO cron_jobs(id,name,expr,action,state,created_at,next_run)"
                " VALUES(?,?,?,?,?,?,?)",
                (jid, name, expr, json.dumps(action, ensure_ascii=False), state,
                 time.time(), nxt.timestamp() if nxt else None))
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

    def list_runs(self, jid: str | None = None, limit: int = 20) -> list[dict]:
        if jid:
            rows = self._db.execute(
                "SELECT * FROM cron_runs WHERE job_id=? ORDER BY ts DESC LIMIT ?",
                (jid, limit))
        else:
            rows = self._db.execute("SELECT * FROM cron_runs ORDER BY ts DESC LIMIT ?",
                                    (limit,))
        return [dict(r) for r in rows.fetchall()]

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        try:
            d["action"] = json.loads(d["action"])
        except Exception:
            pass
        return d

    def _record_run(self, run_id: str, job_id: str, ok: bool, output: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO cron_runs(id,job_id,ts,ok,output) VALUES(?,?,?,?,?)",
                (run_id, job_id, time.time(), 1 if ok else 0, output[:4000]))
            self._db.commit()

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
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(1)

    def _tick(self, dt: datetime) -> None:
        for j in self.list_jobs():
            if j["state"] != "enabled":
                continue
            try:
                if not CronExp(j["expr"]).matches(dt):
                    continue
            except Exception:  # noqa: BLE001
                continue
            nxt = compute_next_run(j["expr"], after=dt + timedelta(minutes=1))
            with self._lock:
                self._db.execute(
                    "UPDATE cron_jobs SET last_run=?, next_run=?,"
                    " total_runs=total_runs+1 WHERE id=?",
                    (time.time(), nxt.timestamp() if nxt else None, j["id"]))
                self._db.commit()
            self._run(j)

    def _run(self, job: dict) -> None:
        """执行单个任务，带防重与结果记录。"""
        with self._lock:
            if job["id"] in self._running:
                return  # 已运行中，跳过（防重）
            self._running.add(job["id"])
        run_id = uuid.uuid4().hex[:12]
        try:
            if self.run_hook:
                try:
                    self.run_hook({"id": job["id"], "name": job["name"],
                                   "action": job["action"], "run_id": run_id})
                except Exception as e:  # noqa: BLE001
                    self._record_run(run_id, job["id"], False, str(e))
                    return
            else:
                res = dispatch(job, run_id)
                self._record_run(run_id, job["id"], res.get("ok", True),
                                 res.get("output", ""))
        finally:
            with self._lock:
                self._running.discard(job["id"])

    # ---- 手动触发（测试/UI 用） ----
    def fire(self, jid: str) -> dict | None:
        j = self.get_job(jid)
        if not j:
            return None
        nxt = compute_next_run(j["expr"])
        with self._lock:
            self._db.execute(
                "UPDATE cron_jobs SET last_run=?, next_run=? WHERE id=?",
                (time.time(), nxt.timestamp() if nxt else None, jid))
            self._db.commit()
        self._run(j)
        return self.get_job(jid)
