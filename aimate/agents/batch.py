"""BatchRunner — 批量处理（参考 hermes batch_runner.py，自研精简版）

对一组 prompt 并发（ThreadPoolExecutor）逐个交给 AgentRunner 处理，回收每条结果
与整体统计。设计要点：
  * dataset 来源：内存 list 或 JSONL 文件（每行含 prompt，可带 image/meta）
  * 每行独立（隔离上下文），复用 AgentRunner 的多轮工具循环
  * 并发 worker 上限可配；响应含 truncated 兜底
  * 汇总 {total, success, failed, tool_calls, avg_turns}
hook 用途：给 runner 注册 on_tool_after/on_done 钩子做统计埋点。
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 4


def _row_text(row: dict) -> str:
    """从 dataset 行取 prompt 文本。"""
    return str(row.get("prompt") or row.get("text") or row.get("message") or "")


class BatchRunner:
    def __init__(self, runner_factory: Any, workers: int = DEFAULT_WORKERS) -> None:
        """runner_factory: () -> AgentRunner（每个 worker 各自创建，隔离 hook 统计）。"""
        self._factory = runner_factory
        self.workers = max(1, int(workers))

    # ---- 数据集加载 ----
    @staticmethod
    def load_dataset(path: str) -> list[dict]:
        """从 JSONL（或 .json）加载 dataset。每行含 {prompt,...}。"""
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        if path.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("items") or data.get("prompts") or []
            return [d for d in data if isinstance(d, dict)]
        rows: list[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    obj = {"prompt": line}
                rows.append(obj if isinstance(obj, dict) else {"prompt": obj})
        return rows

    # ---- 主入口 ----
    def run(self, dataset: Iterable[dict],
            system_prompt: str = "") -> dict:
        """处理整个 dataset，返回汇总。每行进 AgentRunner.run 一段独立会话。"""
        rows = [dict(r) for r in dataset]
        if not rows:
            return {"total": 0, "success": 0, "failed": 0, "results": []}

        results: list[dict] = [None] * len(rows)  # type: ignore[list-item]
        workers = min(self.workers, len(rows))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut_map = {
                ex.submit(self._process_one, i, rows[i], system_prompt): i
                for i in range(len(rows))
            }
            for fut in as_completed(fut_map):
                i = fut_map[fut]
                try:
                    results[i] = fut.result()
                except Exception as e:  # noqa: BLE001
                    results[i] = {"index": i, "ok": False,
                                  "summary": f"{type(e).__name__}: {e}"}

        success = sum(1 for r in results if r and r.get("ok"))
        tool_calls = 0
        total_turns = 0
        for r in results:
            if not r:
                continue
            tool_calls += r.get("tool_calls", 0) or 0
            total_turns += r.get("turns", 1) or 1
        return {
            "total": len(results),
            "success": success,
            "failed": len(results) - success,
            "tool_calls": tool_calls,
            "avg_turns": round(total_turns / len(results), 2) if results else 0,
            "results": results,
        }

    # ---- 单条处理 ----
    def _process_one(self, index: int, row: dict, system_prompt: str) -> dict:
        text = _row_text(row)
        if not text:
            return {"index": index, "ok": False, "summary": "空 prompt"}

        runner = self._factory()  # 每个 worker 独立 runner（独立 hook 统计）
        stats = {"tool_calls": 0, "turns": 0, "truncated": False}
        runner.hook("on_tool_after",
                    lambda **kw: stats.__setitem__("tool_calls",
                                                   stats["tool_calls"] + 1))
        ready = {"tracked": False}

        def _done(**kw):
            stats["turns"] += 1
            ready["tracked"] = True
            if kw.get("truncated"):
                stats["truncated"] = True
        runner.hook("on_done", _done)

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": text})

        try:
            summary, _trace = runner.run(messages)
            if not ready["tracked"]:
                stats["turns"] = 1
            return {
                "index": index,
                "ok": not stats["truncated"] or ("上限" not in summary),
                "summary": summary,
                "tool_calls": stats["tool_calls"],
                "turns": max(stats["turns"], 1),
                "truncated": stats["truncated"],
            }
        except Exception as e:  # noqa: BLE001
            logger.exception("batch row %s 失败", index)
            return {"index": index, "ok": False,
                    "summary": f"{type(e).__name__}: {e}"}
