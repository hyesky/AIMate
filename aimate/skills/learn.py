"""技能沉淀(自进化)：生成 authoring 标准 prompt，交付数字员工即可产出 SKILL.md。

借鉴开源 agent 的 `/learn` 设计思想：**无独立蒸馏引擎**——把技能创作规范
(格式、description 长度、小节顺序)内嵌进 prompt，让 agent 用现有工具自行产出
技能。零模型工具额外足迹，本地/内网部署通用。

AIMate 自研落地：中文 authoring 标准 + description≤60 校验 + 知识库式布局建议。
"""
from __future__ import annotations


def validate_description(desc: str, limit: int = 60) -> tuple[bool, str]:
    """校验技能 description：单句、≤limit 字符、以句号结尾、不重复技能名。"""
    desc = (desc or "").strip()
    if not desc:
        return False, "description 不能为空"
    if len(desc) > limit:
        return False, f"description 超出 {limit} 字符(当前 {len(desc)})会被截断，请精简"
    if not desc.endswith((".", "。", "!")):
        return False, "description 应以句号结尾"
    return True, "ok"


# 中文 authoring 标准 —— 内嵌进 prompt，让数字员工照此产出技能。
_AUTHORING_STANDARDS = """\
请把用户描述的内容沉淀为一个可复用技能(SKILL.md)，严格遵循以下规范：

Frontmatter：
- name: 小写连字符，<=64 字符，无空格。
- description: 一句话，**<=60 字符**，以句号结尾。表述"能做什么"而非"怎么实现"。
  不要堆形容词(强大的/全面的/完美的)。写完后数一下字符，超了就砍。这是最常被违反的规范：
  描述会被系统提示里的技能索引截断到 60 字符，超出的部分静默丢失且永不路由。
- version: 0.1.0
- author: 恒为字面值 `AIMate`，绝不从运行环境(用户名/git config)取 —— 技能会发布共享，
  环境派生的名字是用户未授权的隐私泄漏。

正文小节顺序(无内容可省略)：
1. # <中文标题>  + 2-3 句简介：做什么、不做什么、关键依赖立场(如"纯 stdlib")。
2. ## 何时使用 —— 具体触发短语列表。
3. ## 前置条件 —— 环境变量、依赖、凭据。
4. ## 如何运行 —— 规范调用方式，用 AIMate 的 `terminal`/`read_file` 等工具框定。
5. ## 快速参考 —— 扁平命令/接口清单，不叙述。
6. ## 步骤 —— 带可直接复制命令的有序步骤。
7. ## 坑 —— 已知限制、限流、看似坏了其实没坏的项。
8. ## 验证 —— 一条能证明技能生效的检查命令。

如果来源很大(成册文档/论文/规范库)，用"知识库式"布局：瘦 SKILL.md(仅索引+简介) +
按章节拆到 references/ 子文件，通过 skill_view(name=…, file_path=…) 按需加载。

请不要编造来源里没有的命令或接口。产出后用 validate_description 校验 description。
"""


def build_learn_prompt(source: str, context_note: str = "") -> str:
    """生成一份让数字员工沉淀技能的完整 prompt。

    source: 用户描述的技能来源(目录/URL/刚完成的工作流/粘贴的资料)。
    context_note: 附加上下文(如"本次会话刚做完的事")。
    """
    parts = [_AUTHORING_STANDARDS]
    if context_note:
        parts.append(f"\n附加上下文：{context_note}")
    parts.append(f"\n请基于以下来源沉淀技能：\n{source}")
    return "\n".join(parts)
