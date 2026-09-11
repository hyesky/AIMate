"""记忆门控：判断一条用户消息是否值得触发记忆召回/写入。

借鉴开源 agent 的设计思想：部分消息『无语义信号』——空输入、斜杠命令、纯
打招呼或纯确认('ok'/'thanks'/'继续'/'done')——唤起记忆是浪费(阻塞一轮网络
往返)且可能把过期上下文污染到一句话回复。

AIMate 自研实现：独立正则门控。仅借鉴『该不该召回』这一判断思想，正则、阈值
全部为原创。中文语境额外覆盖 '好的'/'谢谢'/'嗯'/'继续'/'搞定' 等。
"""
from __future__ import annotations

import re
from typing import Optional

# 锚定到结尾，整条消息只能由这些短语 + 可选空白/标点组成。
# 锚定的交替项只允许后接空白或标点，避免误伤以这些词开头的正常词
# (如 "好的建议是……" 不以纯招呼收尾则不算 trivial)。
_TRIVIAL_RE = re.compile(
    r"^("
    r"yes|no|ok|okay|sure|thanks|thank you|thx|y|n|yep|nope|yeah|nah|"
    r"hi|hey|hello|yo|sup|"
    r"continue|go ahead|do it|proceed|got it|cool|nice|great|done|next|"
    r"好的|好|嗯|嗯嗯|谢谢|多谢|继续|搞定|收到|明白|了解"
    r")"
    r"[\s!?.:;,\"'~。！？：、…\u2018\u2019\u201c\u201d]*$",
    re.IGNORECASE,
)


def is_trivial_prompt(text: Optional[str]) -> bool:
    """True 表示消息无语义信号，可跳过记忆召回/写入，省网络与误污染。

    - None / 空白           → True
    - 斜杠命令 (/learn 等)   → True（命令由命令处理器走，不喂记忆）
    - 纯打招呼 / 确认语      → True
    - 否则                  → False（值得触发记忆）
    """
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("/"):
        return True
    return bool(_TRIVIAL_RE.match(stripped))
