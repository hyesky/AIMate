"""工作流编排引擎：面向企业的可视化/声明式 DAG。

设计（自研）：节点 = 工具/LLM/子流程，边 = 数据流转。
提供声明式 DAG 定义 + 顺序/并行执行器 + 状态持久化（可落国产 DB）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

NodeFn = Callable[[dict], Awaitable[dict]]


@dataclass
class WorkflowNode:
    id: str
    fn: NodeFn
    deps: list[str] = field(default_factory=list)  # 依赖节点 id
    params: dict = field(default_factory=dict)


@dataclass
class WorkflowRun:
    wf_id: str
    run_id: str
    status: str = "pending"          # pending/running/success/failed
    outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class WorkflowEngine:
    """简单 DAG 执行器：入度为零的节点可并行执行。"""

    def __init__(self) -> None:
        self._defs: dict[str, dict[str, WorkflowNode]] = {}

    def define(self, wf_id: str, nodes: list[WorkflowNode]) -> None:
        self._defs[wf_id] = {n.id: n for n in nodes}

    async def run(self, wf_id: str, run_id: str, inputs: dict) -> WorkflowRun:
        nodes = self._defs.get(wf_id)
        if not nodes:
            raise KeyError(f"workflow {wf_id} not defined")
        run = WorkflowRun(wf_id, run_id, "running")
        results: dict[str, Any] = dict(inputs)
        remaining = set(nodes)
        while remaining:
            ready = [
                n
                for n in remaining
                if all(d in results for d in nodes[n].deps)
            ]
            if not ready:
                raise RuntimeError(f"deadlock / missing inputs in {wf_id}")
            async def _one(n: WorkflowNode):
                try:
                    return n.id, await n.fn({**results, **n.params})
                except Exception as e:  # noqa: BLE001
                    return n.id, e

            batch = await asyncio.gather(*[_one(nodes[nid]) for nid in sorted(ready)])
            for nid, res in batch:
                if isinstance(res, Exception):
                    run.status = "failed"
                    run.error = f"{nid}: {res}"
                    return run
                results[nid] = res
                remaining.discard(nid)
        run.status = "success"
        run.outputs = results
        return run
