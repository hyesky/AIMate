# AIMate — 国产企业级 AI 智能体平台

> **能干活** 的运行时 × **管得住** 的管理后端。
> 面向信创 / 私有化 / 内网部署的企业智能体平台：数字员工、知识库 RAG、Workflow、技能市场、成员与授权、License 门控，一条链闭环。

AIMate 是一个从零自主设计（路径 B'：借鉴开源蓝本的**架构思想**与**国产落地范式**，核心自研）的企业 AI 智能体平台。它把「Agent 运行时」和「管理控制台」绑在一起：

```
┌──────────────────────── 客户端（负责「用」） ───────────────────────┐
│  网页工作台 (client/web)   办公/运维/业务智能体客户端               │
└───────────────┬────────────────────────────────────────────────────┘
                ▼
┌──────────────────────── 统一接入（安全调度与通道接入） ──────────────┐
│  gateway/   IM 通道（企微/钉钉/飞书）+ OpenAPI + Anthropic-API      │
│             安全认证 (gateway/auth) + 统一接入 (gateway/api)        │
└───────────────┬────────────────────────────────────────────────────┘
                ▼
┌──────────────────────── 服务端 Server（负责「管」） ────────────────┐
│  agents/ 数字员工与 Agent 池      rag/ 知识库（切分/向量化/召回）    │
│  workflow/ 工作流编排              skills/ 技能市场+企业自建        │
│  memory/ 持久记忆                  org/ 成员与组织（RBAC/部门）      │
│  security/ 安全管理/审计/国密      license/ .lic 有效期与配额门控    │
└────────────────────────────────────────────────────────────────────┘
```

私有化部署时，**整套管控台跟着数据一起留在内网**；对话、知识库、审计、Embedding 全部可落客户侧（以实际网络边界为准），对话模型可指向内网推理网关。

## 能力总览

- **IM 通道**：企微 / 钉钉 / 飞书公司级通道（`gateway/channels/*`）
- **知识库 RAG**：本地知识库·切分、向量化、召回（`server/rag`）
- **数字员工**：智能体 / 专家（`server/agents`）
- **技能体系**：Skill 市场 + 企业自建，支持 agent 自沉淀与策展（`server/skills`）
- **成员与组织**：部门树、角色、邀请/导入（`server/org`）
- **浏览器工作台**：登录即可调度服务端智能体（`client/web`）
- **开放集成**：OpenAPI、Anthropic-API（`gateway/api`）
- **License**：`.lic` 模块、有效期与配额门控（`server/license`）
- **自我进化**：自动总结技能 + 有界且经筛选的持久记忆，跨会话保持记忆（`server/memory` + `server/skills`）
- **本地/内网大模型**：对话模型指向内网推理网关；Embedding 可落本机路径（`server/rag`）

## 快速开始

```bash
cd ~/projects/AIMate
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 初始化配置
aimate init

# 启动浏览器管控台（信创首发 · 纯 stdlib，无需前端工具链）
aimate console --port 8900

# 接入内网模型后即可真实对话（示例：本机 llama-server 的 Ornith-35B）
#   vi configs/llm.gateway.json   # 填 base_url/model/api_key
aimate console --llm-config configs/llm.gateway.json

# 验证内网网关连通性
aimate gateway:test --config configs/llm.gateway.json
```

浏览器打开 http://127.0.0.1:8900 即可操作数字员工 / 知识库 / 大模型配置 / 技能库 / MCP 工具库 / 审计。

> 管控台界面为 Hermes-Desktop 风格：左侧功能 rail + 各管理面板卡片，全程内联 JS、零第三方前端依赖。MCP 工具库走 stdio（数据不出域），可对接任意 JSON-RPC-over-stdio 工具服务。

## 文档

- `/docs/architecture.md` — 架构设计
- `/docs/compliance.md` — 信创合规与开源组件说明
- `/docs/roadmap.md` — 里程碑与人月拆分
- `/docs/llm-gateway.md` — 内网 LLM 推理网关（信创 · 数据不出域）
- `/docs/console.md` — 浏览器管控台（纯 stdlib · Hermes-Desktop 风格界面）
- `/docs/mcp.md` — 内网 MCP 工具库（纯 stdlib · JSON-RPC over stdio）
- `/docs/screenshots/` — 管控台界面截图

## 许可

Apache-2.0（支持私有化闭源交付，保留版权声明即可）。
