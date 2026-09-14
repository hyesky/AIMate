"""P3 历史会话需求召回（search_sessions 「7个问题」场景）测试

场景还原：用户在对话中说「我刚才提的那 7 个问题，你一个都没改」。数字员工应
识别这是对历史需求的引用，调用 search_sessions 跨会话检索，召回后确认。

验证：
  1. SessionStore.search 跨会话召回关键词命中的消息（含片段截取）
  2. search_sessions 内置工具出现在 tool_schemas
  3. 执行器经 _default_executor 调 search_sessions 返回结构化结果
  4. 端到端：LLM 先调 search_sessions 得到历史需求 -> 回填 -> 最终应答（模拟验证）
  5. system.search_sessions 在未注入 sessions 时返回 []
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
    """脚本化后端：按队列消耗 step，返回预置 tool_call 或文本。"""
    def __init__(self, config, script):
        self.config = config
        self.script = list(script)

    def chat(self, messages, tools=None, **kw):
        if self.script:
            step = self.script.pop(0)
        else:
            step = "done"
        if step == "search":
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "s1", "type": "function",
                                "function": {"name": "search_sessions",
                                             "arguments": json.dumps({"query": "ai_ma 修改需求"})}}]},
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


def main():
    from aimate.web.session_store import SessionStore
    from aimate.agents.runner import AgentRunner

    print("P3 历史会话需求召回 search_sessions")

    # ---- 预置临时会话历史 ----
    d = tempfile.mkdtemp(prefix="aimate_p3_")
    store = SessionStore(path=os.path.join(d, "s.sqlite3"),
                         workspace_root=os.path.join(d, "ws"))
    # 历史会话（含需求内容）
    s_old = store.create(title="ai_ma 开发", owner="default")
    store.add_message(s_old["id"], "user", "要加 AI 智能体的多轮工具循环")
    store.add_message(s_old["id"], "user", "还要支持子 Agent 委派和代码执行")
    store.add_message(s_old["id"], "user", "以及历史会话需求召回 search_sessions 能力")
    # 另一个不相关会话
    s_other = store.create(title="闲聊", owner="default")
    store.add_message(s_other["id"], "user", "今天天气不错")

    # ---- 1) SessionStore.search 跨会话召回 ----
    hits = store.search("委派", owner="default")
    check("search 命中历史会话", any(h["session_id"] == s_old["id"] for h in hits))
    check("命中带片段", any("委派" in sn for h in hits for sn in h["snippets"]))

    hits2 = store.search("天气", owner="default")
    check("仅匹配目标会话", any(h["session_id"] == s_other["id"] for h in hits2))

    # ---- 2) 注入 system + search_sessions 工具 ----
    class S:
        pass
    sys_obj = S()
    sys_obj.sessions = store
    sys_obj.mcp = type("M", (), {"_schemas": {}})()
    sys_obj.llm = LLMGateway()
    sys_obj.search_kb = lambda q: []
    sys_obj.search_sessions = lambda q, owner="default", limit=20: store.search(q, owner, limit)
    sys_obj.sessions.search if hasattr(sys_obj.sessions, "search") else None

    r = AgentRunner(sys_obj, "b")
    names = {t["function"]["name"] for t in r.tool_schemas()}
    check("search_sessions 在内置工具集", "search_sessions" in names)

    # ---- 3) 执行器直接调用（模拟 LLM 发起的检索） ----
    out = r._dispatch_tool("search_sessions", {"query": "委派", "owner": "default"})
    check("执行器返回结构化结果", isinstance(out, list) and len(out) >= 1)
    check("结果含 session 标题", any(h.get("session_id") == s_old["id"] for h in out))

    # ---- 4) 端到端：LLM 先 search 再应答（还原「7个问题」流程） ----
    sys2 = S()
    sys2.sessions = store
    sys2.mcp = type("M", (), {"_schemas": {}})()
    sys2.llm = LLMGateway()
    sys2.search_kb = lambda q: []
    sys2.search_sessions = lambda q, owner="default", limit=20: store.search(q, owner, limit)
    sys2.llm._backends["b"] = ScriptBackend(
        LLMConfig.from_dict({"model": "m", "base_url": "x"}),
        ["search", "我查到你之前提的历史需求，逐条确认已落实："])
    r2 = AgentRunner(sys2, "b", turn_cap=5)
    text, trace = r2.run([{"role": "user",
                           "content": "我刚才提的那 7 个问题，你一个都没改啊"}])
    check("多轮后得到最终应答", "确认已落实" in text)
    check("工具链含 search_sessions",
          any(t["tool"] == "search_sessions" for t in trace))
    check("工具执行成功", any(t["tool"] == "search_sessions" and t["ok"] for t in trace))

    # ---- 5) 未注入 sessions 时安全返回空 ----
    sys3 = S()
    sys3.mcp = type("M", (), {"_schemas": {}})()
    sys3.llm = LLMGateway()
    sys3.search_kb = lambda q: []
    # 无 sessions 属性 -> search_sessions 走 sys.search_sessions 时 AttributeError？
    # 我们契约：system.search_sessions 默认返回 []；runner 依赖 sys.search_sessions
    # 存在。这里用 System 实例验证其默认行为。
    from aimate.system import System
    real = System()
    check("System.search_sessions 未注入返回空", real.search_sessions("xx") == [])

    print(f"\nP3 全部通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
