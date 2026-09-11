# Hermes 借鉴设计思想 → AIMate 自研映射

> 本文件记录从开源 agent(如 Hermes) 源码中提炼的设计**思想**，
> 以及如何在 AIMate 中用**原创代码**落地。**只借鉴架构思想，不复制源码。**

## 1. 记忆门控：is_trivial_prompt

**借鉴思想**：部分用户消息(空/斜杠命令/纯打招呼/纯确认"ok/thanks/继续")不带语义信号，
唤起记忆召回是浪费(阻塞网络往返)且可能把过期上下文污染到一句话回复。

**AIMate 自研落地**：`aimate/memory/gate.py` — 独立正则门控模块，
MemoryManager 在 pre/post turn 调用它决定是否执行 recall/ingest。

## 2. MemoryManager: Provider 模式 + 后台异步

**借鉴思想**：记忆管理集中为单一 manager，委托给可插拔 provider；
turn 前 prefetch 预取、turn 后 sync 写回，异步不阻塞主循环。

**AIMate 自研落地**：`aimate/memory/manager.py` 已具备 add/replace/remove + 有界预算；
新增 `prefetch()` / `ingest()` + 线程池后台执行(不照搬其内部实现，仅借鉴接口节奏)。

## 3. /learn 无独立蒸馏引擎（规则内嵌 prompt）

**借鉴思想**：技能沉淀不需要单独的 NLP 蒸馏管道——把 authoring 标准(SKILL.md
格式、description≤60字符、小节顺序)写进 prompt，让 agent 用**现有工具**自己产出技能。
零模型工具额外足迹，本地/Docker/远程通用。

**AIMate 自研落地**：`aimate/skills/learn.py` — 生成一份中文 authoring 标准 prompt，
交付给数字员工即可沉淀技能。description 提供 ≤60 字符校验函数。

## 4. 技能渐进披露 + 知识库式布局

**借鉴思想**：技能不一次性全量注入系统提示(省 token)；先给索引(level0)，
用到才加载完整 body。超大知识库用"瘦 SKILL.md 索引 + references/ 按需加载"。

**AIMate 自研落地**：`aimate/skills/store.py` — `index_of()` 返回轻量标题+描述列表；
`load(name)` 才返回完整 body。文档类技能建议 references/ 拆分。

## 5. Curator: 惰性触发 + 只归档不硬删

**借鉴思想**：技能策展不用常驻定时器——agent 空闲且距上次超阈值时惰性触发；
只归档(可恢复)、永不自动删除；stale/archive 用活动时间阈值判定；有观点、
耗成本的 consolidate 合并默认关闭。

**AIMate 自研落地**：`aimate/skills/curator.py` — `maybe_run()` 惰性触发，
`archive_unused(stale_days, archive_days)` 纯归档；pinned 技能跳过。

## 6. 工具 schema 归一化（防严格 provider 拒收）

**借鉴思想**：不同 provider 期望不同的工具 schema 形状(裸函数 schema vs 已包
OpenAI tool 嵌套)。一个坏 schema 会让严格 provider(如 DeepSeek) 以
`tools[N].function: missing field name` 拒收**整个** toolset。故统一归一化。

**AIMate 自研落地**：`aimate/gateway/api/api.py` — `normalize_tool_schema()`
把两种形状归一到裸函数 schema；无法解析的丢弃并告警，不影响其余工具。
