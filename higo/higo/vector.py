"""의미 유사성 검색을 위한 경량 벡터 인덱스.

기본 구현은 외부 의존성이 없는 TF-IDF(단어 + 한글 문자 bigram) 코사인 유사도다.
Embedder 인터페이스를 교체하면 Qdrant·Weaviate·Milvus 같은 Vector DB 와 실제
임베딩 모델로 바꿀 수 있다 (VectorIndex.add / search 시그니처 유지).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Protocol

_WORD = re.compile(r"[A-Za-z][A-Za-z\-']+|[0-9]+|[가-힣]+|[一-鿿]+")
_HANGUL = re.compile(r"^[가-힣]+$")

# 조사·어미·기능어 — 한국어/영어 텍스트에서 변별력이 낮은 토큰
STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "be", "that", "this", "it", "as", "by",
    "for", "on", "with", "from", "not", "but", "its", "his", "her", "their", "which", "what", "who", "all",
    "는", "은", "이", "가", "을", "를", "의", "에", "와", "과", "도", "로", "으로", "에서", "한다", "하다",
    "있다", "없다", "것", "수", "그", "이다", "된다", "및", "또는", "대한", "위한",
}
_JOSA = ("에서는", "으로는", "에게서", "이라는", "라는", "으로", "에서", "에게", "까지", "부터", "보다",
         "처럼", "이며", "이고", "하는", "한다", "된다", "적인", "적", "은", "는", "이", "가", "을", "를",
         "의", "에", "와", "과", "도", "로", "며")


def _strip_josa(word: str) -> str:
    for j in _JOSA:
        if len(word) > len(j) + 1 and word.endswith(j):
            return word[: -len(j)]
    return word


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for m in _WORD.finditer(text or ""):
        w = m.group(0).lower()
        if _HANGUL.match(w):
            w = _strip_josa(w)
            if w in STOPWORDS:
                continue
            toks.append(w)
            if len(w) >= 2:
                toks += [f"#{w[i:i + 2]}" for i in range(len(w) - 1)]
        else:
            if w in STOPWORDS or len(w) < 2:
                continue
            toks.append(w.rstrip("s") if len(w) > 4 else w)
    return toks


class Embedder(Protocol):
    def fit(self, docs: list[str]) -> None: ...
    def embed(self, text: str) -> dict[str, float]: ...


class TfidfEmbedder:
    def __init__(self) -> None:
        self.idf: dict[str, float] = {}
        self.n = 0

    def fit(self, docs: list[str]) -> None:
        self.n = len(docs)
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(tokenize(d)))
        self.idf = {t: math.log((1 + self.n) / (1 + c)) + 1.0 for t, c in df.items()}

    def embed(self, text: str) -> dict[str, float]:
        tf = Counter(tokenize(text))
        vec = {t: (1 + math.log(c)) * self.idf.get(t, math.log(1 + self.n) + 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


class VectorIndex:
    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or TfidfEmbedder()
        self.texts: dict[str, str] = {}
        self.meta: dict[str, dict] = {}
        self.vecs: dict[str, dict[str, float]] = {}

    def build(self, items: Iterable[tuple[str, str, dict]]) -> "VectorIndex":
        items = list(items)
        self.texts = {i: t for i, t, _ in items}
        self.meta = {i: m for i, _, m in items}
        self.embedder.fit(list(self.texts.values()))
        self.vecs = {i: self.embedder.embed(t) for i, t in self.texts.items()}
        return self

    def search(self, query: str, k: int = 10, *, types: Iterable[str] | None = None,
               min_score: float = 0.0, exclude: Iterable[str] = ()) -> list[tuple[str, float]]:
        q = self.embedder.embed(query)
        return self.search_vec(q, k, types=types, min_score=min_score, exclude=exclude)

    def search_vec(self, q: dict[str, float], k: int = 10, *, types=None, min_score: float = 0.0,
                   exclude: Iterable[str] = ()) -> list[tuple[str, float]]:
        ts = set(types) if types else None
        ex = set(exclude)
        scored = []
        for i, v in self.vecs.items():
            if i in ex or (ts and self.meta[i].get("type") not in ts):
                continue
            s = cosine(q, v)
            if s > min_score:
                scored.append((i, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def similar(self, item_id: str, k: int = 10, **kw) -> list[tuple[str, float]]:
        if item_id not in self.vecs:
            return []
        return self.search_vec(self.vecs[item_id], k, exclude=[item_id, *kw.pop("exclude", [])], **kw)


def entity_text(entity: dict) -> str:
    props = entity.get("props") or {}
    parts = [entity.get("label", ""), entity.get("label_ko") or "", " ".join(entity.get("aliases") or []),
             entity.get("description") or "", props.get("statement", ""), props.get("statement_en", ""),
             props.get("definition", ""), props.get("interpretation", "")]
    return " ".join(p for p in parts if p)
