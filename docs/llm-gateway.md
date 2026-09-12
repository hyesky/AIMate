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

## 实测：接入本机 llama-server（Ornith-35B · 信创内网）
本机 `llama-server`（`configs/llm.gateway.json` 里指向 `http://127.0.0.1:8080`）：

```bash
# 模型名必须与 /v1/models 返回的 id 一致
curl -s http://127.0.0.1:8080/v1/models | python3 -m json.tool
aimate gateway:test --config configs/llm.gateway.json   # 连通性
aimate console --llm-config configs/llm.gateway.json    # 管控台真实对话
```

实测结果：
- `gateway:test` ✅ 返回真实模型回复（2 token 自检）。
- dispatch 真实全链路 ✅：SOUL+记忆+RAG 上下文 → Ornith-35B 回答
  「如何保证数据不出域」，模型正确引用知识库并结构化输出，审计落 `llm.dispatch`。
- 常见 500 `Compute error`：多为 **llama-server 长时间运行后 MPS 状态损坏**（`ggml_metal_synchronize`），
  重启服务进程即可（与网关无关）。

## macOS / 小显存调参（M2 24GB 实测）
35B 视觉模型 + 超大 KV 缓存会触发 **Metal OOM**（`command buffer failed / Insufficient Memory`），
表现为短提示正常、带系统提示/RAG 的长上下文 500 `Compute error`。根治调参：

```bash
# 原：-c 65536 --cache-type-k q8_0 --cache-type-v q8_0   ← 24GB 上 KV 缓存过大
# 改：缩小 ctx + 换 q4_0 KV 缓存（省显存近半），text-first 可去掉 -mm 视觉投影
/opt/homebrew/bin/llama-server \
  -m Ornith-1.5-35B-A3B-CRACK-Q3_K_M.gguf \
  -c 16384 -np 1 -ngl 99 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  -b 512 -ub 128 --host 127.0.0.1 --port 8080
```
改后本机实测：短问答 3.9s、带 SOUL+RAG 上下文 27s，均正常。

## 已知约束（macOS 本机）
本机 python3 的 urllib 有 SSL 证书问题 —— 面向 **http** 内网端点即可；
若内网网关走 **https**，需在系统证书/内网 CA 中配置信任。
