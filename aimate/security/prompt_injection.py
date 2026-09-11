"""提示注入检测：写入记忆/技能/上下文的文本先过安全扫描。

借鉴开源 agent（evolution/scan.go）的设计思想：写入持久记忆的内容若含
『覆盖指令』类威胁模式(忽略过往指令/角色劫持/隐藏欺骗/系统提示覆写/绕过
限制)或不可见 Unicode(零宽字符混淆),应被拦截——否则会污染后续每个会话的
系统提示,构成长期后门。

AIMate 自研落地：同一种威胁建模,但中文+英文双语威胁模式、detect() 返回
(structured) 而非仅字符串,便于上层记录审计日志/给出可读原因。不可见字符白
名单纳入 BOM(EFBBBF 常见于文件头)以降低误报。正则与返回契约全部原创。
"""
from __future__ import annotations

import re


# -- 威胁模式：双语。捕获『越权/覆盖/欺骗』的指令,无论中英文表述。--
# 中间修饰词允许任意多个/任意组合(ignore ALL PREVIOUS instructions)。
_THREAT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bignore\b(?:\s+(?:all|previous|prior|above|any|these))+\s+instructions\b", re.I), "prompt_injection"),
    (re.compile(r"(?:忽略|无视|不用理会)(?:所有|上面|之前|此前|先前|全部|任何)*?(?:的)?(?:指令|指示|要求|提示|内容)"), "prompt_injection"),
    (re.compile(r"\byou\s+are\s+now\s+", re.I), "role_hijack"),
    (re.compile(r"(?:从现在开始|接下来的对话中|此后|接下来),?(?:你)?(?:扮演|你是|你就是|当作)(?:一个)?|冒充"), "role_hijack"),
    (re.compile(r"\bdo\s+not\s+tell\s+the\s+user\b", re.I), "deception_hide"),
    (re.compile(r"(?:别|不要|不许)(?:告诉|告知|让)(?:用户|我)"), "deception_hide"),
    (re.compile(r"\bsystem\s+prompt\s+override\b", re.I), "sys_prompt_override"),
    (re.compile(r"\bdisregard\s+(?:your|all|any)\s+(?:instructions|rules|guidelines)\b", re.I), "disregard_rules"),
    (re.compile(r"\bact\s+as\s+(?:if|though)\s+you\s+(?:have\s+no|don.?t\s+have)\s+(?:restrictions|limits|rules)\b", re.I), "bypass_restrictions"),
    (re.compile(r"(?:绕过|无视|打破)(?:你的)?(?:所有)?(?:限制|规则|边界|约束)"), "bypass_restrictions"),
]

# -- 不可见 / 混淆 Unicode（零宽与方向控制符）。--
_INVISIBLE_RUNES: set[int] = {
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0x2060,  # WORD JOINER
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE (排除 BOM 场景,见 is_allowed)
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # LEFT-TO-RIGHT / RIGHT-TO-LEFT overrides
}


def _is_allowed_fe_ff(content: str) -> bool:
    """单个开头 BOM(EFBBBF)合法;剥离后若仍有 FEFF 才视为注入痕迹。"""
    return content.lstrip("\ufeff") != content


def find_invisible_unicode(content: str) -> list[int]:
    """返回文本中不可见/方向控制字符的码点列表(空=干净)。"""
    found: list[int] = []
    for ch in content:
        cp = ord(ch)
        if cp in _INVISIBLE_RUNES:
            if cp == 0xFEFF and ch == content[0] and content.count(ch) == 1:
                continue  # 文件头 BOM,放行
            found.append(cp)
    return found


def find_threat(content: str) -> tuple[str, str] | None:
    """返回 (检测名, 明细)；无威胁返回 None。"""
    for pat, name in _THREAT_PATTERNS:
        m = pat.search(content)
        if m:
            snippet = content[max(0, m.start() - 12): m.end() + 12]
            return name, f"匹配 '{name}' 于: …{snippet}…"
    return None


class InjectionRisk(Exception):
    """检测到提示注入/混淆内容。携带机器可读的 reason 供上层记录审计。"""

    def __init__(self, reason: str, category: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.category = category


def scan(content: str) -> str:
    """安全扫描入口：校验通过返回空串,否则抛出 InjectionRisk(带类别)。"""
    if not content:
        return ""
    inv = find_invisible_unicode(content)
    if inv:
        raise InjectionRisk(f"包含不可见/方向控制 Unicode: {sorted(set(inv))}", "invisible_unicode")
    hit = find_threat(content)
    if hit:
        raise InjectionRisk(hit[1], hit[0])
    return ""
