"""知识库摄取管线（aimate/web/kb_ingest）—— 上传文件 → 自动整理为 md 知识文件 → RAG 索引。

信创红线：纯 stdlib + macOS 自带 textutil（doc/docx/rtf/html/odt→txt），零第三方依赖，
支持断电/无外网私有化部署。图片/音视频等二进制生成带 frontmatter 的引用 md，
文本类（md/txt/json/py/csv…）直接读。产出统一标准 md 知识文件，供 RAG BM25 索引。
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any

# 可直接作为文本读取的扩展名
TEXT_EXTS = {".md", ".markdown", ".txt", ".text", ".log", ".json", ".py", ".js", ".ts",
             ".c", ".h", ".cpp", ".cc", ".java", ".go", ".rs", ".rb", ".php", ".sql",
             ".sh", ".bash", ".yaml", ".yml", ".toml", ".ini", ".conf", ".csv", ".xml",
             ".html", ".htm", ".css", ".svg", ".gitignore", ".jsx", ".tsx", ".vue"}

# textutil 可转 txt 的富文本扩展名
_RICH_EXTS = {".doc", ".docx", ".rtf", ".html", ".htm", ".odt", ".wordml", ".text"}

# 二进制：生成引用 md
_BIN_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".heic",
             ".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".mp3",
             ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".zip", ".tar", ".gz",
             ".7z", ".pdf", ".pptx", ".ppt", ".xlsx", ".xls", ".exe", ".dmg", ".bin",
             ".iso", ".pkg"}

_SAFE_TITLE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff_.-]+")


def detect_kind(ext: str) -> str:
    ext = ext.lower()
    if ext in TEXT_EXTS:
        return "text"
    if ext in _RICH_EXTS:
        return "rich"
    return "binary"


def _run_textutil(path: str, timeout: int = 60) -> str:
    """用 macOS textutil 把富文本转到 txt。失败返回空串。"""
    try:
        r = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", path],
            capture_output=True, timeout=timeout,
        )
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
    except Exception:
        pass
    return ""


def _size_str(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1048576:.1f} MB"


def extract_text(path: str, kind: str | None = None, limit: int = 200_000) -> str:
    """从文件提取纯文本。kind 缺省按扩展名推断。"""
    ext = os.path.splitext(path)[1].lower()
    if kind is None:
        kind = detect_kind(ext)
    if kind == "text":
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(limit)
        except Exception:
            return ""
    if kind == "rich":
        return _run_textutil(path)[:limit]
    return ""  # binary


def to_md_entry(orig_name: str, text: str, src_path: str, doc_id: str,
                extra: dict | None = None) -> str:
    """把提取的文本整理为带 frontmatter 的标准 md 知识文件。

    frontmatter 采用 YAML 风格（title/source/doc_id/ingested/kind/type），
    便于 RAG 切分与按文档聚合；正文保留原始层级（标题→正文），去重空行。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = ["---", f"title: {_SAFE_TITLE.sub('_', orig_name) or orig_name}",
             f"source: {src_path}", f"doc_id: {doc_id}", f"ingested: {now}",
             "kind: knowledge", "type: rag"]
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    title = _SAFE_TITLE.sub(" ", os.path.splitext(orig_name)[0]) or orig_name
    lines.append(f"# {title}")
    lines.append("")
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    if cleaned:
        lines.append(cleaned)
    else:
        lines.append("> 该文件为二进制资源，正文无法直接提取，可在知识库中预览或默认应用打开。")
    lines.append("")
    return "\n".join(lines)


def make_doc_id(orig_name: str, salt: str = "") -> str:
    """由文件名生成稳定 doc_id。"""
    base = os.path.splitext(os.path.basename(orig_name))[0]
    base = _SAFE_TITLE.sub("-", base).strip("-") or "doc"
    if salt:
        base = f"{base}-{salt}"
    return base


def ingest_bytes(body: bytes, filename: str, kb_root: str,
                 uploads_subdir: str = "uploads") -> dict[str, Any]:
    """核心管线：接收上传字节 → 存原始文件 → 提取文本 → 写 md 知识文件。

    返回 {doc_id, md_path, kind, text_preview, size, name}。
    """
    safe = os.path.basename(filename) or "upload.bin"
    # 1) 存原始文件到 knowledge-base/uploads/
    up_dir = os.path.join(kb_root, uploads_subdir)
    os.makedirs(up_dir, exist_ok=True)
    up_path = os.path.join(up_dir, safe)
    n = 1
    while os.path.exists(up_path):
        root, ext = os.path.splitext(safe)
        up_path = os.path.join(up_dir, f"{root}-{n}{ext}")
        n += 1
    with open(up_path, "wb") as f:
        f.write(body)

    # 2) 提取文本
    kind = detect_kind(os.path.splitext(up_path)[1].lower())
    text = extract_text(up_path, kind)

    # 3) 生成 md 知识文件到 knowledge-base/
    doc_id = make_doc_id(os.path.basename(up_path))
    md_name = f"{doc_id}.md"
    md_path = os.path.join(kb_root, md_name)
    n = 1
    while os.path.exists(md_path):
        md_path = os.path.join(kb_root, f"{doc_id}-{n}.md")
        md_name = os.path.basename(md_path)
        n += 1
    rel_up = os.path.relpath(up_path, kb_root)
    md_content = to_md_entry(os.path.basename(up_path), text, rel_up,
                             make_doc_id(os.path.basename(md_name)))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return {"doc_id": os.path.splitext(md_name)[0], "md_path": md_path,
            "md_name": md_name, "kind": kind, "size": len(body),
            "name": os.path.basename(up_path),
            "text_preview": (text or md_content)[:500]}
