"""P2c 代码执行 execute_code + 沙箱集成测试

验证：
  1. execute_code 正常执行并回收 stdout
  2. 语法错误 / 非零退出返回 ok=False
  3. 超时被中止（TimeoutExpired）
  4. 大输出按字节截断（保留头尾 + 标注省略）
  5. 环境清洗不注入密钥
  6. 注册进 AgentRunner 内置工具 + tool_schemas 可见 + 经执行器可调
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


def main():
    from aimate.agents.code_exec import execute_code
    from aimate.agents.runner import AgentRunner

    print("P2c 代码执行 execute_code")

    # ---- 1) 正常执行 ----
    r = execute_code("print('hello from exec'); print(1+1)")
    check("正常执行返回 ok", r["ok"] is True)
    check("回收 stdout", "hello from exec" in r["stdout"] and "2" in r["stdout"])

    # ---- 2) 错误返回 ok=False ----
    r2 = execute_code("x = 1/0")
    check("运行时错误 ok=False", r2["ok"] is False)
    check("错误信息进 stderr", "ZeroDivisionError" in (r2["stderr"] or ""))

    # ---- 3) 超时 ----
    r3 = execute_code("import time; time.sleep(5)", timeout=0.5)
    check("超时被中止", r3.get("timeout") is True and r3["ok"] is False)

    # ---- 4) 大输出截断 ----
    r4 = execute_code("for i in range(20000): print('x'*5)")
    check("大输出标记截断", r4["truncated"] is True)
    check("截断标注省略字节", "省略" in r4["stdout"] or "..." in r4["stdout"])
    # 50KB 上限；截断后应明显小于输入总量
    check("截断后长度受控", len(r4["stdout"]) < 100 * 1024)

    # ---- 5) 环境清洗 ----
    os.environ["AIMATE_API_KEY"] = "SECRET_TOKEN_XYZ"
    r5 = execute_code("import os; print(os.environ.get('AIMATE_API_KEY','EMPTY'))")
    check("密钥不进子进程环境", "SECRET" not in r5["stdout"])

    # ---- 6) 注册进 runner ----
    class FakeSystem:
        pass
    s = FakeSystem()
    s.mcp = type("M", (), {"_schemas": {}})()
    s.llm = LLMGateway()
    s.search_kb = lambda q: []
    runner = AgentRunner(s, "b")
    names = {t["function"]["name"] for t in runner.tool_schemas()}
    check("execute_code 在内置工具集", "execute_code" in names)

    # 经执行器调用（不走 LLM，直接调内部）
    out = runner._dispatch_tool("execute_code", {"code": "print('via-runner')"})
    check("执行器可直接调用 execute_code",
          isinstance(out, dict) and "via-runner" in out.get("stdout", ""))

    print(f"\nP2c 全部通过 ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
