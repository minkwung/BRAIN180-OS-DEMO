"""Document Pipeline + AI Extraction.

원전 텍스트 → 문장 분할 → 엔티티 링크(가제티어) → 명제·관계 후보 추출 → 후보 큐.

추출 결과는 곧바로 그래프에 들어가지 않는다. 모두 `candidates` 테이블에 쌓이고,
사람이 승인해야 엔티티/명제/관계로 반영된다. 관계 후보는 승인되더라도 우선
'hypothesis' 상태로 들어가 증거가 붙어야 'accepted' 로 올라갈 수 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .graph import GraphIndex
from .llm import LLMClient, LLMUnavailable
from .store import Store

_SENT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s*|\n{2,}")

# 관계 단서어 → predicate (영/한)
RELATION_CUES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"influenc|영향을 (주|받)|영향 아래|inspired|영감을"), "influenced"),
    (re.compile(r"criticiz|critique|비판|반대하"), "criticized"),
    (re.compile(r"refut|논박|반박"), "refuted"),
    (re.compile(r"reject|거부|배척"), "rejected"),
    (re.compile(r"student of|studied under|제자|사사|스승"), "student_of"),
    (re.compile(r"extend|develop(ed)? further|확장|발전시"), "extended"),
    (re.compile(r"adopt|borrow|받아들|수용|계승"), "adopted"),
    (re.compile(r"reinterpret|재해석"), "reinterpreted"),
    (re.compile(r"respond|repl(y|ied) to|응답|답하"), "responds_to"),
    (re.compile(r"similar|resembl|parallel|유사|닮|비슷"), "similar_to"),
]
# 주장 문장의 단서
CLAIM_CUES = re.compile(
    r"\b(is|are|must|cannot|consists|only|all|every|never|argue|hold|claim|maintain)\b|"
    r"이다|한다|없다|있다|해야|아니다|주장|본다|라고")


@dataclass
class Mention:
    entity_id: str
    type: str
    text: str
    start: int


class Extractor:
    def __init__(self, store: Store, graph: GraphIndex, llm: LLMClient | None = None):
        self.store = store
        self.g = graph
        self.llm = llm
        self._gazetteer: list[tuple[str, str, str]] | None = None
        self._gaz_rev = -1

    # --------------------------------------------------------- gazetteer
    def gazetteer(self) -> list[tuple[str, str, str]]:
        g = self.g.refresh()
        if self._gazetteer is None or self._gaz_rev != self.store.revision:
            names = []
            for n in g.nodes.values():
                if n["type"] in ("Era", "Source", "Proposition", "Interpretation", "Argument"):
                    continue
                for name in {n["label"], n.get("label_ko") or "", *(n.get("aliases") or [])}:
                    if name and len(name) >= 2:
                        names.append((name.lower(), n["id"], n["type"]))
            names.sort(key=lambda x: -len(x[0]))  # 긴 이름 우선 매칭
            self._gazetteer = names
            self._gaz_rev = self.store.revision
        return self._gazetteer

    def link_entities(self, sentence: str) -> list[Mention]:
        low = sentence.lower()
        taken: list[tuple[int, int]] = []
        out: list[Mention] = []
        seen = set()
        for name, eid, typ in self.gazetteer():
            start = 0
            while True:
                i = low.find(name, start)
                if i < 0:
                    break
                j = i + len(name)
                # 영문은 단어 경계 확인
                if name.isascii() and ((i > 0 and low[i - 1].isalnum()) or (j < len(low) and low[j].isalnum())):
                    start = j
                    continue
                if not any(a < j and i < b for a, b in taken):
                    taken.append((i, j))
                    if eid not in seen:
                        out.append(Mention(eid, typ, sentence[i:j], i))
                        seen.add(eid)
                start = j
        out.sort(key=lambda m: m.start)
        return out

    @staticmethod
    def sentences(text: str) -> list[str]:
        parts = [s.strip() for s in _SENT.split(text or "") if s and s.strip()]
        return [p for p in parts if len(p) > 8]

    # ------------------------------------------------------ rule-based
    def extract_rules(self, text: str, author_id: str | None = None, work_id: str | None = None) -> list[dict]:
        cands: list[dict] = []
        for sent in self.sentences(text):
            mentions = self.link_entities(sent)
            persons = [m for m in mentions if m.type == "Person"]
            concepts = [m for m in mentions if m.type == "Concept"]
            # 1) 관계 후보: 두 인물 + 단서어
            low = sent.lower()
            for pat, pred in RELATION_CUES:
                if not pat.search(low):
                    continue
                if len(persons) >= 2:
                    src, tgt = persons[0].entity_id, persons[1].entity_id
                    # "B는 A의 영향을 받았다" 류의 수동 표현 → 방향 뒤집기
                    passive = re.search(r"influenced by|영향을 받|영향 아래|제자", low)
                    if pred == "influenced" and passive:
                        src, tgt = tgt, src
                    if pred == "student_of" and not passive and "제자" not in low:
                        src, tgt = tgt, src
                    # 능동 표현("B는 A를 비판했다")은 먼저 나온 인물을 행위자로 본다
                    cands.append({"kind": "edge", "score": 0.5, "payload": {
                        "source": src, "predicate": pred, "target": tgt, "sentence": sent,
                        "method": "rule:cue+2persons"}})
                elif len(persons) == 1 and concepts and pred in ("adopted", "criticized", "rejected", "extended",
                                                                 "reinterpreted"):
                    cands.append({"kind": "edge", "score": 0.4, "payload": {
                        "source": persons[0].entity_id, "predicate": pred, "target": concepts[0].entity_id,
                        "sentence": sent, "method": "rule:cue+person+concept"}})
                break
            # 2) 명제 후보: 저자가 있는 문서에서 개념을 포함한 주장 문장
            if concepts and CLAIM_CUES.search(low) and (author_id or persons):
                cands.append({"kind": "proposition", "score": 0.3 + 0.1 * min(len(concepts), 3), "payload": {
                    "statement": sent, "author": author_id or persons[0].entity_id, "work": work_id,
                    "concepts": [m.entity_id for m in concepts], "method": "rule:claim+concept"}})
            # 3) 미등록 개념 후보: 따옴표/『』로 강조된 용어
            for term in re.findall(r"[‘'\"“「『]([^’'\"”」』]{2,30})[’'\"”」』]", sent):
                if not any(term.lower() == n for n, _, _ in self.gazetteer()):
                    cands.append({"kind": "entity", "score": 0.2, "payload": {
                        "type": "Concept", "label": term, "sentence": sent, "method": "rule:quoted-term"}})
        return cands

    # ------------------------------------------------------------ LLM
    LLM_SYSTEM = (
        "You are an extraction engine for an intellectual-history ontology (HIGO). From the given primary "
        "or secondary text, extract only what the text itself supports. Distinguish influence (a historical, "
        "causal claim) from similarity (a structural resemblance, non-causal) — never report a similarity "
        "as influence. Use the provided known entity ids whenever an entity matches; otherwise propose a new "
        "entity with a type from: Person, Work, Concept, School, Event. Allowed predicates: influenced, "
        "student_of, responds_to, adopted, extended, modified, reinterpreted, criticized, rejected, refuted, "
        "challenged, similar_to, analogous_to, contrasts_with, opposed_to, depends_on, presupposes. "
        "JSON schema: {\"entities\":[{\"id\"?,\"type\",\"label\",\"label_ko\"?,\"description\"}],"
        "\"propositions\":[{\"statement\",\"author\",\"work\"?,\"concepts\":[ids or labels],\"locator\"?}],"
        "\"relations\":[{\"source\",\"predicate\",\"target\",\"evidence_quote\",\"evidence_status\":"
        "\"direct|indirect|disputed|inferred\"}]}. Quotes must be verbatim spans from the text."
    )

    def extract_llm(self, text: str, author_id: str | None, work_id: str | None) -> list[dict]:
        if not self.llm or not self.llm.available:
            raise LLMUnavailable("LLM not configured")
        known = [f"{eid} = {name}" for name, eid, t in self.gazetteer() if t in ("Person", "Concept", "Work")][:400]
        user = ("Known entities (id = name):\n" + "\n".join(known) +
                f"\n\nDocument author id: {author_id or 'unknown'}; work id: {work_id or 'unknown'}\n\n"
                f"TEXT:\n{text}")
        data = self.llm.complete_json(self.LLM_SYSTEM, user)
        cands = []
        for e in data.get("entities", []):
            if e.get("id") and e["id"] in self.g.nodes:
                continue
            cands.append({"kind": "entity", "score": 0.5, "payload": {**e, "method": "llm"}})
        for p in data.get("propositions", []):
            cands.append({"kind": "proposition", "score": 0.6, "payload": {
                "statement": p.get("statement", ""), "author": p.get("author") or author_id,
                "work": p.get("work") or work_id, "concepts": p.get("concepts", []),
                "locator": p.get("locator", ""), "method": "llm"}})
        for r in data.get("relations", []):
            cands.append({"kind": "edge", "score": 0.6, "payload": {
                "source": r.get("source"), "predicate": r.get("predicate"), "target": r.get("target"),
                "sentence": r.get("evidence_quote", ""), "evidence_status": r.get("evidence_status", "inferred"),
                "method": "llm"}})
        return cands

    # ---------------------------------------------------------- pipeline
    def ingest(self, title: str, text: str, author_id: str | None = None, work_id: str | None = None,
               use_llm: bool = False) -> dict:
        doc = self.store.add_document(title, text, author_id, work_id)
        cands = self.extract_rules(text, author_id, work_id)
        method = "rules"
        llm_error = None
        if use_llm:
            try:
                cands += self.extract_llm(text, author_id, work_id)
                method = "rules+llm"
            except (LLMUnavailable, ValueError) as exc:
                llm_error = str(exc)
        saved = []
        dedup = set()
        for c in cands:
            p = c["payload"]
            key = (c["kind"], p.get("source"), p.get("predicate"), p.get("target"), p.get("statement"), p.get("label"))
            if key in dedup:
                continue
            dedup.add(key)
            origin = "ai" if p.get("method") == "llm" else "extraction"
            saved.append(self.store.add_candidate(c["kind"], p, origin=origin, document_id=doc["id"],
                                                  score=c["score"]))
        return {"document": doc, "method": method, "llm_error": llm_error, "candidates": saved,
                "sentences": len(self.sentences(text))}

    # ---------------------------------------------------------- review
    def approve_candidate(self, cid: str, actor: str, overrides: dict | None = None) -> dict:
        cand = self.store.get_candidate(cid)
        if not cand or cand["status"] != "pending":
            raise ValueError("candidate not pending")
        p = {**cand["payload"], **(overrides or {})}
        doc_id = cand["document_id"]
        origin = "ai" if cand["origin"] == "ai" else "extraction"
        result: dict = {}
        if cand["kind"] == "entity":
            from .ids import make_id
            eid = p.get("id") or make_id(p.get("type", "Concept"), p["label"])
            result = self.store.upsert_entity(eid, p.get("type", "Concept"), p["label"],
                                              label_ko=p.get("label_ko"), description=p.get("description", ""),
                                              origin=origin, actor=actor)
        elif cand["kind"] == "proposition":
            from .ids import make_id
            pid = make_id("Proposition", p["statement"][:60])
            year = self.g.year(p["work"]) if p.get("work") else None
            result = self.store.upsert_entity(
                pid, "Proposition", p["statement"][:80], description="",
                props={"statement": p["statement"], "locator": p.get("locator", ""), "year": year,
                       "document": doc_id}, origin=origin, actor=actor)
            if p.get("author") and self.store.get_entity(p["author"]):
                self.store.add_edge(p["author"], "proposes", pid, origin=origin, epistemic_status="proposed",
                                    actor=actor)
            if p.get("work") and self.store.get_entity(p["work"]):
                self.store.add_edge(p["work"], "contains", pid, origin=origin, epistemic_status="proposed",
                                    actor=actor)
            for c in p.get("concepts", []):
                if self.store.get_entity(c):
                    self.store.add_edge(pid, "about", c, origin=origin, epistemic_status="proposed", actor=actor)
        elif cand["kind"] == "edge":
            for k in ("source", "target"):
                if not self.store.get_entity(p.get(k) or ""):
                    raise ValueError(f"{k} entity not found: {p.get(k)}")
            edge = self.store.add_edge(p["source"], p["predicate"], p["target"], origin=origin,
                                       evidence_status=p.get("evidence_status", "inferred"),
                                       epistemic_status="hypothesis", note=f"extracted from {doc_id}",
                                       actor=actor)
            if p.get("sentence"):
                doc = next((d for d in self.store.list_documents() if d["id"] == doc_id), None)
                self.store.add_evidence(edge["id"], tier=6 if origin == "ai" else 5,
                                        citation=f"document {doc_id}: {doc['title'] if doc else ''}",
                                        quotation=p["sentence"], added_by=actor,
                                        interpretation=f"extraction method: {p.get('method')}")
            result = self.store.get_edge(edge["id"], with_evidence=True)
        self.store.set_candidate_status(cid, "approved", actor)
        return {"candidate": cid, "created": result}

    def reject_candidate(self, cid: str, actor: str) -> None:
        self.store.set_candidate_status(cid, "rejected", actor)
