"""인용문 원문 대조기 — 지어낸 출처를 기계적으로 걸러낸다.

증거에 URL 과 원문 인용(quotation)이 있으면 그 URL 을 다시 가져와 인용문이 실제로
문서 안에 있는지 확인한다. LLM 의 판단이 아니라 문자열 대조이므로, 출처를 지어내면
여기서 걸린다.

판정
  verified     정규화한 인용문이 문서에 그대로 있음
  partial      인용문의 단어 5-gram 중 상당수(기본 60% 이상)만 문서에 있음 → 사람 확인 필요
  not_found    문서는 열었으나 인용문이 없음 → 자동 반영 금지 (출처 날조 의심)
  fetch_failed 문서를 열지 못함 (네트워크·권한·404 등) → 사람 확인 필요
  no_quote     URL 은 있으나 인용문이 없음
  no_url       URL 이 없음 (오프라인 원전·유료 자료 등)
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import unicodedata
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable

VERIFIED = "verified"
PARTIAL = "partial"
NOT_FOUND = "not_found"
FETCH_FAILED = "fetch_failed"
NO_QUOTE = "no_quote"
NO_URL = "no_url"

STATUS_KO = {VERIFIED: "원문 일치", PARTIAL: "부분 일치", NOT_FOUND: "원문에 없음", FETCH_FAILED: "문서 열기 실패",
             NO_QUOTE: "인용문 없음", NO_URL: "URL 없음"}

MAX_BYTES = 8 * 1024 * 1024
USER_AGENT = "HIGO-verifier/0.1 (intellectual-history ontology; quote verification)"


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    p = _TextExtractor()
    p.feed(raw)
    return html.unescape(" ".join(p.parts))


def normalize(text: str) -> str:
    """대소문자·따옴표·하이픈·공백·구두점 차이를 없앤다 (한글·한자·그리스어 유지)."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"-\s*\n\s*", "", t)  # 줄끝 하이픈 연결
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = t.replace("_", " ")
    return re.sub(r"\s+", " ", t).strip()


def _ngrams(words: list[str], n: int = 5) -> set[tuple[str, ...]]:
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


@dataclass
class FetchResult:
    url: str
    ok: bool
    text: str = ""
    status: int | None = None
    error: str = ""
    retrieved_at: float = field(default_factory=time.time)
    content_hash: str = ""


def http_fetch(url: str, timeout: float = 20.0) -> FetchResult:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (허용된 URL 스킴만 호출)
            raw = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
            ctype = resp.headers.get("Content-Type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            status = resp.status
    except Exception as exc:  # 네트워크 오류는 판정 결과로 기록한다
        return FetchResult(url, False, error=f"{type(exc).__name__}: {exc}")
    body = raw.decode(charset, errors="replace")
    text = html_to_text(body) if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")) else body
    return FetchResult(url, True, text=text, status=status,
                       content_hash="sha256:" + hashlib.sha256(raw).hexdigest())


@dataclass
class Verdict:
    status: str
    score: float = 0.0
    detail: str = ""
    url: str = ""
    retrieved_at: float | None = None
    content_hash: str = ""

    @property
    def label_ko(self) -> str:
        return STATUS_KO.get(self.status, self.status)

    def as_dict(self) -> dict:
        return {"status": self.status, "label_ko": self.label_ko, "score": round(self.score, 3),
                "detail": self.detail, "url": self.url}


class QuoteVerifier:
    """URL 별로 문서를 한 번만 가져오고(주기 내 캐시) 인용문을 대조한다."""

    def __init__(self, fetch: Callable[[str], FetchResult] = http_fetch, partial_threshold: float = 0.6,
                 allowed_schemes: tuple[str, ...] = ("http", "https")):
        self.fetch = fetch
        self.partial_threshold = partial_threshold
        self.allowed_schemes = allowed_schemes
        self._cache: dict[str, FetchResult] = {}

    def get(self, url: str) -> FetchResult:
        if url not in self._cache:
            scheme = url.split(":", 1)[0].lower()
            if scheme not in self.allowed_schemes:
                self._cache[url] = FetchResult(url, False, error=f"scheme not allowed: {scheme}")
            else:
                self._cache[url] = self.fetch(url)
        return self._cache[url]

    def check(self, url: str, quotation: str) -> Verdict:
        if not url:
            return Verdict(NO_URL, detail="URL 이 없어 원문 대조 불가")
        if not (quotation or "").strip():
            return Verdict(NO_QUOTE, url=url, detail="인용문이 없어 원문 대조 불가")
        doc = self.get(url)
        if not doc.ok:
            return Verdict(FETCH_FAILED, url=url, detail=doc.error, retrieved_at=doc.retrieved_at)
        q, t = normalize(quotation), normalize(doc.text)
        base = dict(url=url, retrieved_at=doc.retrieved_at, content_hash=doc.content_hash)
        if q and q in t:
            return Verdict(VERIFIED, score=1.0, detail="정규화한 인용문이 문서에 그대로 있음", **base)
        qg = _ngrams(q.split())
        if not qg:
            return Verdict(NOT_FOUND, detail="인용문이 비어 있음", **base)
        tg = _ngrams(t.split(), n=len(next(iter(qg))))
        score = len(qg & tg) / len(qg)
        if score >= self.partial_threshold:
            return Verdict(PARTIAL, score=score, detail=f"단어 5-gram {score:.0%} 일치 — 번역본·판본 차이일 수 있음", **base)
        return Verdict(NOT_FOUND, score=score, detail=f"문서에 인용문이 없음 (5-gram {score:.0%} 일치)", **base)

    def verify_store(self, store, evidence_ids=None, actor: str = "verifier") -> dict:
        """저장소의 증거를 대조하고 결과를 기록한다. URL 없는 증거는 건너뛴다."""
        counts: dict[str, int] = {}
        results = []
        wanted = set(evidence_ids) if evidence_ids is not None else None
        for ev in store.all_evidence():
            if wanted is not None and ev["id"] not in wanted:
                continue
            if not ev.get("url"):
                continue
            v = self.check(ev["url"], ev.get("quotation", ""))
            store.set_evidence_verification(ev["id"], verification=v.status, retrieved_at=v.retrieved_at,
                                            content_hash=v.content_hash, actor=actor)
            counts[v.status] = counts.get(v.status, 0) + 1
            results.append({"evidence_id": ev["id"], "edge_id": ev["edge_id"], **v.as_dict()})
        return {"counts": counts, "results": results}
