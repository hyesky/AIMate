# 内网 MCP 工具库（信创 · 纯 stdlib）

把 AIMate 数字员工接到标准 **Model Context Protocol** 工具服务，扩展工具调用
能力，同时守住信创红线：**工具代码与数据全程不出域**，零第三方运行时依赖。

## 为什么这样设计
- **MCP = 工具的事实标准**：Anthropic 提出、被主流 agent 生态广泛采用。工具
  以 `inputSchema`（JSON Schema）自描述，模型按 schema 生成参数调用。
- **走 stdio 而非 HTTP**：stdio（本地子进程）天然不出域，可对接任意实现了
  `JSON-RPC 2.0 over stdio` 的 MCP server——无论是 Node/Python/Go 写的可信
  工具容器，还是国产化的工具服务。不依赖公网、不引入 SDK。
- **纯 stdlib**：收发只用到 `subprocess` + `json` + `select`，无第三方包。

## 模块
```
aimate/mcp/
├── __init__.py   # 导出 McpError / McpRegistry / StdioMcpClient
├── registry.py   # McpRegistry：多 server 管理 + JSON-RPC over stdio 客户端
└── demo.py       # 示例本地 stdio MCP server（自测与接线演示，3 个工具）
```

### registry.py
- `StdioMcpClient`：以子进程拉起 MCP server，按 **Content-Length 帧**（与官方
  MCP stdio 对齐）收发 `JSON-RPC 2.0` 消息：
  - `initialize` 握手（协议版本、能力声明）
  - `tools/list` 获取工具 schema
  - `tools/call` 调用工具（超时保护，可并发）
- `McpRegistry`：管理多个 server（`add_server` / `list_servers` / `tool_schemas`
  / `call_tool('server__tool', args)` / `remove` / `close_all`）。把每个 server
  的工具统一转成 OpenAI function schema，供数字员工工具集复用。

### demo.py（示例 server，3 个工具）
- `sum(numbers)` — 计算整数序列之和
- `sysinfo()` — 返回本机系统信息（内网信创自检）
- `kb_lookup(key)` — 查询内网知识库条目（演示工具接入 RAG）

> 生产对接：写一个自己的 `main`，`sys.stdin` 读 JSON、`sys.stdout` 逐帧写 JSON
> 即可成为数字员工的 MCP server；命令形如 `add_server('x', ['python3','-m','pkg.server'])`。

## 接入数字员工工具集
在管控台 `🔌 MCP` 面板输入 server 名 + 启动命令点「连接」；后端 `McpRegistry`
握手后把每个工具经 `api.register_tool()` 注册进调度器，模型即可在对话中按
schema 生成参数调用（工具名 `server__tool`）。

## 验证
- 自测 `mcp.*` 3 项：connect / tools(真实调用) / schema。
- 管控台 `console.mcp.*` 3 项：add（3 工具）/ call（`demo__sum`→`总和 = 60`）。
- 真实浏览器：MCP 面板连接 demo → 3 工具出现 → 调用 `demo__sum` → `总和 = 21`。
