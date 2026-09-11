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


def cmd_server(args) -> int:
    from aimate.gateway.api.api import GatewayAPI, ChatRequest
    from aimate.gateway.auth.auth import Role
    from aimate.system import build_system

    sys_ = build_system()
    sys_.bootstrap_demo()
    auth = sys_.auth
    api = GatewayAPI(auth)

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
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aimate", description="AIMate 国产企业级 AI 智能体平台")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("init", help="初始化并装配演示数据")
    sub.add_parser("server", help="启动服务端（演示骨架）")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "server":
        return cmd_server(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
