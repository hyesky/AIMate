"""P2d 事件钩子 hooks + 批量处理 batch 测试

验证：
  1. AgentRunner 事件钩子：on_tool_before/after、on_done 触发
  2. 钩子异常不影响主循环（吞掉）
  3. BatchRunner 批量并发处理并发回结果
  4. dataset JSONL 加载
  5. 批量汇总统计（total/success/tool_calls/avg_turns）
  6. 空 dataset 兜底
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimate.llm.gateway import LLMGateway, LLMConfig  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ✔ {name}")


class ScriptBackend:
    def __init__(self, config, script):
        self.config = config
        self.script = list(script)

    def chat(self, messages, tools=None, **kw):
        if self.script:
            step = self.script.pop(0)
        else:
            step = "done"
        if step == "rag":
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "rag_search",
                                             "arguments": json.dumps({"query": "内网部署"})}}]},
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
            return ""


def fake_system(kb=None):
    class R:
        def __init__(self, docs):
            self.docs = docs or ["AIMate 支持私有化内网部署。"]
        def search(self, q, top_k=3):
            return [type("H", (), {"text": d, "score": 1.0})()
                    for d in self.docs if q in d][:top_k] or \
                   [type("H", (), {"text": "(无)", "score": 0.0})()]
    class S:
        pass
    s = S()
    s.rag = R(kb)
    s.mcp = type("M", (), {"_schemas": {}})()
    s.llm = LLMGateway()
    s.search_kb = lambda q: s.rag.search(q, top_k=3)
    return s


def main():
    from aimate.agents.runner import AgentRunner
    from aimate.agents.batch import BatchRunner

    print("P2d 事件钩子 + 批量处理")

    # ---- 1) 事件钩子触发 ----
    s = fake_system(["AIMate 支持私有化内网部署。"])
    fake = ScriptBackend(LLMConfig.from_dict({"model": "m", "base_url": "x"}),
                         ["rag", "final"])
    s.llm._backends["b"] = fake
    r = AgentRunner(s, "b", turn_cap=5)
    events = []
    r.hook("on_tool_before", lambda **kw: events.append(("before", kw["name"])))
    r.hook("on_tool_after", lambda **kw: events.append(("after", kw["name"], kw["ok"])))
    r.hook("on_done", lambda **kw: events.append(("done", kw.get("text", ""))))
    text, _ = r.run([{"role": "user", "content": "怎么部署"}])
    check("on_tool_before 触发", any(e[0] == "before" and e[1] == "rag_search" for e in events))
    check("on_tool_after 触发且 ok", any(e[0] == "after" and e[1] == "rag_search" and e[2] for e in events))
    check("on_done 触发且带最终文本", any(e[0] == "done" and e[1] == "final" for e in events))

    # ---- 2) 钩子异常不影响主循环 ----
    s2 = fake_system()
    fake2 = ScriptBackend(LLMConfig.from_dict({"model": "m", "base_url": "x"}), ["ok2"])
    s2.llm._backends["b"] = fake2
    r2 = AgentRunner(s2, "b")
    def bad_hook(**kw):
        raise RuntimeError("hook boom")
    r2.hook("on_done", bad_hook)
    t2, _ = r2.run([{"role": "user", "content": "hi"}])
    check("钩子异常被吞掉，主循环正常", t2 == "ok2")

    # ---- 3) BatchRunner 批量并发 ----
    n = 6
    class Factory:
        def __init__(self):
            self.cnt = 0
        def __call__(self):
            self.cnt += 1
            sym = fake_system()
            sym.llm._backends["b"] = ScriptBackend(
                LLMConfig.from_dict({"model": "m", "base_url": "x"}),
                [f"批次答复{self.cnt}"])
            return AgentRunner(sym, "b")
    br = BatchRunner(Factory(), workers=4)
    dataset = [{"prompt": f"任务 {i}"} for i in range(n)]
    res = br.run(dataset)
    check("批量处理全部成功", res["total"] == n and res["success"] == n)
    check("失败计数为 0", res["failed"] == 0)
    check("每条返回独立摘要",
          len({x["summary"] for x in res["results"]}) == n)

    # ---- 4) dataset JSONL 加载 ----
    d = tempfile.mkdtemp(prefix="aimate_p2d_")
    jl = os.path.join(d, "ds.jsonl")
    with open(jl, "w", encoding="utf-8") as f:
        f.write(json.dumps({"prompt": "p1"}) + "\n")
        f.write("普通文本行\n")
        f.write(json.dumps({"prompt": "p2"}) + "\n")
    rows = BatchRunner.load_dataset(jl)
    check("JSONL 加载 3 行", len(rows) == 3)
    check("普通行被包装为 prompt", any("普通文本" in r.get("prompt", "") for r in rows))

    # ---- 5) 空 dataset 兜底 ----
    res0 = br.run([])
    check("空 dataset 返回 total=0", res0["total"] == 0 and res0["success"] == 0)

    print(f"\nP2d 全部通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
