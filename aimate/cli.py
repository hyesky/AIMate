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


def cmd_curator(args) -> int:
    """自我进化：跑一轮技能策展（归档闲置、标记陈旧）。"""
    from aimate.system import build_system
    sys_ = build_system()
    res = sys_.run_curator()
    print(f"[AIMate] Curator 一轮策展完成：")
    print(f"  归档 {len(res['archived'])} 条闲置技能: {', '.join(res['archived']) or '无'}")
    print(f"  标记 {len(res['stale'])} 条陈旧技能: {', '.join(res['stale']) or '无'}")
    return 0


def cmd_server(args) -> int:
    from aimate.gateway.api.api import GatewayAPI, ChatRequest
    from aimate.gateway.auth.auth import Role
    from aimate.system import build_system

    sys_ = build_system()
    sys_.bootstrap_demo()
    cfg = getattr(args, "llm_config", None)
    if cfg:
        sys_.configure_llm(cfg)
        print(f"[AIMate] 已装配内网 LLM 网关: {cfg}")
    else:
        print("[AIMate] 未装配内网 LLM（骨架模式：分发为路由回显）。"
              "用 --llm-config configs/llm.gateway.json 接入内网模型。")
    auth = sys_.auth
    api = GatewayAPI(auth, system=sys_)

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


def cmd_gateway_test(args) -> int:
    """验证内网 LLM 网关连通性（不依赖真实模型/可在代理前自检）。"""
    import json
    from aimate.llm import LLMError, LLMGateway

    cfg = getattr(args, "config", None)
    if not cfg:
        print("[gateway:test] 用法: --config configs/llm.gateway.json")
        return 2
    try:
        data = json.load(open(cfg, "r", encoding="utf-8"))
    except OSError as e:
        print(f"[gateway:test] 无法读取配置 {cfg}: {e}")
        return 2
    gw = LLMGateway(data.get("backends", {}))
    target = data.get("default", "")
    print(f"[gateway:test] 后端注册: {list(gw._backends)} 别名: {list(gw._aliases)}")
    if not gw._backends:
        print("[gateway:test] 无任何后端——配置为空。")
        return 2
    try:
        backend = gw.resolve(target)
        print(f"[gateway:test] 目标后端: {target} -> {backend.config.base_url} "
              f"model={backend.config.model}")
        resp = backend.chat([{"role": "user", "content": "ping"}])
        print(f"[gateway:test] OK ✅ 返回: {backend.reply_text(resp)[:120]!r} "
              f"finish={backend.finish_reason(resp)}")
        print(f"[gateway:test] 本请求约消耗 {gw.estimate_tokens('ping')} token")
        return 0
    except LLMError as e:
        print(f"[gateway:test] 连接失败 ❌: {e}")
        if e.status and e.status < 500:
            print("[gateway:test] 提示: 4xx 为配置/鉴权问题，请核对 base_url/api_key/model")
        else:
            print("[gateway:test] 提示: 确认内网模型服务已起（llama-server/vLLM/Ollama）"
                  "且本机可访问该端点")
        return 1


def cmd_console(args) -> int:
    """启动浏览器管控台（信创首发 · 纯 stdlib HTTP）。"""
    from aimate.system import build_system
    from aimate.web.console import serve

    sys_ = build_system()
    sys_.bootstrap_demo()
    cfg = getattr(args, "llm_config", None)
    if cfg:
        sys_.configure_llm(cfg)
        print(f"[AIMate] 已装配内网 LLM 网关: {cfg}")
    else:
        print("[AIMate] 未装配内网 LLM（分发为骨架回显）。"
              "--llm-config 接入内网模型后即可真实对话。")

    agent_ids = sys_.api and [sys_.demo_agent.id] or []
    host, port = getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8900)
    srv = serve(host, port, system=sys_, agent_ids=agent_ids)
    print(f"[AIMate] 🔗 管控台已启动:  http://{host}:{port}")
    print("[AIMate] 浏览器打开即可操作数字员工 / RAG / 审计。Ctrl+C 退出。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[AIMate] 已退出。")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aimate", description="AIMate 国产企业级 AI 智能体平台")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("init", help="初始化并装配演示数据")
    p_server = sub.add_parser("server", help="启动服务端（演示骨架）")
    p_server.add_argument("--llm-config", help="内网 LLM 网关 JSON 配置路径")
    p_console = sub.add_parser("console", help="启动浏览器管控台（信创首发）")
    p_console.add_argument("--llm-config", help="内网 LLM 网关 JSON 配置路径")
    p_console.add_argument("--host", default="127.0.0.1", help="监听地址")
    p_console.add_argument("--port", type=int, default=8900, help="监听端口")
    p_learn = sub.add_parser("learn", help="自进化：把来源沉淀为技能(prompt)")
    p_learn.add_argument("source", help="技能来源：目录/URL/工作流/粘贴资料")
    p_learn.add_argument("--context", help="附加上下文(如'本次会话刚做完的事')")
    p_gt = sub.add_parser("gateway:test", help="验证内网 LLM 网关连通性")
    p_gt.add_argument("--config", help="网关 JSON 配置路径")
    sub.add_parser("curator", help="自我进化：跑一轮技能策展(归档闲置/标记陈旧)")
    args = p.parse_args(argv)
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "server":
        return cmd_server(args)
    if args.cmd == "console":
        return cmd_console(args)
    if args.cmd == "learn":
        return cmd_learn(args)
    if args.cmd == "gateway:test":
        return cmd_gateway_test(args)
    if args.cmd == "curator":
        return cmd_curator(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
