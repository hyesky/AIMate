# AIMate 浏览器管控台（信创首发 · 零前端依赖）

一个**纯 stdlib 的 Web 管控台**——不用 Node、不用 npm、不用任何前端脚手架，
靠标准库 `http.server` 起单页 UI（内联 HTML + 原生 JS），让数字员工 /
RAG / 审计 / 内网 LLM 网关在浏览器里可视可操作。信创环境无需安装前端工具链。

## 启动
```bash
# 骨架模式（不接模型也能看 UI / 检索 / 审计）
PYTHONPATH=$PWD python3 -m aimate.cli console --port 8900

# 装配内网模型后真实对话
PYTHONPATH=$PWD python3 -m aimate.cli console --port 8900 \
    --llm-config configs/llm.gateway.json
```
浏览器打开 http://127.0.0.1:8900 。

## 布局（三栏）
- **左栏·平台状态 + 数字员工**：后端数、默认模型、数字员工/技能/审计计数、token 估算；点卡片切换对话对象。
- **中栏·对话**：输入指令发给当前数字员工，自动拼接 `SOUL + 记忆快照 + RAG 检索上下文` 后转发内网网关，显示回复/模型名/错误提示。
- **右栏·知识库检索 + 审计日志**：加权融合召回（带 kind/score）；审计实时滚动（3s 轮询）。

## 端点（可被自建前端复用）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/`            | 单页管控台 UI |
| GET  | `/api/info`    | 平台/网关概览 |
| GET  | `/api/agents`  | 数字员工列表 |
| POST | `/api/chat`    | 调度数字员工（复用内网网关） |
| POST | `/api/kb/search` | 知识库检索（加权融合） |
| GET  | `/api/audit`   | 审计日志 |

## 实现位置
- `aimate/web/console.py` — `ConsoleHandler`（路由/端点）+ `serve()`
- 复用 `System`（org/auth/memory/rag/llm/skills/audit）；数字员工经 `GatewayAPI.dispatch` 调度，审计照常落库。
- CORS 已开，方便将来接独立前端；绑定默认 `127.0.0.1` 保证信创内网安全默认值。

## 验证
- 自测 `console.*` 5 项端到端（页面/概览/员工/检索/骨架对话）。
- 真实浏览器实测：RAG 检索命中、对话调度、审计滚动均正常。
