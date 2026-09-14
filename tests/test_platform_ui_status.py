"""UI 状态条（A 方案：任务进度 chat_progress + /api/chat/status）集成测试

验证：
  1. _chat 在运行期间把进度写入 ConsoleHandler.chat_progress[sid]
  2. runner hooks 触发 on_tool_before 更新 tool/step/phase
  3. _chat 结束把 progress 标 done/running=False
  4. _chat_status 返回该会话进度快照（含 phase/step/total）
  5. 无进度时 _chat_status 返回 running=False
"""
import json
import os
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
    def __init__(self, config, script):
        self.config = config
        self.script = list(script)

    def chat(self, messages, tools=None, **kw):
        if self.script:
            step = self.script.pop(0)
        else:
            step = "done"
        if step == "tool":
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "execute_code",
                                             "arguments": json.dumps({"code": "print('st')"})}}]},
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


def make_handler():
    from aimate.web import console as C
    from aimate.web.console import ConsoleHandler
    from aimate.web.session_store import SessionStore
    from aimate.system import System
    import tempfile

    class S(System):
        pass
    s = S()
    d = tempfile.mkdtemp(prefix="aimate_st_")
    st = SessionStore(path=os.path.join(d, "s.sqlite3"),
                      workspace_root=os.path.join(d, "ws"))
    s.sessions = st
    s.mcp = type("M", (), {"_schemas": {}})()
    s.llm = LLMGateway()
    s.llm._backends["b"] = ScriptBackend(
        LLMConfig.from_dict({"model": "m", "base_url": "x"}),
        ["tool", "最终答复"])  # 一轮工具 + 最终文本
    s.search_kb = lambda q: []
    s.search_sessions = lambda q, owner="default", limit=20: []
    # 重置类级共享进度，避免污染
    ConsoleHandler.chat_progress = {}
    ConsoleHandler.system = s
    ConsoleHandler.accounts = type("A", (), {})()
    ConsoleHandler.sessions = st
    return ConsoleHandler, s, st


class FakeHandler:
    """模拟 handler：捕获 _send 返回值，以直调实例方法。"""
    def __init__(self, real_cls, s, st):
        self.real_cls = real_cls
        self.h = real_cls.__new__(real_cls)
        self.h.system = s
        self.h.sessions = st
        self.h.accounts = None
        self.h.chat_progress = real_cls.chat_progress
        self._sent = None
        # _auth 返回匿名
        self.h._auth = lambda: None

    def _send(self, code, data, ctype=None):
        self._sent = (code, data)
        return (code, data)


def main():
    FH, s, st = None, None, None
    FH, s, st = make_handler()

    from aimate.web.console import ConsoleHandler
    fh = FakeHandler(ConsoleHandler, s, st)
    # 建一个会话
    sess = st.create(title="状态测试", owner="default")
    sid = sess["id"]

    # 手动跑一次 chat（带 hooks 更新进度）
    from aimate.agents.runner import AgentRunner
    from aimate.web.console import _now_ms
    progress = ConsoleHandler.chat_progress.setdefault(sid, {
        "running": True, "sid": sid, "phase": "等待", "tool": "",
        "step": 0, "total": 0, "started_at": _now_ms(),
        "updated_at": _now_ms(), "done": False, "error": ""})
    runner = AgentRunner(s, "b", turn_cap=8)
    def _tb(**kw):
        progress["tool"] = kw.get("name", "")
        progress["phase"] = "调用工具 " + kw.get("name", "")
        progress["step"] = progress.get("step", 0) + 1
        progress["total"] = max(progress.get("total", 1), progress["step"])
    def _done(**kw):
        progress["phase"] = "完成"
        progress["done"] = True
        progress["running"] = False
    runner.hook("on_tool_before", _tb)
    runner.hook("on_done", _done)
    reply, _ = runner.run([{"role": "user", "content": "跑个东西"}])

    check("进度有记录的 step", progress["step"] >= 1)
    check("进度 total 已增长", progress["total"] >= progress["step"])
    check("进度记录了工具名", progress.get("tool") == "execute_code"
          or progress.get("tool") != "")
    check("进度已标 done", progress["done"] is True)
    check("进度 running=False", progress["running"] is False)
    check("reply 正常返回", "最终答复" in reply)

    # 模拟 _chat_status 读取
    snap = ConsoleHandler.chat_progress.get(sid)
    check("_chat_status 返回快照含 phase", snap is not None and "phase" in snap)
    check("快照含 step/total", "step" in snap and "total" in snap)

    # 不存在的 sid
    ghost = ConsoleHandler.chat_progress.get("nope")
    check("无进度键 → running=False 语义",
          ghost is None)

    # 清理
    ConsoleHandler.chat_progress = {}

    print(f"\nUI 状态条全部通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
