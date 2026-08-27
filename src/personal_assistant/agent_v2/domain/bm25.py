"""BM25 与倒排索引（专项计划 §9.3 / CT-7）。

纯领域实现，零外部依赖：
- Okapi BM25（k1=1.5, b=0.75）；
- 倒排表：term → {doc_id: tf}，IDF 预计算；
- 分词：小写化 + 非字母数字切分（中文字符按单字切分，保证 CJK 工具名/
  描述可检索）。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_K1 = 1.5
_B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """小写 + 非字母数字切分；CJK 单字成词。"""
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True, slots=True)
class Bm25Doc:
    doc_id: str
    tokens: tuple[str, ...]


@dataclass(slots=True)
class Bm25Index:
    """可增量构建的 BM25 索引（构建后调用 freeze 固定 IDF）。"""

    docs: dict[str, Bm25Doc] = field(default_factory=dict)
    inverted: dict[str, dict[str, int]] = field(default_factory=dict)
    term_df: Counter[str] = field(default_factory=Counter)
    total_len: int = 0
    _frozen: bool = False

    def add(self, doc_id: str, text: str) -> None:
        if self._frozen:
            raise ValueError("索引已冻结")
        if doc_id in self.docs:
            raise ValueError(f"重复文档：{doc_id}")
        tokens = tokenize(text)
        self.docs[doc_id] = Bm25Doc(doc_id=doc_id, tokens=tuple(tokens))
        self.total_len += len(tokens)
        for term, tf in Counter(tokens).items():
            self.inverted.setdefault(term, {})[doc_id] = tf
            self.term_df[term] += 1

    def freeze(self) -> "FrozenBm25":
        n_docs = max(len(self.docs), 1)
        avg_len = max(self.total_len / n_docs, 1.0)
        idf = {
            term: math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            for term, df in self.term_df.items()
        }
        doc_len = {doc_id: len(doc.tokens) for doc_id, doc in self.docs.items()}
        self._frozen = True
        return FrozenBm25(
            docs=dict(self.docs),
            inverted={k: dict(v) for k, v in self.inverted.items()},
            idf=idf,
            doc_len=doc_len,
            avg_len=avg_len,
            n_docs=n_docs,
        )


@dataclass(frozen=True, slots=True)
class FrozenBm25:
    """只读检索视图：score(query_tokens) → [(doc_id, score)] 有序降序。"""

    docs: dict[str, Bm25Doc]
    inverted: dict[str, dict[str, int]]
    idf: dict[str, float]
    doc_len: dict[str, int]
    avg_len: float
    n_docs: int

    def score(self, query_text: str) -> list[tuple[str, float]]:
        query_terms = tokenize(query_text)
        scores: dict[str, float] = {}
        for term in query_terms:
            postings = self.inverted.get(term)
            if not postings:
                continue
            idf = self.idf.get(term, 0.0)
            for doc_id, tf in postings.items():
                dl = self.doc_len.get(doc_id, 0)
                denom = tf + _K1 * (1.0 - _B + _B * (dl / self.avg_len))
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (
                    (tf * (_K1 + 1.0)) / denom
                )
        # 确定性排序：分数降序，同分按 doc_id 字典序。
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
