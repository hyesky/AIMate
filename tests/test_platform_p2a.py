"""P2a 定时任务 Cron 引擎测试（参考 hermes cron 模式）。"""
import os
import sys
import tempfile
import threading
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimate.web import scheduler  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ✔ {name}")


def main():
    print("P2a 定时任务 Cron 引擎")
    d = tempfile.mkdtemp(prefix="aimate_p2a_")
    s = scheduler.Scheduler(d)

    # 1) cron 字段解析
    check("*/5 分钟", scheduler._parse_field("*/5", 0, 59) == set(range(0, 60, 5)))
    check("范围 1-3 时", scheduler._parse_field("1-3", 0, 23) == {1, 2, 3})
    check("列表 1,15", scheduler._parse_field("1,15", 0, 59) == {1, 15})

    # 2) 表达式匹配
    ce = scheduler.CronExp("30 9 * * 1")  # 周一 09:30
    ok = ce.matches(datetime(2026, 9, 14, 9, 30))
    bad = ce.matches(datetime(2026, 9, 14, 9, 31))
    wk = ce.matches(datetime(2026, 9, 15, 9, 30))  # 周二
    check("匹配精准", ok and not bad and not wk)

    # 3) compute_next_run
    nxt = scheduler.compute_next_run("*/5 * * * *",
                                     after=datetime(2026, 9, 14, 9, 3))
    check("next_run 步进", nxt == datetime(2026, 9, 14, 9, 5))

    # 4) 持久化 CRUD
    j = s.add_job("测试任务", "0 2 * * *", {"type": "exec", "cmd": "echo hi"})
    check("add 生成 id", bool(j["id"]))
    check("list 含任务", len(s.list_jobs()) == 1)
    check("next_run 已算", isinstance(j.get("next_run"), float))
    s.remove_job(j["id"])
    check("remove 后空", len(s.list_jobs()) == 0)

    # 5) 执行 dispatch（exec）
    r = scheduler.dispatch({"name": "t", "action": {"type": "exec", "cmd": "echo p2a-ok"}},
                           run_id="x")
    check("exec 动作", r["ok"] and "p2a-ok" in r["output"])

    # 6) 手动触发 + 执行历史
    j2 = s.add_job("跑一次", "* * * * *",
                   {"type": "exec", "cmd": "printf run"})
    fired = s.fire(j2["id"])
    check("fire 后 last_run 更新", bool(fired and fired.get("last_run")))
    runs = s.list_runs(j2["id"])
    check("执行历史落库", len(runs) >= 1 and runs[0]["output"] == "run")

    # 7) 暂停（state）后不触发
    s.set_state(j2["id"], "paused")
    n0 = len(s.list_jobs())
    s._tick(datetime.now().replace(second=0))
    check("暂停不执行（无新增运行）", len(s.list_runs(j2["id"])) == 1)

    # 8) tick 主循环派发（enabled + 匹配）
    s.set_state(j2["id"], "enabled")
    from aimate.web.scheduler import CronExp
    j3 = s.add_job("循环", "* * * * *", {"type": "exec", "cmd": "printf tick"})
    # 让 _tick 手动在匹配时刻跑
    hit = next((t for t in range(0, 60) if t in CronExp(j3["expr"]).minute), 0)
    s._tick(datetime.now().replace(minute=hit, second=0))
    check("tick 触发执行", any(r["job_id"] == j3["id"] for r in s.list_runs()))

    # 9) 运行防重：并发触发慢任务不重叠
    entered = []
    def slow_hook(_job):
        entered.append(1)
        time.sleep(0.5)
    s2 = scheduler.Scheduler(d, run_hook=slow_hook)
    j4 = s2.add_job("防重", "* * * * *", {"type": "log"})
    # 两个线程同时触发同一任务
    barrier = threading.Barrier(2)
    def go():
        barrier.wait()
        s2.fire(j4["id"])
    t1 = threading.Thread(target=go); t2 = threading.Thread(target=go)
    t1.start(); t2.start(); t1.join(); t2.join()
    check("慢任务并发防重只进一次", len(entered) == 1)

    print(f"\nALL PASS ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
