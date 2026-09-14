"""P2b 子 Agent 委派（delegate_task）+ 多轮工具循环测试

用脚本化 FakeBackend 驱动 AgentRunner，验证：
  1. 多轮工具执行循环（LLM 返回 tool_calls -> 执行 -> 回填 -> 再 chat 至最终文本）
  2. 工具执行结果正确回填为 role=tool 消息
  3. rag_search 内置工具解析
  4. delegate_task 批量并行 + 子 Agent 隔离上下文 + summary 回收
  5. 递归委派屏蔽（子 Agent 工具集剔除 delegate_task）
  6. 超轮数兜底
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimate.llm.gateway import LLMGateway, LLMConfig  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ✔ {name}")


class ScriptBackend:
    """按脚本依次返回响应；记录全部入参（用于校验回填/隔离/工具集）。"""

    def __init__(self, config, script):
        self.config = config
        self.script = list(script)
        self.seen = []  # (role 序列, tools)

    def chat(self, messages, tools=None, **kw):
        self.seen.append((list(messages), list(tools or [])))
        if not self.script:
            return {"choices": [{"message": {"content": "（脚本耗尽）"},
                                 "finish_reason": "stop"}]}
        step = self.script.pop(0)
        if step == "rag":
            args = json.dumps({"query": "内网部署"}, ensure_ascii=False)
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "call_rag1", "type": "function",
                                "function": {"name": "rag_search",
                                             "arguments": args}}]},
                "finish_reason": "tool_calls"}]}
        if step == "rag2":
            args = json.dumps({"query": "License"}, ensure_ascii=False)
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "call_rag2", "type": "function",
                                "function": {"name": "rag_search",
                                             "arguments": args}}]},
                "finish_reason": "tool_calls"}]}
        return {"choices": [{"message": {"content": step}, "finish_reason": "stop"}]}

    def reply_text(self, resp):
        try:
            return resp["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError):
            return ""

    def finish_reason(self, resp):
        try:
            return resp["choices"][0].get("finish_reason", "")
        except (KeyError, IndexError):
            return ""

    def tool_calls(self, resp):
        try:
            return resp["choices"][0]["message"].get("tool_calls") or []
        except (KeyError, IndexError):
            return []


def fake_system(kb_docs=None):
    class FakeRag:
        def __init__(self, docs):
            self.docs = docs or ["AIMate 平台支持私有化内网部署。"]

        def search(self, query, top_k=3):
            hits = [d for d in self.docs if query in d]
            if not hits:
                hits = ["(无命中)"]
            return [type("H", (), {"text": h, "score": 1.0})() for h in hits[:top_k]]

    class FakeMCP:
        def __init__(self):
            self._schemas = {}

    class FakeSystem:
        pass

    s = FakeSystem()
    s.rag = FakeRag(kb_docs)
    s.mcp = FakeMCP()
    s.llm = LLMGateway()
    s.search_kb = lambda q: s.rag.search(q, top_k=3)
    return s


class RoutingGateway:
    """delegate 端到端：按子任务 goal 里的 c4aN 序号返回独立摘要。"""

    def __init__(self):
        self._cfg = LLMConfig.from_dict({"model": "m", "base_url": "x"})

    def resolve(self, alias):
        return self

    def chat(self, alias, messages, tools=None, **kw):
        first = next((m["content"] for m in messages if m.get("role") == "user"), "")
        m = re.search(r"c4a(\d)", first)
        idx = m.group(1) if m else "0"
        return {"choices": [{"message": {
            "content": f"对子任务 {idx} 的调研结论摘要"},
            "finish_reason": "stop"}]}

    def reply_text(self, resp):
        return resp["choices"][0]["message"].get("content") or ""

    def finish_reason(self, resp):
        return resp["choices"][0].get("finish_reason", "")

    def tool_calls(self, resp):
        return resp["choices"][0]["message"].get("tool_calls") or []


def main():
    from aimate.agents.runner import AgentRunner, DELEGATE_BLOCKED_TOOLS
    from aimate.agents.delegate import AgentsDelegate

    print("P2b 子 Agent 委派 + 多轮工具循环")

    # ---- 1) 多轮工具循环：rag_search -> 回填 -> 最终文本 ----
    s = fake_system(["AIMate 支持私有化内网部署。"])
    fake = ScriptBackend(LLMConfig.from_dict({"model": "m", "base_url": "x"}),
                         ["rag", "final"])
    s.llm._backends["b"] = fake
    r = AgentRunner(s, "b", turn_cap=6)
    text, trace = r.run([{"role": "user", "content": "怎么部署？"}])
    check("循环后得到最终文本", "final" in text)
    check("rag_search 已执行入 trace", any(t["tool"] == "rag_search" for t in trace))
    check("trace 记录工具命中文本",
          any("私有化内网部署" in t["result"] for t in trace))
    tool_msgs = [m for hist in fake.seen for m in hist[0]
                 if m.get("role") == "tool"]
    check("执行结果回填为 role=tool",
          any("私有化内网部署" in m.get("content", "") for m in tool_msgs))

    # ---- 2) 连续多工具轮 ----
    s2 = fake_system(["License 有效期", "内网部署"])
    fake2 = ScriptBackend(LLMConfig.from_dict({"model": "m", "base_url": "x"}),
                          ["rag", "rag2", "done2"])
    s2.llm._backends["b"] = fake2
    r2 = AgentRunner(s2, "b")
    t2, tr2 = r2.run([{"role": "user", "content": "部署与 License"}])
    check("连续多工具轮", t2 == "done2"
          and len([x for x in tr2 if x["ok"]]) == 2)

    # ---- 3) AgentRunner 内置工具 schema ----
    s3 = fake_system()
    r3 = AgentRunner(s3, "b")
    names = {s["function"]["name"] for s in r3.tool_schemas()}
    check("暴露内置工具", "rag_search" in names and "delegate_task" in names)
    child_names = {s["function"]["name"] for s in r3.tool_schemas()
                   if s["function"]["name"] not in DELEGATE_BLOCKED_TOOLS}
    check("子工具集剔除 delegate_task（防递归）",
          "delegate_task" not in child_names
          and "delegate_task" in DELEGATE_BLOCKED_TOOLS)

    # ---- 4) delegate 批量并行 + 隔离上下文 + summary 回收 ----
    s5 = fake_system()
    s5.llm = RoutingGateway()
    r5 = AgentRunner(s5, "b")
    d5 = AgentsDelegate(r5)
    res = d5.invoke({
        "description": "并行调研",
        "tasks": [{"goal": "研究 A c4a1", "context": "a"},
                  {"goal": "研究 B c4a2", "context": "b"},
                  {"goal": "研究 C c4a3", "context": "c"},
                  {"goal": "研究 D c4a4", "context": "d"}]},
    )
    check("委托返回 4 个结果", res["n"] == 4 and len(res["results"]) == 4)
    check("子任务全部成功",
          all(rr.get("ok") for rr in res["results"]))
    check("各子任务独立摘要",
          len({rr.get("summary") for rr in res["results"]}) == 4)

    # ---- 5) invoke 校验：空/坏任务 ----
    bad = d5.invoke({"tasks": []})
    check("空任务返回 error", "error" in bad)
    bad2 = d5.invoke({})
    check("缺 tasks 返回 error", "error" in bad2)

    # ---- 6) 超轮数兜底 ----
    s7 = fake_system(["x"])
    fake7 = ScriptBackend(LLMConfig.from_dict({"model": "m", "base_url": "x"}),
                          ["rag"] * 9)
    s7.llm._backends["b"] = fake7
    r7 = AgentRunner(s7, "b", turn_cap=3)
    t7, _ = r7.run([{"role": "user", "content": "hi"}])
    check("超轮数返回兜底文案", "上限" in t7)

    print(f"\nP2b 全部通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
