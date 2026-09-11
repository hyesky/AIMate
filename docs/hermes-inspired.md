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

---

# OpenOcta 借鉴映射（Go → Python 自研，参考不照搬）

> 参考对象：github.com/openocta/openocta（Apache-2.0，431 个 Go 文件 / ~6.7 万行）。
> 思想引自 @summary Go 源码勘察（/tmp/octa），本文件只记录**借鉴的架构思想**与
> **AIMate 原创实现位置**，不复制任何 Go 源码。两者对应模块逐一比对后落地。

## A. RAG：归一化加权融合（超越纯 RRF）

**借鉴思想**（`src/pkg/agent/knowledge/engine.go`）：
稀疏(Bleve)+稠密(向量) 检索的融合不是只按排名(RRF)，而是**各自 min-max 归一化后
按可配权重加权**（text 0.55 / vec 0.45）；先取 `limit×3` 候选**放大再重排**；
摘要**按查询词在全文位置定位**截取而非从头截断；可**按 kinds(memory/rules/skills/tools)
限定检索域**。

**AIMate 自研落地**：`aimate/rag/engine.py` —
`KnowledgeBase(search fusion='weighted'|'rrf')`；`_normalize`(归一化)、
`_make_snippet`(查询词定位摘要)、`index(kind=...)`(kinds 过滤)、`candidate_mult`(召回放大)。
保留 RRF 作无向量/降级路径，两者可切换。

## B. 记忆库：内容安全 + 原子写 + 多目标

**借鉴思想**（`src/pkg/agent/evolution/store.go` + `scan.go`）：
- **内容安全扫描**：写入持久记忆前检测**提示注入**（覆盖指令/角色劫持/欺骗隐藏/
  绕过限制等威胁模式）+ **不可见 Unicode**(零宽字符混淆)——否则污染后续每个
  会话的系统提示，构成长期后门。
- **原子写入**：temp 文件 + rename，防断电/崩溃损坏记忆文件。
- **多目标扩展**：支持 `memory/user/soul/prompt`(可进化的系统提示+人格层)。
- **写去重 + 命中歧义检测**：同内容不重复追加；replace 匹配多条时报"更具体"。

**AIMate 自研落地**：
- `aimate/security/prompt_injection.py`(新)— `find_threat`/`find_invisible_unicode`/
  `scan`，中英双语威胁模式 + BOM 白名单。
- `aimate/memory/manager.py` — `VALID_TARGETS_EXT`(soul/prompt)、add/replace 前置
  `_scan` 安全拦截、add 去重；`FileMemoryStore`(新)— 原子写 + `set_limit` 逐目标限额 +
  `persist`/`load_all` 多租户隔离。

## 说明
- 以上两条与既有的 **Hermes** 借鉴(记忆门控/Provider/learn/渐进披露/Curator/
  工具 schema 归一化)互补：Hermes 偏**交互与策展**，OpenOcta 偏**检索与安全**。
- 全部为**原创实现 + 53 项自测**逐条验证；不引入任何第三方依赖(M0 纯 stdlib)。
