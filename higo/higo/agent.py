"""2단계 — 조사 에이전트 · 독립 검토자 · 비용 상한.

    공백 분석 상위 작업 → (작업마다) 조사 에이전트: Claude + 웹 검색·열람 + HIGO 조회 도구
      → 변경 묶음 제안 → 독립 검토자(반대 입장 검토)가 유지·강등·삭제
      → 1단계 관문(원문 대조 → 위험도 정책 → 등급별 반영) → 주기 보고서 → PR

조사 에이전트는 그래프를 직접 고칠 수 없다. `propose_changes` 도구로 변경을 '제안'할 뿐이며,
그 제안은 changeset.py 의 원문 대조와 위험도 정책을 통과해야 반영된다.

비용: 모든 API 호출의 실제 usage 로 비용을 누적하고, 다음 호출의 예상 비용까지 더해 상한을 넘으면
호출하기 전에 멈춘다 (주기당 기본 5달러).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import gaps as gaps_mod
from . import ontology as O
from .core import HIGO

MODEL = os.environ.get("HIGO_AGENT_MODEL", "claude-opus-5")
PROMPT_VERSION = "researcher-v1/reviewer-v1"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# 100만 토큰당 달러 (입력, 출력, 캐시 읽기 배율)
PRICING = {
    "claude-opus-5": (5.0, 25.0, 0.1),
    "claude-opus-5-5": (4.0, 20.0, 0.05),
    "claude-opus-4-8": (5.0, 25.0, 0.1),
    "claude-sonnet-5": (2.0, 10.0, 0.1),
    "claude-haiku-4-5": (1.0, 5.0, 0.1),
    "claude-fable-5-1": (10.0, 50.0, 0.025),
}
UNKNOWN_MODEL_PRICE = (10.0, 50.0, 0.1)   # 모르는 모델(폴백 등)은 보수적으로 비싸게 계산
CACHE_WRITE_MULT = 1.25
WEB_SEARCH_USD = 10.0 / 1000               # 웹 검색 1회 (web fetch 는 토큰으로만 과금)
MIN_CALL_RESERVE_USD = 0.25                # 다음 호출에 남겨 둘 최소 여유

DEFAULT_SOURCES = {
    "allowed_domains": [
        "plato.stanford.edu", "iep.utm.edu", "philpapers.org", "en.wikisource.org", "www.gutenberg.org",
        "www.perseus.tufts.edu", "archive.org", "www.marxists.org", "oll.libertyfund.org", "www.econlib.org",
        "www.wikidata.org", "en.wikipedia.org", "ko.wikipedia.org",
    ],
    "tier_hints": {
        "1": "원전 전문을 제공하는 사이트(위키소스·구텐베르크·페르세우스·마르크시스트 아카이브·OLL·Econlib)의 원문",
        "4": "스탠퍼드·인터넷 철학 백과사전(SEP·IEP) 항목",
        "5": "위키백과·위키데이터 (단서 찾기용, 사실 확인 보조)",
    },
}

RESEARCHABLE = ["weak_influence", "secondary_only", "pending_review", "quote_missing", "thin_thinker",
                "concept_without_propositions", "work_without_propositions", "domain_coverage", "unverified_evidence"]


class BudgetExceeded(RuntimeError):
    pass


# --------------------------------------------------------------------------- cost
@dataclass
class CostMeter:
    budget_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    last_call_usd: float = 0.0
    by_model: dict = field(default_factory=dict)

    @staticmethod
    def price(model: str) -> tuple[float, float, float]:
        for key, p in PRICING.items():
            if model == key or model.startswith(key + "-"):
                return p
        return UNKNOWN_MODEL_PRICE

    def record(self, response) -> float:
        u = response.usage
        inp = getattr(u, "input_tokens", 0) or 0
        out = getattr(u, "output_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        stu = getattr(u, "server_tool_use", None)
        ws = (getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
        model = getattr(response, "model", MODEL) or MODEL
        pin, pout, rmult = self.price(model)
        cost = (inp * pin + cw * pin * CACHE_WRITE_MULT + cr * pin * rmult + out * pout) / 1e6 + ws * WEB_SEARCH_USD
        self.spent_usd += cost
        self.calls += 1
        self.input_tokens += inp
        self.output_tokens += out
        self.cache_read_tokens += cr
        self.cache_write_tokens += cw
        self.web_searches += ws
        self.last_call_usd = cost
        self.by_model[model] = round(self.by_model.get(model, 0.0) + cost, 4)
        return cost

    def next_call_estimate(self) -> float:
        # 대화가 길어질수록 호출당 비용이 커지므로 직전 호출의 1.5배를 예상치로 쓴다
        return max(MIN_CALL_RESERVE_USD, self.last_call_usd * 1.5)

    def can_afford(self, estimate: float | None = None) -> bool:
        return self.spent_usd + (estimate if estimate is not None else self.next_call_estimate()) <= self.budget_usd

    def summary(self) -> dict:
        return {"budget_usd": self.budget_usd, "spent_usd": round(self.spent_usd, 4), "calls": self.calls,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens, "cache_write_tokens": self.cache_write_tokens,
                "web_searches": self.web_searches, "by_model": self.by_model}


# --------------------------------------------------------------------------- prompts
RESEARCHER_SYSTEM = """You are the research agent of HIGO, an intellectual-history ontology (people, works, concepts, \
propositions, and evidence-backed relations such as influence, criticism and similarity). Each conversation gives you \
one improvement task chosen by a gap analyzer. Research it on the web and propose changes with the propose_changes tool.

How your proposals are judged — plan for this:
- Every evidence item needs `url` and `quotation`. An automatic verifier re-downloads the URL and checks that the \
quotation string appears on that page. Copy the quotation verbatim (a short sentence or phrase, 5-40 words) from text you \
actually fetched with web_fetch. A quotation that is not on the page gets the whole operation rejected as fabricated.
- Prefer primary texts (tier 1) and scholarly encyclopedias (tier 4). Tier: 1 primary source, 2 contemporary testimony, \
3 scholarly monograph/article, 4 academic encyclopedia (SEP, IEP), 5 popular/Wikipedia.
- Influence, succession and criticism are historical-causal claims; similarity is structural and never implies influence. \
Never report a resemblance as influence. Use evidence_status honestly: direct (the person says so), indirect (via an \
intermediary or strongly documented), disputed (scholars disagree), inferred.
- Causal and interpretive claims are only ever stored as hypotheses for human review; facts such as dates and authorship \
can be accepted automatically when verified. Do not inflate.
- Check the existing graph first (search_ontology, get_entity, get_edge) and never duplicate what is there. Reuse existing \
entity ids exactly. For new entities give an explicit id like person:adam-ferguson, work:essay-civil-society, \
concept:spontaneous-order (lowercase ascii, hyphens).
- Write labels and proposition statements in Korean (label_ko, statement), with English originals in label and \
statement_en. A proposition is a faithful paraphrase of a specific passage with its standard locator.
- It is fine to propose nothing if the sources do not support a change; say so briefly. Quality over quantity: a few \
well-supported operations beat many weak ones.

Operation shapes (fields in [] are optional):
  add_entity: {"op":"add_entity","entity":{"id","type","label",["label_ko","start_year","end_year","description"]},"evidence":[...],"rationale"}
  add_edge: {"op":"add_edge","edge":{"source","predicate","target","evidence_status"},"evidence":[...],"rationale"}
  add_proposition: {"op":"add_proposition","proposition":{"id","author","work","statement","statement_en","locator",["year"],"concepts":[...]},"evidence":[...],"rationale"}
  add_evidence: {"op":"add_evidence","edge_id","evidence":[...],"rationale"}
  update_entity: {"op":"update_entity","id","changes":{...},"evidence":[...],"rationale"}
  evidence item: {"tier","url","quotation",["citation","locator","stance":"supports"|"contradicts","interpretation"]}
Entity types: {entity_types}. Predicates: {predicates}.
When you are done, stop; your final message should be one or two sentences summarizing what you proposed."""

REVIEWER_SYSTEM = """You are the independent reviewer for HIGO, an intellectual-history ontology. A research agent proposed \
the operations below. Your job is adversarial: find what is wrong before a human sees it. For each operation decide:
- keep: the quotation plausibly supports exactly this claim, the relation type is right, dates/directions are consistent.
- downgrade: the claim is plausible but overstated (e.g. evidence_status "direct" where the quote only shows resemblance \
or indirect contact; influence asserted where only similarity is shown). Explain what should be weaker.
- drop: the quotation does not support the claim, the relation confuses similarity with influence, the direction or \
chronology is wrong, the entity duplicates an existing one, or it is trivial/noisy.
Be specific in reasons (Korean, one sentence). You cannot see the web pages; judge from the quotation and claim."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object",
        "properties": {"index": {"type": "integer"}, "verdict": {"type": "string", "enum": ["keep", "downgrade", "drop"]},
                       "reason": {"type": "string"}},
        "required": ["index", "verdict", "reason"], "additionalProperties": False}}},
    "required": ["reviews"], "additionalProperties": False,
}

ALLOWED_OPS = {"add_entity", "add_edge", "add_proposition", "add_evidence", "update_entity"}


# --------------------------------------------------------------------------- tools
def client_tools() -> list[dict]:
    return [
        {"name": "search_ontology", "description": "Search the HIGO graph by name or meaning. Returns entity ids.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"},
                                                           "types": {"type": "array", "items": {"type": "string"}}},
                          "required": ["query"]}},
        {"name": "get_entity", "description": "Get an entity with its relations (edge ids, predicate, other end, status, confidence).",
         "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        {"name": "get_edge", "description": "Get one relation with its full evidence bundle (tiers, urls, quotations, verification).",
         "input_schema": {"type": "object", "properties": {"edge_id": {"type": "string"}}, "required": ["edge_id"]}},
        {"name": "propose_changes",
         "description": "Propose ontology changes for human-governed review. Can be called more than once. "
                        "Returns per-operation validation errors you should fix.",
         "input_schema": {"type": "object", "properties": {
             "operations": {"type": "array", "items": {"type": "object"}},
             "notes": {"type": "string"}}, "required": ["operations"]}},
    ]


def server_tools(domains: list[str], max_searches: int, max_fetches: int) -> list[dict]:
    web_search = {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}
    web_fetch = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches,
                 "max_content_tokens": 12000}
    if domains:
        web_search["allowed_domains"] = domains
        web_fetch["allowed_domains"] = domains
    return [web_search, web_fetch]


class ToolBox:
    """조사 에이전트가 쓰는 HIGO 조회·제안 도구 (그래프를 직접 수정하지 않는다)."""

    def __init__(self, higo: HIGO, allowed_domains: list[str] | None = None):
        self.h = higo
        self.allowed_domains = allowed_domains
        self.proposed: list[dict] = []

    def run(self, name: str, args: dict) -> tuple[str, bool]:
        try:
            fn = getattr(self, f"_t_{name}")
        except AttributeError:
            return f"unknown tool {name}", True
        try:
            return json.dumps(fn(**args), ensure_ascii=False, default=str), False
        except (KeyError, TypeError, ValueError) as exc:
            return f"error: {exc}", True

    def _t_search_ontology(self, query: str, types: list[str] | None = None):
        return self.h.search(query, k=8, types=types or None)

    def _t_get_entity(self, id: str):
        d = self.h.reasoner.entity_detail(id)
        ent = d["entity"]
        rels = []
        for group in d["relations"].values():
            for r in group:
                rels.append({"edge_id": r["edge_id"], "predicate": r.get("predicate_ko"), "outgoing": r["outgoing"],
                             "other": r["other"], "other_label": r["other_label"], "status": r["epistemic_status"],
                             "confidence": round(r["confidence"], 2), "evidence": r["evidence_count"]})
        return {"id": ent["id"], "type": ent["type"], "label": ent["label"], "label_ko": ent.get("label_ko"),
                "years": [ent.get("start_year"), ent.get("end_year")], "description": ent.get("description"),
                "statement": (ent.get("props") or {}).get("statement"), "relations": rels[:60]}

    def _t_get_edge(self, edge_id: str):
        e = self.h.store.get_edge(edge_id, with_evidence=True)
        if not e:
            raise KeyError(edge_id)
        keep = ("tier", "stance", "citation", "source_label", "locator", "url", "quotation", "verification")
        return {"id": e["id"], "source": e["source"], "predicate": e["predicate"], "target": e["target"],
                "status": e["epistemic_status"], "evidence_status": e["evidence_status"],
                "confidence": e["confidence"], "evidence": [{k: ev.get(k) for k in keep if ev.get(k)} for ev in e["evidence"]]}

    def _t_propose_changes(self, operations: list[dict], notes: str = ""):
        accepted, errors = 0, []
        new_ids = {p["entity"].get("id") for p in self.proposed if p.get("op") == "add_entity"}
        for i, op in enumerate(operations):
            problems = validate_operation(self.h, op, new_ids, self.allowed_domains)
            if problems:
                errors.append({"index": i, "problems": problems})
                continue
            if op["op"] == "add_entity":
                new_ids.add(op["entity"]["id"])
            self.proposed.append(op)
            accepted += 1
        return {"accepted": accepted, "errors": errors, "total_proposed": len(self.proposed)}


def _domain_allowed(url: str, allowed: list[str] | None) -> bool:
    if not allowed:
        return True
    host = urlparse(url).netloc.lower().split(":")[0]
    bare = lambda d: d[4:] if d.startswith("www.") else d  # noqa: E731
    return any(bare(host) == bare(d) or host.endswith("." + bare(d)) for d in allowed)


def validate_operation(h: HIGO, op: dict, new_ids: set[str], allowed_domains: list[str] | None = None) -> list[str]:
    """제안 형식 검사 — 에이전트가 같은 대화 안에서 고칠 수 있도록 구체적으로 알려 준다."""
    p: list[str] = []
    kind = op.get("op")
    if kind not in ALLOWED_OPS:
        return [f"op must be one of {sorted(ALLOWED_OPS)}"]
    exists = lambda i: bool(i) and (h.store.get_entity(i) is not None or i in new_ids)  # noqa: E731
    evidence = op.get("evidence") or []
    for j, ev in enumerate(evidence):
        if int(ev.get("tier", 0) or 0) not in O.EVIDENCE_TIERS:
            p.append(f"evidence[{j}].tier must be 1-6")
        if not ev.get("url") or not str(ev.get("url")).startswith(("http://", "https://")):
            p.append(f"evidence[{j}].url must be an http(s) URL you fetched")
        elif not _domain_allowed(ev["url"], allowed_domains):
            p.append(f"evidence[{j}].url is not on an allowed source domain")
        if not (ev.get("quotation") or "").strip():
            p.append(f"evidence[{j}].quotation must be copied verbatim from the page")
    if kind == "add_entity":
        e = op.get("entity") or {}
        if e.get("type") not in O.ENTITY_TYPES:
            p.append("entity.type unknown")
        if not e.get("id") or ":" not in e.get("id", ""):
            p.append("entity.id required, e.g. person:adam-ferguson")
        if not e.get("label"):
            p.append("entity.label required")
        if not evidence:
            p.append("at least one evidence item required")
    elif kind == "add_edge":
        e = op.get("edge") or {}
        if e.get("predicate") not in O.RELATION_TYPES:
            p.append(f"edge.predicate unknown: {e.get('predicate')}")
        for k in ("source", "target"):
            if not exists(e.get(k)):
                p.append(f"edge.{k} {e.get(k)!r} does not exist (search_ontology, or add_entity first)")
        if e.get("predicate") in O.RELATION_TYPES and O.RELATION_TYPES[e["predicate"]].requires_evidence and not evidence:
            p.append("this relation requires evidence")
    elif kind == "add_proposition":
        pr = op.get("proposition") or {}
        for k in ("author", "statement"):
            if not pr.get(k):
                p.append(f"proposition.{k} required")
        for k in ("author", "work"):
            if pr.get(k) and not exists(pr[k]):
                p.append(f"proposition.{k} {pr[k]!r} does not exist")
        if not evidence:
            p.append("at least one evidence item required")
    elif kind == "add_evidence":
        if not op.get("edge_id") or not h.store.get_edge(op["edge_id"]):
            p.append("edge_id must be an existing edge id")
        if not evidence:
            p.append("evidence required")
    elif kind == "update_entity":
        if not h.store.get_entity(op.get("id") or ""):
            p.append("id must be an existing entity")
    return p


# --------------------------------------------------------------------------- agent
def _sanitize_for_echo(content: list) -> list:
    """폴백이 출력 도중에 일어났다면, 마지막 fallback 블록 앞의 thinking·tool_use 블록은 되돌려 보내지 않는다."""
    idx = max((i for i, b in enumerate(content) if getattr(b, "type", "") == "fallback"), default=None)
    if idx is None:
        return content
    drop_types = {"thinking", "redacted_thinking", "tool_use"}
    paired = {getattr(b, "tool_use_id", None) for b in content[:idx] if getattr(b, "type", "").endswith("_tool_result")}
    out = []
    for i, b in enumerate(content):
        t = getattr(b, "type", "")
        if i < idx and (t in drop_types or (t == "server_tool_use" and getattr(b, "id", None) not in paired)):
            continue
        out.append(b)
    return out


@dataclass
class TaskLog:
    task: dict
    requests: int = 0
    stop: str = ""
    summary: str = ""
    proposed: int = 0
    kept: int = 0
    downgraded: int = 0
    dropped: int = 0
    cost_usd: float = 0.0
    reviews: list = field(default_factory=list)


class Researcher:
    def __init__(self, higo: HIGO, meter: CostMeter, client=None, model: str = MODEL,
                 sources: dict | None = None, max_requests_per_task: int = 10, max_searches: int = 5,
                 max_fetches: int = 8, effort: str = "medium"):
        if client is None:
            import anthropic  # 선택 의존성: pip install anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.h = higo
        self.meter = meter
        self.model = model
        self.sources = sources or DEFAULT_SOURCES
        self.max_requests = max_requests_per_task
        self.max_searches = max_searches
        self.max_fetches = max_fetches
        self.effort = effort

    def _call(self, **kw):
        if not self.meter.can_afford():
            raise BudgetExceeded(f"다음 호출 예상 비용을 더하면 상한 ${self.meter.budget_usd:.2f} 초과")
        resp = self.client.beta.messages.create(
            model=self.model, max_tokens=16000, betas=[FALLBACK_BETA], fallbacks="default",
            thinking={"type": "adaptive"}, cache_control={"type": "ephemeral"}, **kw)
        self.meter.record(resp)
        return resp

    def research(self, task: dict, log: TaskLog) -> list[dict]:
        box = ToolBox(self.h, self.sources["allowed_domains"])
        system = RESEARCHER_SYSTEM.replace("{entity_types}", ", ".join(O.ENTITY_TYPES)).replace(
            "{predicates}", ", ".join(O.RELATION_TYPES))
        context = {}
        if task.get("target") and self.h.store.get_entity(task["target"]):
            context = box._t_get_entity(task["target"])
        user = (f"Task ({task['label_ko']}): {task['action']}\nDetail: {task.get('detail', '')}\n"
                f"Task data: {json.dumps({k: v for k, v in task.items() if k not in ('label_ko',)}, ensure_ascii=False)}\n"
                f"Allowed source domains: {', '.join(self.sources['allowed_domains'])}\n"
                f"Tier guide: {json.dumps(self.sources.get('tier_hints', {}), ensure_ascii=False)}\n"
                f"Current graph context for the target:\n{json.dumps(context, ensure_ascii=False)[:12000]}")
        messages = [{"role": "user", "content": user}]
        tools = client_tools() + server_tools(self.sources["allowed_domains"], self.max_searches, self.max_fetches)
        start = self.meter.spent_usd
        try:
            while log.requests < self.max_requests:
                resp = self._call(system=system, tools=tools, messages=messages,
                                  output_config={"effort": self.effort})
                log.requests += 1
                log.stop = resp.stop_reason
                if resp.stop_reason == "refusal":
                    log.summary = "모델이 요청을 거절함"
                    break
                messages.append({"role": "assistant", "content": _sanitize_for_echo(list(resp.content))})
                if resp.stop_reason == "pause_turn":
                    continue  # 서버 도구 반복 한도 — 그대로 다시 보내면 이어서 진행
                calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
                if resp.stop_reason != "tool_use" or not calls:
                    log.summary = " ".join(getattr(b, "text", "") for b in resp.content
                                           if getattr(b, "type", "") == "text").strip()[:400]
                    break
                results = []
                for c in calls:
                    out, is_err = box.run(c.name, dict(c.input or {}))
                    results.append({"type": "tool_result", "tool_use_id": c.id, "content": out, "is_error": is_err})
                messages.append({"role": "user", "content": results})
            else:
                log.stop = "max_requests"
        except BudgetExceeded as exc:
            log.stop = "budget"
            log.summary = str(exc)
        log.cost_usd = round(self.meter.spent_usd - start, 4)
        log.proposed = len(box.proposed)
        return box.proposed

    def review(self, task: dict, ops: list[dict], log: TaskLog) -> list[dict]:
        """독립 검토자: 별도 대화에서 반대 입장으로 제안을 검토한다."""
        if not ops:
            return []
        start = self.meter.spent_usd
        listing = [{"index": i, "op": op} for i, op in enumerate(ops)]
        try:
            resp = self._call(system=REVIEWER_SYSTEM,
                              messages=[{"role": "user", "content":
                                         f"Task: {task['action']}\nProposed operations:\n"
                                         f"{json.dumps(listing, ensure_ascii=False)[:60000]}"}],
                              output_config={"effort": self.effort,
                                             "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}})
        except BudgetExceeded:
            log.reviews.append({"note": "예산 부족으로 독립 검토를 건너뜀 — 제안은 모두 강등 처리"})
            return [_downgrade(op, "독립 검토 없음(예산 부족)") for op in ops]
        log.cost_usd = round(log.cost_usd + self.meter.spent_usd - start, 4)
        if resp.stop_reason == "refusal":
            return [_downgrade(op, "독립 검토 거절됨") for op in ops]
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "{}")
        try:
            verdicts = {r["index"]: r for r in json.loads(text).get("reviews", [])}
        except json.JSONDecodeError:
            verdicts = {}
        out = []
        for i, op in enumerate(ops):
            v = verdicts.get(i, {"verdict": "downgrade", "reason": "검토 결과 누락"})
            log.reviews.append({"index": i, **v})
            if v["verdict"] == "drop":
                log.dropped += 1
                continue
            if v["verdict"] == "downgrade":
                log.downgraded += 1
                out.append(_downgrade(op, v["reason"]))
            else:
                log.kept += 1
                out.append({**op, "review_note": f"독립 검토 유지: {v['reason']}"})
        return out


def _downgrade(op: dict, reason: str) -> dict:
    op = json.loads(json.dumps(op))
    if op.get("op") == "add_edge":
        pred = op["edge"].get("predicate")
        if pred in O.RELATION_TYPES and O.RELATION_TYPES[pred].category in O.CAUSAL_CATEGORIES:
            op["edge"]["evidence_status"] = "inferred"
        op["edge"]["note"] = f"독립 검토 강등: {reason}"
    op["review_note"] = f"독립 검토 강등: {reason}"
    op["rationale"] = (op.get("rationale", "") + f" [검토자: {reason}]").strip()
    op["force_review"] = True
    return op


def load_sources(data_dir) -> dict:
    p = Path(data_dir) / "sources.json" if data_dir else None
    if p and p.is_file():
        return {**DEFAULT_SOURCES, **json.loads(p.read_text(encoding="utf-8"))}
    return DEFAULT_SOURCES


def select_tasks(higo: HIGO, data_dir, max_tasks: int) -> list[dict]:
    """공백 분석 결과에서 조사 가능한 작업을 고르되, 같은 유형이 몰리지 않게 섞는다."""
    res = gaps_mod.analyze(higo.store, gaps_mod.load_roadmap(data_dir), limit=200)
    pool = [t for t in res["tasks"] if t["type"] in RESEARCHABLE]
    picked, per_type = [], {}
    for t in pool:
        if per_type.get(t["type"], 0) >= max(1, max_tasks // 3):
            continue
        picked.append(t)
        per_type[t["type"]] = per_type.get(t["type"], 0) + 1
        if len(picked) >= max_tasks:
            break
    return picked


def research_changeset(data_dir, budget_usd: float = 5.0, max_tasks: int = 8, client=None,
                       model: str = MODEL, review: bool = True) -> dict:
    """조사 → 독립 검토 → 변경 묶음. 반영은 하지 않는다 (cycle.run_cycle 이 관문 역할)."""
    h = HIGO(":memory:", data_dir=data_dir)
    h.seed()
    meter = CostMeter(budget_usd)
    agent = Researcher(h, meter, client=client, model=model, sources=load_sources(data_dir))
    tasks = select_tasks(h, data_dir, max_tasks)
    ops: list[dict] = []
    logs: list[TaskLog] = []
    for t in tasks:
        if not meter.can_afford():
            logs.append(TaskLog(t, stop="budget", summary="예산 소진으로 시작하지 않음"))
            continue
        log = TaskLog(t)
        proposed = agent.research(t, log)
        ops += agent.review(t, proposed, log) if review else proposed
        logs.append(log)
    return {
        "agent": {"model": model, "prompt_version": PROMPT_VERSION, "cost": meter.summary(),
                  "tasks": [{"type": lg.task["type"], "label_ko": lg.task["label_ko"],
                             "target": lg.task.get("target_label") or lg.task.get("target"),
                             "action": lg.task["action"], "requests": lg.requests, "stop": lg.stop,
                             "summary": lg.summary, "proposed": lg.proposed, "kept": lg.kept,
                             "downgraded": lg.downgraded, "dropped": lg.dropped, "cost_usd": lg.cost_usd,
                             "reviews": lg.reviews} for lg in logs],
                  "finished_at": time.time()},
        "operations": ops,
    }
