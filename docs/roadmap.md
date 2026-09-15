# AIMate 里程碑与人月拆分（路径 B'）

## MVP（M0 — 可演示骨架，已交付）
- [x] 四层目录骨架（client / gateway / server / pkg）
- [x] 运行时核心：Agent 池、记忆管理（有界+自进化）、RAG（BM25+hybrid 接口）
- [x] Workflow DAG 引擎、技能 Store + Curator、Org/RBAC、审计+国密封装、License 门控
- [x] 网关：认证 + OpenAPI/Anthropic 兼容 + 飞书通道（骨架）
- [x] CLI：`aimate init` / `aimate server`（无第三方运行时依赖即可跑通）
- [x] 文档：README / architecture / compliance

## M1 — 内网可用（约 6–8 人月）
- [ ] 持久化：SQLite → 达梦/人大金仓/OceanBase 适配层
- [ ] 对话接入内网 LLM 网关（vLLM/MLX/国产），非骨架式调度
- [ ] 完整 IM 接线：飞书（lark-oapi 完整实现）、企微、钉钉
- [ ] 管理后端 Web 工作台（成员/授权/模型/知识/License）前端落地
- [ ] Embedding 落本机/内网路径，RAG 生产化（切分/向量/召回调优）
- [ ] 技能市场 UI + 企业自建审批流

## M2 — 生产化（约 8–10 人月）
- [ ] 多节点数字员工注册进管控台、统一调度与故障转移（注册/枚举/启停已落地，调度与故障转移待续）
- [ ] 审计合规：全链路审计 + 等保 2.0/3.0 对齐 + 国密 SM2/3/4 合规实现
- [x] 自我进化生产化：Curator 后台任务、技能版本与回滚、记忆合并治理
- [ ] License 商业化：在线激活/离线.lic、配额弹性
- [ ] 安全：提示注入防护、权限最小化、数据防泄漏

## 里程碑备注
- 自研占比目标：运行时 + 管理后端 + RAG/Workflow 全部自研；仅复用宽松许可开源库。
- 协作模式：核心复用（若启用）仅作**架构参考**，交付物代码为原创。
