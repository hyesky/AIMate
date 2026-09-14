"""AgentRunner — 多轮工具执行循环（参考 hermes delegate_tool / tool-loop 工程思想，自研实现）

AIMate 的 dispatch() 原为单轮 LLM 调用（返回 tool_calls 但不执行）。本模块引入
「chat → tool_calls → 执行 → 回填 → 再 chat」的循环，直到 finish 或达 max_turns，
是 P2b 子 Agent 委派 与 P2c/P2d 的地基。

执行器（execute_tool）把三类工具统一到一个入口：
  * MCP 工具      -> system.mcp.call_tool(<server>__<tool>, args)   （stdio，数据不出域）
  * 内置知识召回  -> system.search_kb(query)  （RAG，BM25）
  * delegate_task -> 由 AgentsDelegate 接管（多轮循环/批量并行/隔离上下文）
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 内置非 MCP 工具名（前缀，不含「<server>__」）
BUILTIN_TOOLS = {
    "rag_search": "在本地知识库中检索与 query 相关的内容（BM25 稀疏检索）",
    "delegate_task": "把任务拆分为独立子任务并委派给子 Agent 并行执行，返回各子任务摘要",
    "execute_code": "在隔离沙箱子进程中执行一段 Python 代码，返回其 stdout/stderr",
}

# 子 Agent 必须屏蔽的工具（防止递归委派 / 污染共享状态）——借鉴 hermes
# DELEGATE_BLOCKED_TOOLS：delegate_task（禁递归）、write_memory（禁写共享记忆）。
DELEGATE_BLOCKED_TOOLS = frozenset({"delegate_task", "write_memory"})


class ToolExecutionError(Exception):
    """工具执行失败但可继续会话（结果以错误文本回填，不中止整个循环）。"""


def _stringify(result: Any) -> str:
    """把工具返回序列化为回填给模型的文本（容忍任意返回类型）。"""
    if result is None:
        return "(无返回)"
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(result)
    return str(result)


class AgentRunner:
    """多轮工具执行循环。

    用法（伪代码）:
        runner = AgentRunner(system, turn_cap=8)
        final, trace = runner.run(alias, messages, tools=tools)

    返回 (最终文本, 过程 trace)。
    """

    def __init__(self, system: Any, alias: str, turn_cap: int = 8,
                 executor: Optional[Callable[[str, dict], Any]] = None) -> None:
        self.system = system
        self.alias = alias
        self.turn_cap = turn_cap
        # 自定义执行器（测试/委派覆盖用）；默认走 _default_executor
        self._executor = executor

    # ---- 工具 schema ----
    def tool_schemas(self) -> list[dict]:
        """归并 MCP 工具 + 内置工具，返回 openai tool 包裹形式。"""
        mcp = [
            {"type": "function", "function": s}
            for s in getattr(self.system.mcp, "_schemas", {}).values()
        ]
        builtin = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": _builtin_params(name),
                },
            }
            for name, desc in BUILTIN_TOOLS.items()
        ]
        return mcp + builtin

    # ---- 主循环 ----
    def run(self, messages: list[dict], tools: Optional[list[dict]] = None,
            *, max_turns: Optional[int] = None) -> tuple[str, list[dict]]:
        """执行对话到最终回复。messages 为不含 system 的用户/助手消息序列。

        returns (final_text, trace)  trace 记录每轮 tool_calls 及其结果。
        """
        cap = self.turn_cap if max_turns is None else max_turns
        trace: list[dict] = []
        history: list[dict] = list(messages)

        for _ in range(cap):
            resp = self.system.llm.chat(self.alias, history, tools=tools)
            backend = self.system.llm.resolve(self.alias)
            text = backend.reply_text(resp)
            finish = backend.finish_reason(resp)
            tcs = backend.tool_calls(resp)

            if tcs:
                # 工具调用轮：执行 + 回填 role=tool，再继续
                for tc in tcs:
                    fn = (tc.get("function") or {}).get("name", "")
                    arg_raw = (tc.get("function") or {}).get("arguments", "{}")
                    try:
                        args = json.loads(arg_raw) if isinstance(arg_raw, str) else arg_raw
                        if not isinstance(args, dict):
                            args = {"arguments": args}
                    except ValueError:
                        args = {}
                    result_text = self._execute_tool(fn, args, trace)
                    history.append({"role": "assistant",
                                    "content": None, "tool_calls": [tc]})
                    history.append({"role": "tool", "tool_call_id": tc.get("id", fn),
                                    "content": result_text})
                continue  # 本轮回填后继续

            # 无工具调用：正常回复
            if text:
                history.append({"role": "assistant", "content": text})
            return text, trace

        # 超轮数兜底
        return "(已达到最大工具轮数上限)", trace

    # ---- 执行器 ----
    def _execute_tool(self, name: str, args: dict, trace: list[dict]) -> str:
        try:
            out = self._dispatch_tool(name, args)
            text = _stringify(out)
            trace.append({"tool": name, "args": args, "ok": True, "result": text})
            return text
        except ToolExecutionError as e:
            text = f"工具执行失败: {e}"
            trace.append({"tool": name, "args": args, "ok": False, "result": text})
            return text
        except Exception as e:  # noqa: BLE001 未知异常也不中断循环
            text = f"工具执行异常: {type(e).__name__}: {e}"
            trace.append({"tool": name, "args": args, "ok": False, "result": text})
            return text

    def _dispatch_tool(self, name: str, args: dict) -> Any:
        if self._executor is not None:
            return self._executor(name, args)
        return self._default_executor(name, args)

    def _default_executor(self, name: str, args: dict) -> Any:
        sys = self.system
        if name == "rag_search":
            q = str(args.get("query") or args.get("q") or "")
            if not q:
                raise ToolExecutionError("rag_search 缺少 query")
            hits = sys.search_kb(q)
            return [
                {"text": getattr(h, "text", str(h)), "score": getattr(h, "score", None)}
                for h in (hits or [])
            ]
        if name == "delegate_task":
            return self._delegate(args)
        if name == "execute_code":
            from aimate.agents.code_exec import execute_code

            code = args.get("code") or ""
            timeout = min(float(args.get("timeout", 300) or 300), 600)
            return execute_code(code, timeout=timeout)
        if "__" in name:
            return sys.mcp.call_tool(name, args)
        raise ToolExecutionError(f"未知工具: {name}")

    def _delegate(self, args: dict) -> Any:
        """delegate_task 由 AgentsDelegate 接管（延迟导入避免循环依赖）。"""
        from aimate.agents.delegate import AgentsDelegate

        delegate = AgentsDelegate(self)
        return delegate.invoke(args)


def _builtin_params(name: str) -> dict:
    """内置工具的 JSON Schema parameters（供模型 tool_calling 用）。"""
    if name == "rag_search":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "要在本地知识库中检索的关键词/问题"},
            },
            "required": ["query"],
        }
    if name == "delegate_task":
        return {
            "type": "object",
            "properties": {
                "description": {"type": "string",
                                "description": "委派意图的总说明（发给每个子任务的背景）"},
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "子任务目标（自包含）"},
                            "context": {"type": "string", "description": "子任务补充上下文（可选）"},
                        },
                        "required": ["goal"],
                    },
                    "description": "可并行执行的子任务列表",
                },
            },
            "required": ["tasks"],
        }
    if name == "execute_code":
        from aimate.agents.code_exec import schema as _code_schema

        return _code_schema()
    return {"type": "object", "properties": {}}
