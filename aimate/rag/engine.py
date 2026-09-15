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
    kind: str = "doc"


class Embedder(Protocol):
    """向量化抽象：可指向内网/本地 embedding。"""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class Hit:
    doc_id: str
    score: float
    text: str
    snippet: str = ""
    kind: str = ""


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
                scored.append(Hit(c.doc_id, s, c.text, kind=c.kind))
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
            scored.append(Hit(c.doc_id, s, c.text, kind=c.kind))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:top_k]


def _cos(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _normalize(scores: list[float]) -> list[float]:
    """Min-max 归一化到 [0,1]；全零则返回原值。对应开源实现 normalizeScores。"""
    if not scores:
        return scores
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [0.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def _make_snippet(text: str, query: str, max_len: int = 240) -> str:
    """按查询词在全文首次命中的位置前后截取摘要；无命中则从头截断。

    借鉴开源实现 snippetFrom 的『定位命中词』设计思想，AIMate 自研算法。
    """
    t = text.strip()
    if len(t) <= max_len:
        return t
    q = [w for w in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(w) >= 2]
    lower = t.lower()
    pos = -1
    for w in q:
        i = lower.find(w)
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0 or len(q) == 0:
        return t[:max_len] + "…"
    start = max(0, pos - 20)
    if start + max_len > len(t):
        start = max(0, len(t) - max_len)
    out = t[start:start + max_len]
    if start > 0:
        out = "…" + out
    if start + max_len < len(t):
        out = out + "…"
    return out


class KnowledgeBase:
    """RAG 门面：切分 + 混合检索。

    召回策略（自研，借鉴开源 hybrid 引擎设计思想）：
    - 稀疏(BM25) 与 稠密(余弦) 候选先各自归一化,再按可配权重加权融合
      (text_weight / vec_weight)——比纯 RRF 更能反映真实相关度。
    - 候选放大：先取 limit×k 再截断重排,稳定 top-k。
    - kinds 过滤：可按文档类型(memory/rules/skills/tools)限定检索域。
    - snippet：按查询词智能定位生成摘要。
    RRF 仍保留,可通过 fusion='rrf' 选用。
    """

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        text_weight: float = 0.55,
        vec_weight: float = 0.45,
        fusion: str = "weighted",
    ) -> None:
        self.bm25 = BM25Index()
        self.vector: Optional[VectorIndex] = VectorIndex(embedder) if embedder else None
        self.text_weight = text_weight
        self.vec_weight = vec_weight
        self.fusion = fusion  # 'weighted' | 'rrf'

    @property
    def has_vector(self) -> bool:
        return self.vector is not None

    def index(self, text: str, doc_id: str, chunk_chars: int = 800, kind: str = "doc") -> int:
        chunks = split_document(text, doc_id, chunk_chars)
        for c in chunks:
            c.kind = kind
        self.bm25.add(chunks)
        if self.vector:
            self.vector.add(chunks)
        return len(chunks)

    @staticmethod
    def _filtered(sparse: list[Hit], dense: list[Hit], kinds: set[str] | None) -> tuple[list[Hit], list[Hit]]:
        if not kinds:
            return sparse, dense
        sparse = [h for h in sparse if h.kind in kinds]
        dense = [h for h in dense if h.kind in kinds]
        return sparse, dense

    def search(
        self,
        query: str,
        top_k: int = 5,
        kinds: set[str] | None = None,
        candidate_mult: int = 3,
        rerank: bool = False,
        rerank_lambda: float = 0.7,
    ) -> list[Hit]:
        if not query.strip():
            return []
        cand = top_k * candidate_mult
        sparse = self.bm25.search(query, cand)
        if self.vector:
            dense = self.vector.search(query, cand)
        else:
            dense = []
        sparse, dense = self._filtered(sparse, dense, kinds)

        if self.fusion == "weighted" and self.vector and dense:
            combined: dict[str, float] = {}
            meta: dict[str, Hit] = {}
            smap = {h.doc_id: h for h in sparse}
            dmap = {h.doc_id: h for h in dense}
            s_norm = _normalize([h.score for h in sparse])
            d_norm = _normalize([h.score for h in dense])
            for i, h in enumerate(sparse):
                combined[h.doc_id] = self.text_weight * s_norm[i]
                meta[h.doc_id] = h
            for j, h in enumerate(dense):
                combined[h.doc_id] = combined.get(h.doc_id, 0.0) + self.vec_weight * d_norm[j]
                if h.doc_id not in meta:
                    meta[h.doc_id] = h
            order = sorted(combined, key=combined.get, reverse=True)
            result = [
                self._decorate(meta[oid], query)
                for oid in order[:top_k]
                if oid in meta
            ]
            return self.rerank_mmr(result, query, rerank_lambda, top_k) if rerank else result

        # 默认/降级：RRF 融合
        merged: dict[str, float] = {}
        for rank, h in enumerate(sparse):
            merged[h.doc_id] = merged.get(h.doc_id, 0) + 1 / (60 + rank)
        for rank, h in enumerate(dense):
            merged[h.doc_id] = merged.get(h.doc_id, 0) + 1 / (60 + rank)
        order = sorted(merged, key=merged.get, reverse=True)
        m = {h.doc_id: h for h in [*sparse, *dense]}
        result = [self._decorate(m[oid], query) for oid in order[:top_k] if oid in m]
        return self.rerank_mmr(result, query, rerank_lambda, top_k) if rerank else result

    @staticmethod
    def _decorate(hit: Hit, query: str) -> Hit:
        hit.snippet = _make_snippet(hit.text, query)
        return hit

    # ---- 生产化：MMR 多样重排（缓解同一文档多段落垄断 top-k）----
    @staticmethod
    def rerank_mmr(
        hits: list[Hit],
        query: str,
        lambda_: float = 0.7,
        top_k: int | None = None,
    ) -> list[Hit]:
        """最大边际相关（MMR）重排：综合相关度与多样性。

        MMR = argmax [ λ·sim(query,item) − (1−λ)·max_{已选} sim(item,已选) ]

        - λ 高 → 越看重相关度；λ 低 → 越看重多样性（λ=0.7 常用）
        - 相似度基于查询与候选中英文词的 Jaccard（纯 stdlib，无需向量）
        """
        if not hits:
            return []
        def _jac(a: str, b: str) -> float:
            sa = set(re.findall(r"[a-zA-Z0-9_]+", a.lower()))
            sb = set(re.findall(r"[a-zA-Z0-9_]+", b.lower()))
            if not sa or not sb:
                return 0.0
            return len(sa & sb) / len(sa | sb)
        qtok = " ".join(re.findall(r"[a-zA-Z0-9_]+", query.lower()))
        for h in hits:
            h.score = _jac(qtok, h.text)
        remaining = list(hits)
        chosen: list[Hit] = []
        k = top_k if top_k is not None else len(remaining)
        while remaining and len(chosen) < k:
            best, best_val = None, float("-inf")
            for h in remaining:
                rel = _jac(qtok, h.text)
                div = max((_jac(h.text, g.text) for g in chosen), default=0.0)
                val = lambda_ * rel - (1 - lambda_) * div
                if val > best_val:
                    best, best_val = h, val
            assert best is not None  # remaining 非空必有最优
            chosen.append(best)
            remaining.remove(best)
        return chosen
