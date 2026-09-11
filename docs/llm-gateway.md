# 内网 LLM 推理网关（信创/私有化 · 数据不出域）

AIMate 把数字员工接到**内网模型**的统一入口。不内置任何云厂商 SDK：
只通过 OpenAI 兼容的 `/v1/chat/completions` 协议对接本地/内网推理服务
（llama.cpp / llama-server、vLLM、Ollama、OneAPI 等任意 OpenAI 兼容网关），
做到**模型可替换、厂商无关、数据留内网**。

## 目录
- `aimate/llm/gateway.py` — `LLMConfig` / `OpenAICompatibleLLM` / `LLMGateway`（纯 stdlib + urllib）
- `configs/llm.gateway.json` — 客户侧部署配置模板
- CLI：`aimate gateway:test --config configs/llm.gateway.json`（连通性自检）
- CLI：`aimate server --llm-config configs/llm.gateway.json`（装配后分发真实推理）

## 配置
编辑 `configs/llm.gateway.json`：

```json
{
  "backends": {
    "inner-gateway": {
      "base_url": "http://127.0.0.1:8080",
      "api_key": "",
      "model": "qwen2.5:7b-instruct-q6_K",
      "timeout": 120.0,
      "max_retries": 2,
      "temperature": 0.2
    }
  },
  "aliases": { "logical-name": { "alias_of": "inner-gateway" } },
  "default": "inner-gateway"
}
```

- `base_url`：内网网关地址，**不含** `/v1`（客户端自动拼接 `/v1/chat/completions`）。
- `api_key`：为空表示免鉴权内网网关（如 llama-server / Ollama）。
- `model`：上游填模型名（llama-server 用 GGUF 别名，vLLM 用托管模型名）。
- `aliases`：逻辑别名 → 后端，数字员工 `Agent.model` 填逻辑名即可换模型。

## 能力
- **对话补全**：messages + 可选工具 schema（`tools`/`tool_choice=auto`），
  兼容严格 provider（配合 `api.normalize_tool_schema`）。
- **装配系统提示**：dispatch 时自动拼接 `SOUL(人格/边界) + 记忆快照 + RAG 检索上下文`。
- **超时/重试**：指数退避；4xx 判定为确定错误不重试。
- **成本/配额**：`estimate_tokens` / `estimate_cost`（内网自托管默认只计配额）。
- **审计**：每次分发/错误落审计日志（`llm.dispatch` / `llm.error`）。

## 已知约束（macOS 本机）
本机 python3 的 urllib 有 SSL 证书问题 —— 面向 **http** 内网端点即可；
若内网网关走 **https**，需在系统证书/内网 CA 中配置信任。
