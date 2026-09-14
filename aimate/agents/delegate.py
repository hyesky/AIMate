"""AgentsDelegate — 子 Agent 委派（参考 hermes delegate_tool.py，自研实现）

把任务拆分为若干独立子任务，交给「隔离上下文」的子 Agent 并行执行，最后回收
每个子任务的 summary。子 Agent 复用 AgentRunner 的多轮工具循环，但：
  * 每个子任务用一份全新消息序列（不携带父对话历史）—— 隔离上下文
  * 屏蔽 DELEGATE_BLOCKED_TOOLS（禁递归委派 / 禁写共享记忆）
  * 批量任务经 ThreadPoolExecutor 并行
  * 父 Agent 只见最终 summary，不见子任务中间过程
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from aimate.agents.runner import DELEGATE_BLOCKED_TOOLS

logger = logging.getLogger(__name__)

_MAX_WORKERS = 4
_DEFAULT_TIMEOUT = 120.0


class AgentsDelegate:
    def __init__(self, runner: Any, max_workers: int = _MAX_WORKERS) -> None:
        self.runner = runner
        self.max_workers = max_workers

    # ---- 入口 ----
    def invoke(self, args: dict) -> dict:
        """执行 delegate_task。args 含 {description?, tasks:[{goal, context?}]}。"""
        tasks = args.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            return {"error": "delegate_task 需要非空 tasks 列表"}

        # 结构化：每个子任务携带 description 总背景
        desc = str(args.get("description") or "")
        normalized = [
            {
                "goal": str((t or {}).get("goal", "")).strip(),
                "context": str((t or {}).get("context", "") or "").strip(),
                "description": desc,
            }
            for t in tasks
            if isinstance(t, dict) and str((t or {}).get("goal", "")).strip()
        ]
        if not normalized:
            return {"error": "delegate_task 无可用的 goal 任务"}

        results = self._run_parallel(normalized)
        return {
            "n": len(results),
            "results": results,
        }

    # ---- 并行执行 ----
    def _run_parallel(self, tasks: list[dict]) -> list[dict]:
        out: list[dict] = []
        if len(tasks) == 1:
            return [self._run_one(tasks[0])]
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as ex:
            futs = {ex.submit(_worker, self, t): t for t in tasks}
            for fut in as_completed(futs, timeout=_DEFAULT_TIMEOUT):
                t = futs[fut]
                try:
                    out.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    out.append(_result(t, ok=False, detail=f"{type(e).__name__}: {e}"))
        return out

    # ---- 单任务执行（子 Agent 隔离上下文） ----
    def _run_one(self, task: dict) -> dict:
        goal = task["goal"]
        context = task.get("context") or ""
        desc = task.get("description") or ""

        # 子 Agent 系统提示：focused subagent（借鉴 hermes _build_child_system_prompt）
        sys_parts = [
            "你是一位专注的子 Agent（subagent），负责完成一个被委派的独立子任务。",
            f"任务（TASK）:\n{goal}",
        ]
        if context:
            sys_parts.append(f"补充上下文（CONTEXT）:\n{context}")
        if desc:
            sys_parts.append(f"总说明（BACKGROUND）:\n{desc}")
        sys_parts.append(
            "请尽可能独立完成任务。任务结束后，请给出简洁总结（summary），"
            "内容包括：你做了什么、达成了什么结果、创建/修改了哪些内容、遇到什么问题。"
            "你的总结会返回给上级 Agent，请聚焦结果而非过程。"
        )
        child_system = "\n\n".join(sys_parts)

        # 子 Agent 可用工具：父工具集剔除 DELEGATE_BLOCKED_TOOLS
        tools = [
            t for t in (self.runner.tool_schemas() or [])
            if _tool_name(t) not in DELEGATE_BLOCKED_TOOLS
        ]

        child_messages: list[dict] = [{"role": "user", "content": goal}]
        try:
            final, _trace = self.runner.run(
                child_messages,
                tools=tools or None,
                max_turns=self.runner.turn_cap,
            )
            return _result(task, ok=True, summary=final,
                           system_prompt_prefix=child_system.splitlines()[0])
        except Exception as e:  # noqa: BLE001
            logger.exception("subagent 执行失败")
            return _result(task, ok=False, detail=f"{type(e).__name__}: {e}")


def _tool_name(t: Any) -> str:
    """从 openai tool 包裹里取函数名。"""
    if not isinstance(t, dict):
        return ""
    fn = t.get("function")
    if isinstance(fn, dict):
        return str(fn.get("name", ""))
    return str(t.get("name", ""))


def _result(task: dict, *, ok: bool, summary: str = "", detail: Optional[str] = None,
            system_prompt_prefix: str = "") -> dict:
    return {
        "goal": task.get("goal", ""),
        "ok": ok,
        "summary": summary or (detail or "(无摘要)"),
    }


def _worker(dele: AgentsDelegate, task: dict) -> dict:
    """线程 worker：给每个子任务一个独立的线程本地隔离（TLS 日志/状态）。"""
    tls = getattr(_worker, "tls", None)
    if tls is None:
        tls = threading.local()
        _worker.tls = tls
    tls.task_id = _safe_id(task.get("goal", ""))
    return dele._run_one(task)


def _safe_id(goal: str) -> str:
    import re
    m = re.search(r"[0-9a-f]{8,}", goal.lower())
    return m.group(0) if m else "sub"
