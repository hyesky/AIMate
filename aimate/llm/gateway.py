"""内网 LLM 网关：把数字员工接到私有化/内网模型后端。

信创/私有化要点：模型权重与推理全程不出内网（数据不出域）。AIMate 不内置
任何云厂商 SDK——只通过 OpenAI 兼容的 /v1/chat/completions 明文协议对接
本地或内网的推理服务（llama.cpp / llama-server、vLLM、Ollama、OneAPI
等任意 OpenAI 兼容网关），做到"模型可替换、厂商无关、数据留内网"。

设计（借鉴开源 agent 蓝本 + 自研）：
- Provider 抽象：内网统一走 http（OpenAI 兼容）；留出本地进程/多路网关扩展口。
- 别名映射：model_aliases 用 dict 把逻辑名(如 inner-gateway)映射到实际
  {base_url, api_key, model}，客户改一行配置即可换模型。
- 对话补全：messages 列表 + 可选工具 schema 注入上游（供严格 provider 拒收防护）。
- 超时/重试：握手超时 & 稳妥默认重试，网关兜底。
- prompt/字节成本估算：内网 LLM 计费/配额/审计用，纯近似。

实现为纯标准库（M0 零第三方运行时依赖）：只依赖 urllib.request + json。
注意本机 python 的 urllib 有 SSL 证书问题 -> 主要面向 http 内网端点；
如需 https 内网网关，由系统证书/内网 CA 管理。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """网关级错误（连接/鉴权/超时/上游 4xx/5xx）。"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class LLMConfig:
    """内网模型端点配置（一份配置 = 一个可对接的后端）。"""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "default",
        timeout: float = 60.0,
        max_retries: int = 2,
        temperature: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature

    @classmethod
    def from_dict(cls, cfg: dict) -> "LLMConfig":
        return cls(
            base_url=cfg["base_url"],
            api_key=str(cfg.get("api_key", "")),
            model=str(cfg.get("model", "default")),
            timeout=float(cfg.get("timeout", 60.0)),
            max_retries=int(cfg.get("max_retries", 2)),
            temperature=float(cfg.get("temperature", 0.2)),
        )


class OpenAICompatibleLLM:
    """OpenAI 兼容 /v1/chat/completions 客户端（内网私有化网关）。

    不引入 openai SDK——用 urllib 直连，兼容 llama-server / vLLM / Ollama
    / OneAPI 等任意 OpenAI 兼容端点。支持非流式对话 + 工具 schema 透传。
    """

    CHAT_PATH = "/v1/chat/completions"

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    # ---- 底层 POST ----
    def _post(self, payload: dict) -> dict:
        url = self.config.base_url + self.CHAT_PATH
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        last_err: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            if attempt > 0:
                time.sleep(min(2 ** attempt, 4))  # 指数退避
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:  # noqa: S310 内网网关
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code < 500:
                    # 4xx 为确定错误(鉴权/参数)，不重试
                    body = e.read().decode("utf-8", "replace")[:200]
                    raise LLMError(f"上游 {e.code}: {body}", status=e.code) from e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = e
        raise LLMError(f"内网 LLM 网关请求失败（重试 {self.config.max_retries} 次）: {last_err}")

    # ---- 对话补全 ----
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        """返回 OpenAI 兼容响应 dict（choices[0].message 等）。"""
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return self._post(payload)

    # ---- 便捷解析 ----
    def reply_text(self, resp: dict) -> str:
        """从补全响应提取最终文本。"""
        try:
            msg = resp["choices"][0]["message"]
            return msg.get("content") or ""
        except (KeyError, IndexError):
            return ""

    def finish_reason(self, resp: dict) -> str:
        try:
            return resp["choices"][0].get("finish_reason", "")
        except (KeyError, IndexError):
            return ""

    def tool_calls(self, resp: dict) -> list[dict]:
        try:
            return resp["choices"][0]["message"].get("tool_calls") or []
        except (KeyError, IndexError):
            return []


# ---------------------------------------------------------------------------
# 网关注册表 + 别名映射（借鉴开源 model_aliases 配置思想，自研实现）
# 客户通过一份内网配置文件声明可用后端，逻辑名 -> 实际端点。
# ---------------------------------------------------------------------------
class LLMGateway:
    """内网 LLM 网关门面：管理多个后端、按别名路由、统一计费/审计钩子。"""

    def __init__(self, configs: dict[str, dict] | None = None) -> None:
        self._backends: dict[str, OpenAICompatibleLLM] = {}
        self._aliases: dict[str, str] = {}  # 逻辑别名 -> 后端名
        if configs:
            self.configure(configs)

    def configure(self, configs: dict[str, dict]) -> None:
        """configs: {"后端名": {...LLMConfig字段}, "别名": {"alias_of": "后端名"}}"""
        for name, cfg in configs.items():
            if set(cfg) == {"alias_of"}:
                self._aliases[name] = str(cfg["alias_of"])
            else:
                self._backends[name] = OpenAICompatibleLLM(LLMConfig.from_dict(cfg))

    def resolve(self, alias: str) -> OpenAICompatibleLLM:
        """按逻辑别名取后端；支持二级别名表查。"""
        target = self._aliases.get(alias, alias)
        if target not in self._backends:
            raise LLMError(f"未配置模型后端: {alias}")
        return self._backends[target]

    def chat(
        self,
        alias: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kw: Any,
    ) -> dict:
        return self.resolve(alias).chat(messages, tools=tools, **kw)

    # ---- 成本/配额 近似（内网 LLM 计费/审计用） ----
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略近似：中文多字/词权重高，拉丁词按空格分词。仅用于配额近似。"""
        if not text:
            return 0
        latin = sum(1 for w in text.split() if w.isascii())
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        return latin + cjk + max(0, len(text) - latin - cjk) // 3

    @staticmethod
    def estimate_cost(tokens: int, per_1k: float = 0.0) -> float:
        """按每千 token 单价算成本（默认 0，内网自托管通常只计配额）。"""
        return tokens / 1000.0 * per_1k
