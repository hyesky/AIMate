"""知识库 RAG：文档切分 → 向量化 → 召回。

设计（自研，本地化可部署）：
- 切分：按段落/固定窗口，保留元数据。
- 向量化：可插拔 Embedder 接口，默认对接内网推理网关的 OpenAI 兼容 embedding，
  也支持本机路径/国产向量模型。
- 召回：BM25 稀疏 + 稠密向量混合检索（hybrid），可切换国产向量库后端。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass
class Chunk:
    doc_id: str
    text: str
    meta: dict = field(default_factory=dict)


class Embedder(Protocol):
    """向量化抽象：可指向内网/本地 embedding。"""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class Hit:
    doc_id: str
    score: float
    text: str


def split_document(text: str, doc_id: str, chunk_chars: int = 800, overlap: int = 100) -> list[Chunk]:
    """按段落 + 滑窗切分。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buf, buf_len = "", 0
    idx = 0
    for p in paras:
        if buf_len + len(p) > chunk_chars and buf:
            chunks.append(Chunk(doc_id, buf, {"order": idx}))
            idx += 1
            buf = buf[-overlap:] + "\n" + p
            buf_len = len(buf)
        else:
            buf = (buf + "\n" + p) if buf else p
            buf_len = len(buf)
    if buf:
        chunks.append(Chunk(doc_id, buf, {"order": idx}))
    return chunks


class BM25Index:
    """稀疏检索（无外部依赖、纯自研实现）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs: list[Chunk] = []
        self.df: dict[str, int] = {}
        self.avgdl = 0.0

    def add(self, chunks: List[Chunk]) -> None:
        self.docs.extend(chunks)
        for c in chunks:
            for tok in set(_tokenize(c.text)):
                self.df[tok] = self.df.get(tok, 0) + 1
        self.avgdl = sum(len(_tokenize(c.text)) for c in self.docs) / max(len(self.docs), 1)

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        n = len(self.docs)
        q_tokens = set(_tokenize(query))
        scored: list[Hit] = []
        for i, c in enumerate(self.docs):
            dl = len(_tokenize(c.text))
            s = 0.0
            for t in q_tokens:
                tf = _tokenize(c.text).count(t)
                if tf == 0:
                    continue
                idf = ((n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5) + 1.0)
                s += idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1e-9))
                )
            if s > 0:
                scored.append(Hit(c.doc_id, s, c.text))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


def _tokenize(text: str) -> list[str]:
    # 中文按字bigram + 英文按词，简易实现；生产可换 jieba/国产分词
    tokens: list[str] = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    return tokens + [a + b for a, b in zip(cjk, cjk[1:])]


class VectorIndex:
    """稠密向量索引（内存 + 余弦相似）。生产可换国产向量库（Milvus/Faiss 化国产）。"""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vectors: list[list[float]] = []

    def add(self, chunks: List[Chunk]) -> None:
        vecs = self.embedder.embed([c.text for c in chunks])
        self.chunks.extend(chunks)
        self.vectors.extend(vecs)

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        qv = self.embedder.embed([query])[0]
        scored: list[Hit] = []
        for c, v in zip(self.chunks, self.vectors):
            s = _cos(qv, v)
            scored.append(Hit(c.doc_id, s, c.text))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


def _cos(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class KnowledgeBase:
    """RAG 门面：切分 + 混合检索。"""

    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self.bm25 = BM25Index()
        self.vector: Optional[VectorIndex] = VectorIndex(embedder) if embedder else None

    @property
    def has_vector(self) -> bool:
        return self.vector is not None

    def index(self, text: str, doc_id: str, chunk_chars: int = 800) -> int:
        chunks = split_document(text, doc_id, chunk_chars)
        self.bm25.add(chunks)
        if self.vector:
            self.vector.add(chunks)
        return len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        sparse = self.bm25.search(query, top_k * 2)
        if not self.vector:
            return sparse[:top_k]
        dense = self.vector.search(query, top_k)
        # 简单 RRF 融合
        combined: dict[str, float] = {}
        for rank, h in enumerate(sparse):
            combined[h.doc_id] = combined.get(h.doc_id, 0) + 1 / (60 + rank)
        for rank, h in enumerate(dense):
            combined[h.doc_id] = combined.get(h.doc_id, 0) + 1 / (60 + rank)
        order = sorted(combined, key=combined.get, reverse=True)
        m = {h.doc_id: h for h in [*sparse, *dense]}
        return [m[oid] for oid in order[:top_k] if oid in m]
