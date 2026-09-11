"""命令入口：aimate init / aimate server。"""
from __future__ import annotations

import argparse
import sys


def cmd_init(args) -> int:
    from aimate.system import build_system
    sys_ = build_system()
    sys_.bootstrap_demo()
    print("[AIMate] 初始化完成：数字员工 + 知识库 + 技能 + License 演示数据已就绪。")
    return 0


def cmd_learn(args) -> int:
    """自进化：基于输入来源沉淀一个技能（生成 authoring 标准 prompt）。"""
    from aimate.skills.learn import build_learn_prompt, validate_description
    from aimate.system import build_system

    sys_ = build_system()
    prompt = build_learn_prompt(args.source, getattr(args, "context", ""))
    print("[AIMate] 已生成技能沉淀 prompt（交给数字员工即可产出 SKILL.md）：\n")
    print(prompt[:2000])
    print("\n--- 校验示例 ---")
    ok, msg = validate_description("处理工单。")
    print(f"validate_description('处理工单。') -> ok={ok}, {msg}")
    return 0


def cmd_server(args) -> int:
    from aimate.gateway.api.api import GatewayAPI, ChatRequest
    from aimate.gateway.auth.auth import Role
    from aimate.system import build_system

    sys_ = build_system()
    sys_.bootstrap_demo()
    auth = sys_.auth
    api = GatewayAPI(auth)

    # 注册一个外部工具（示范工具 schema 归一化：故意给已包装 shape）
    api.register_tool({"type": "function", "function": {
        "name": "search_kb", "description": "检索企业知识库",
        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
    }})

    key = auth.issue_api_key("tenant-demo", Role.ADMIN)
    principal = auth.authenticate_api_key(key)
    assert principal is not None

    print("[AIMate] 服务端骨架启动（演示模式），API Key:", key)
    print("[AIMate] 分发测试 >>", api.dispatch(principal, ChatRequest(
        agent_id=sys_.demo_agent.id, tenant_id="tenant-demo",
        messages=[{"role": "user", "content": "你好"}],
    )))
    print("[AIMate] Anthropic 兼容 >>", api.anthropic_messages({
        "model": "claude-3-5-haiku", "messages": [{"role": "user", "content": "总结"}],
    }))
    print("[AIMate] 外部工具 schema 归一化 >>", api.tool_schemas())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aimate", description="AIMate 国产企业级 AI 智能体平台")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("init", help="初始化并装配演示数据")
    sub.add_parser("server", help="启动服务端（演示骨架）")
    p_learn = sub.add_parser("learn", help="自进化：把来源沉淀为技能(prompt)")
    p_learn.add_argument("source", help="技能来源：目录/URL/工作流/粘贴资料")
    p_learn.add_argument("--context", help="附加上下文(如'本次会话刚做完的事')")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "server":
        return cmd_server(args)
    if args.cmd == "learn":
        return cmd_learn(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
