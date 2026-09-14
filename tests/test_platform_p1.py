"""P1 RAG 知识库摄取管线测试：上传 → 自动转 md → 索引入 RAG。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimate.web import kb_ingest  # noqa: E402

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAIL: {name}"
    PASS += 1
    print(f"  ✔ {name}")


def main():
    print("P1 RAG 知识库摄取管线")
    d = tempfile.mkdtemp(prefix="kb_rag_")

    # 1) md 文本上传
    r1 = kb_ingest.ingest_bytes(
        "# 内网部署\n\nAIMate 支持私有化部署。\n".encode(), "deploy notes.md", d)
    check("md 文本 → doc_id 规范化", r1["doc_id"] == "deploy-notes")
    check("md 文本 kind=text", r1["kind"] == "text")
    check("生成 md 文件", os.path.exists(r1["md_path"]))
    md1 = open(r1["md_path"], encoding="utf-8").read()
    check("md frontmatter 含 title", "title:" in md1)
    check("md 正文保留原文", "私有化部署" in md1)
    check("kind: knowledge", "kind: knowledge" in md1 and "type: rag" in md1)

    # 2) 二进制 → 引用 md
    r3 = kb_ingest.ingest_bytes(b"\x89PNG\r\n\x1a\nfake", "logo.png", d)
    check("二进制 kind=binary", r3["kind"] == "binary")
    check("二进制也生成 md", os.path.exists(r3["md_path"]))

    # 3) doc_id 稳定 & 冲突去重
    r4 = kb_ingest.ingest_bytes(b"a", "x.md", d)
    r5 = kb_ingest.ingest_bytes(b"b", "x.md", d)
    check("同名二次上传 doc_id 去重", r4["doc_id"] != r5["doc_id"])
    check("原始文件存入 uploads/", os.path.exists(
        os.path.join(d, "uploads", os.path.basename(r4["name"]))))

    # 4) textutil 富文本提取（html 走 text，rtf 走 textutil）
    rtf = os.path.join(d, "a.rtf")
    open(rtf, "w", encoding="utf-8").write(r"{\rtf1 AIMate Platform Test}")
    rr = kb_ingest.ingest_bytes(open(rtf, "rb").read(), "a.rtf", d)
    md = open(rr["md_path"], encoding="utf-8").read()
    check("rtf 提取含 textutil 文本", "AIMate" in md)

    # 5) 索引入 RAG：复用 KnowledgeBase
    from aimate.rag.engine import KnowledgeBase
    kb = KnowledgeBase()
    n = kb.index(open(r1["md_path"], encoding="utf-8").read(), doc_id="deploy-notes", kind="doc")
    hits = kb.search("私有化部署", top_k=3)
    check("RAG BM25 召回上传 md", hits and hits[0].doc_id == "deploy-notes")

    print(f"\nALL PASS ✔ ({PASS} checks)")


if __name__ == "__main__":
    main()
