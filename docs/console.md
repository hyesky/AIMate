# AIMate 浏览器管控台（信创首发 · 零前端依赖）

一个**纯 stdlib 的 Web 管控台**——不用 Node、不用 npm、不用任何前端脚手架，
靠标准库 `http.server` 起单页 UI（内联 HTML + 原生 JS），让数字员工 / RAG /
内网 LLM 网关 / 技能库 / MCP 工具库在浏览器里可视可操作。信创环境无需安装
前端工具链。界面风格参考 Hermes Desktop（左侧功能导航 rail + 深色面板卡片）。

## 启动
```bash
# 骨架模式（不接模型也能看 UI / 检索 / 管理 / 审计）
PYTHONPATH=$PWD python3 -m aimate.cli console --port 8900

# 装配内网模型后真实对话（并加载真实后端）
PYTHONPATH=$PWD python3 -m aimate.cli console --port 8900 \
    --llm-config configs/llm.gateway.json
```
浏览器打开 http://127.0.0.1:8900 。

## 界面（左侧 rail 导航 + 各功能面板）
左侧固定窄 rail（Hermes-Desktop 风格）+ 主区卡片面板，共 6 个视图：

| 图标 | 视图 | 能力 |
|---|---|---|
| 💬 | 对话 | 对当前数字员工发指令，自动拼 `SOUL + 记忆 + RAG 上下文` 接内网网关 |
| 📚 | 知识库 | 录入/索引入库/清空文档；检索；枚举已索引文档（doc_id/分块/预览） |
| 🧠 | 大模型 | 注册内网后端（base_url/model）、列出已配置后端、测试连通性 |
| 🧩 | 技能库 | 创建技能（AUTO/DRAFT/PUBLISHED）、切换状态、列表 |
| 🔌 | MCP | 接入 stdio MCP server、列出工具、调用工具、移除 server |
| 🛡 | 审计 | 实时滚动审计日志（3s 轮询） |

## 端点（可被自建前端复用）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/`                     | 单页管控台 UI |
| GET  | `/api/info`             | 平台/网关概览 |
| GET  | `/api/agents`           | 数字员工列表 |
| POST | `/api/chat`             | 调度数字员工（复用内网网关） |
| POST | `/api/kb/search`        | 知识库检索（加权融合） |
| GET  | `/api/kb/docs`          | 枚举已索引文档 |
| POST | `/api/kb`               | 录入/索引入库文档 |
| POST | `/api/kb/clear`         | 清空知识库 |
| GET  | `/api/llm`              | 已配置后端列表 |
| POST | `/api/llm`              | 注册内网后端 |
| POST | `/api/llm/test`         | 测试后端连通性 |
| GET  | `/api/skills`           | 技能列表 |
| POST | `/api/skills`           | 创建技能 |
| POST | `/api/skills/status`    | 切换技能状态 |
| GET  | `/api/mcp`              | MCP server/工具列表 |
| POST | `/api/mcp`              | 连接 stdio MCP server（并注册进数字员工工具集） |
| POST | `/api/mcp/call`         | 调用 MCP 工具 |
| POST | `/api/mcp/remove`       | 移除 MCP server |
| GET  | `/api/audit`            | 审计日志 |

## 实现位置
- `aimate/web/console.py` — `ConsoleHandler`（路由/端点 + Hermes-Desktop 风格单页前端）+ `serve()`
- `aimate/mcp/` — 内网 MCP 工具库（纯 stdlib JSON-RPC over stdio）：`registry.py`（McpRegistry + 客户端）、`demo.py`（示例 server）
- 复用 `System`（org/auth/memory/rag/llm/skills/audit/mcp）；数字员工经 `GatewayAPI.dispatch` 调度，审计照常落库。
- CORS 已开，方便将来接独立前端；绑定默认 `127.0.0.1` 保证信创内网安全默认值。

## 验证
- 自测 `console.*` / `kb.*` / `skills.*` / `mcp.*` 端到端（页面/概览/员工/检索/骨架对话/四模块管理）。
- 真实浏览器实测：四面板 DOM 渲染、KB 录入与枚举、LLM 后端注册、MCP demo 连接与调用（`demo__sum`→`总和 = 21`）均正常。
- 截图见 `docs/screenshots/`。
