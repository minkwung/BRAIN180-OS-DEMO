"""변경 묶음(changeset) 적용기 — 자동 갱신 주기의 관문.

조사 에이전트(2단계)는 그래프를 직접 고치지 않는다. 아래 형식의 JSON 을 내놓으면,
이 모듈이 스키마 검사 → 중복 검사 → 인용문 원문 대조 → 위험도 분류 → 등급별 반영을 한다.

    {
      "agent": {"model": "...", "prompt_version": "..."},
      "operations": [
        {"op": "add_entity", "entity": {"type": "Person", "label": "...", "label_ko": "...",
                                        "start_year": 1711, "end_year": 1776, "description": "..."},
         "evidence": [{"tier": 1, "url": "...", "quotation": "...", "citation": "...", "locator": "..."}],
         "rationale": "왜 추가하는가"},
        {"op": "add_edge", "edge": {"source": "...", "predicate": "...", "target": "...",
                                    "evidence_status": "direct"}, "evidence": [...], "rationale": "..."},
        {"op": "add_proposition", "proposition": {"author": "person:x", "work": "work:y", "statement": "...",
                                                  "statement_en": "...", "locator": "...", "year": 1740,
                                                  "concepts": ["concept:z"]}, "evidence": [...]},
        {"op": "add_evidence", "edge_id": "E00123", "evidence": [...]},
        {"op": "update_entity", "id": "...", "changes": {...}, "evidence": [...]},
        {"op": "set_status", "edge_id": "E00123", "status": "rejected", "reason": "..."},
        {"op": "schema_change", "description": "...", "proposal": {...}}
      ]
    }
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import ontology as O
from .ids import make_id
from .policy import HIGH, LOW, MEDIUM, REJECTED, STRUCTURAL, Decision, apply_verification, base_risk
from .store import Store
from .validation import ReviewError, Reviewer, validate_edge
from .verify import QuoteVerifier

AUTO_ACTOR = "policy:auto"
AUDIT_RATE = 0.05


@dataclass
class OpResult:
    index: int
    op: str
    summary: str
    risk: str
    outcome: str                   # applied_accepted | applied_proposed | applied_hypothesis | pending | rejected | skipped
    reasons: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    verification: list[dict] = field(default_factory=list)
    rationale: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def new_run_id(runs_dir: Path | None = None) -> str:
    day = time.strftime("%Y%m%d")
    n = 1
    if runs_dir and runs_dir.is_dir():
        n = 1 + sum(1 for p in runs_dir.glob(f"R{day}-*.json"))
    return f"R{day}-{n:02d}"


class ChangesetApplier:
    def __init__(self, store: Store, verifier: QuoteVerifier | None = None, run_id: str | None = None):
        self.store = store
        self.verifier = verifier or QuoteVerifier()
        self.run_id = run_id or new_run_id()
        self.reviewer = Reviewer(store)

    # ------------------------------------------------------------ helpers
    def _label(self, eid: str) -> str:
        e = self.store.get_entity(eid)
        return (e.get("label_ko") or e["label"]) if e else eid

    def _verify(self, evidence: list[dict]) -> tuple[list[str], list[dict]]:
        verdicts, details = [], []
        for ev in evidence:
            v = self.verifier.check(ev.get("url", ""), ev.get("quotation", ""))
            ev["_verdict"] = v
            verdicts.append(v.status)
            details.append({"url": ev.get("url", ""), "citation": ev.get("citation", ""), **v.as_dict()})
        return verdicts, details

    def _evidence_kwargs(self, ev: dict) -> dict:
        v = ev.get("_verdict")
        src = ev.get("source_id")
        return dict(tier=int(ev["tier"]), source_id=src if src and self.store.get_entity(src) else None,
                    citation=ev.get("citation", "") or (src or ""), stance=ev.get("stance", "supports"),
                    locator=ev.get("locator", ""), quotation=ev.get("quotation", ""),
                    interpretation=ev.get("interpretation", ""), added_by=f"ai:{self.run_id}",
                    url=ev.get("url", ""), verification=v.status if v and ev.get("url") else "",
                    retrieved_at=v.retrieved_at if v else None, content_hash=v.content_hash if v else "",
                    verified_at=time.time() if v and ev.get("url") else None)

    def _run_props(self, risk: str, extra: dict | None = None) -> dict:
        return {"run": self.run_id, "risk": risk, **(extra or {})}

    def _log_auto(self, kind: str, oid: str, reasons: list[str]) -> None:
        # 자동 반영 사실을 데이터 파일에도 남긴다 (history 는 파일에 저장하지 않음)
        stamp = {"run": self.run_id, "policy": "low-risk verified", "at": round(time.time())}
        if kind == "edge":
            e = self.store.get_edge(oid)
            if e and not (e.get("props") or {}).get("auto_accepted"):
                self.store.update_edge(oid, props={**(e.get("props") or {}), "auto_accepted": stamp},
                                       actor=AUTO_ACTOR, reason="auto_accept")
        with self.store.tx() as c:
            self.store._log(c, kind, oid, "auto_accept", None, {"run": self.run_id}, AUTO_ACTOR, "; ".join(reasons))

    # ------------------------------------------------------------ main
    def apply(self, changeset: dict) -> dict:
        results: list[OpResult] = []
        for i, op in enumerate(changeset.get("operations", [])):
            try:
                results.append(self._apply_one(i, op))
            except (KeyError, ValueError, ReviewError) as exc:
                results.append(OpResult(i, op.get("op", "?"), json.dumps(op, ensure_ascii=False)[:120], REJECTED,
                                        "rejected", [f"형식·스키마 오류: {exc}"], rationale=op.get("rationale", "")))
        low_applied = [r for r in results if r.risk == LOW and r.outcome == "applied_accepted"]
        rng = random.Random(self.run_id)
        k = min(len(low_applied), max(1, round(len(low_applied) * AUDIT_RATE))) if low_applied else 0
        audit = [r.index for r in rng.sample(low_applied, k)] if k else []
        return {"run_id": self.run_id, "agent": changeset.get("agent", {}), "applied_at": time.time(),
                "results": [r.as_dict() for r in results], "audit_sample": audit}

    def _apply_one(self, i: int, op: dict) -> OpResult:
        kind = op.get("op")
        evidence = [dict(e) for e in op.get("evidence") or []]
        decision = base_risk(op)
        verdicts, vdetails = self._verify(evidence)
        decision = apply_verification(decision, evidence, verdicts)
        res = OpResult(i, kind or "?", "", decision.risk, "pending", decision.reasons, verification=vdetails,
                       rationale=op.get("rationale", ""))
        handler = getattr(self, f"_op_{kind}", None)
        if handler is None:
            res.summary, res.outcome = f"알 수 없는 작업 {kind}", "rejected"
            return res
        handler(op, evidence, decision, res)
        return res

    # ------------------------------------------------------------ operations
    def _op_add_entity(self, op, evidence, decision: Decision, res: OpResult):
        ent = op["entity"]
        typ, label = ent["type"], ent["label"]
        if typ not in O.ENTITY_TYPES:
            raise ValueError(f"unknown entity type {typ}")
        eid = ent.get("id") or make_id(typ, label)
        res.summary = f"{O.ENTITY_TYPES[typ].label_ko} 추가: {ent.get('label_ko') or label} ({eid})"
        res.refs = [eid]
        dup = self.store.get_entity(eid) or next(
            (e for e in self.store.list_entities(type=typ, q=label, limit=20)
             if e["label"].lower() == label.lower() or (ent.get("label_ko") and e.get("label_ko") == ent.get("label_ko"))),
            None)
        if dup:
            res.outcome, res.refs = "skipped", [dup["id"]]
            res.reasons.append(f"이미 있는 엔티티 {dup['id']} — 중복 추가 안 함 (수정은 update_entity 로 제안)")
            return
        if decision.risk == REJECTED:
            res.outcome = "rejected"
            return
        sources = [{k: v for k, v in self._evidence_kwargs(ev).items()
                    if k in ("tier", "url", "citation", "locator", "quotation", "verification") and v}
                   for ev in evidence]
        props = {**(ent.get("props") or {}), **self._run_props(decision.risk), "sources": sources}
        status = "accepted" if decision.risk == LOW else "proposed"
        self.store.upsert_entity(eid, typ, label, label_ko=ent.get("label_ko"), aliases=ent.get("aliases", []),
                                 description=ent.get("description", ""), props=props,
                                 start_year=ent.get("start_year"), end_year=ent.get("end_year"), origin="ai",
                                 status=status, actor=f"ai:{self.run_id}")
        if status == "accepted":
            self._log_auto("entity", eid, decision.reasons)
        res.outcome = "applied_accepted" if status == "accepted" else "applied_proposed"

    def _add_edge(self, edge: dict, evidence, decision: Decision, res: OpResult, extra_props=None) -> str | None:
        src, pred, tgt = edge["source"], edge["predicate"], edge["target"]
        if pred not in O.RELATION_TYPES:
            raise ValueError(f"unknown predicate {pred}")
        existing = self.store.find_edge(src, pred, tgt)
        if existing:
            if decision.risk == REJECTED:
                res.outcome = "rejected"
                return None
            # 이미 있는 관계라면 증거만 보탠다
            for ev in evidence:
                self.store.add_evidence(existing["id"], **self._evidence_kwargs(ev))
            res.outcome, res.refs = "skipped", [existing["id"]]
            res.reasons.append(f"이미 있는 관계 {existing['id']} — 증거 {len(evidence)}건만 추가")
            return existing["id"]
        epi = {LOW: "accepted", MEDIUM: "proposed", HIGH: "hypothesis"}.get(decision.risk)
        probe = {"source": src, "predicate": pred, "target": tgt, "epistemic_status": "proposed",
                 "evidence_status": edge.get("evidence_status", "direct")}
        rep = validate_edge(self.store, probe)
        if not rep.ok:
            raise ValueError("; ".join(i.message for i in rep.issues if i.level == "error"))
        if decision.risk == REJECTED or epi is None:
            res.outcome = "rejected" if decision.risk == REJECTED else "pending"
            return None
        e = self.store.add_edge(src, pred, tgt, evidence_status=edge.get("evidence_status", "inferred"),
                                epistemic_status=epi, origin="ai", note=edge.get("note", ""),
                                props=self._run_props(decision.risk, extra_props), actor=f"ai:{self.run_id}")
        for ev in evidence:
            self.store.add_evidence(e["id"], **self._evidence_kwargs(ev))
        if epi == "accepted":
            self._log_auto("edge", e["id"], decision.reasons)
        res.refs.append(e["id"])
        res.outcome = {"accepted": "applied_accepted", "proposed": "applied_proposed",
                       "hypothesis": "applied_hypothesis"}[epi]
        return e["id"]

    def _op_add_edge(self, op, evidence, decision, res):
        edge = op["edge"]
        pred = edge["predicate"]
        rel_ko = O.RELATION_TYPES[pred].label_ko if pred in O.RELATION_TYPES else pred
        res.summary = f"관계 추가: {self._label(edge['source'])} —{rel_ko}→ {self._label(edge['target'])}"
        self._add_edge(edge, evidence, decision, res)

    def _op_add_proposition(self, op, evidence, decision, res):
        p = op["proposition"]
        for k in ("author", "work"):
            if p.get(k) and not self.store.get_entity(p[k]):
                raise KeyError(f"{k} not found: {p[k]}")
        pid = p.get("id") or make_id("Proposition", f"{p['author'].split(':')[-1]}-{p['statement'][:48]}")
        res.summary = f"명제 추가 ({self._label(p['author'])}): {p['statement'][:60]}"
        res.refs = [pid]
        if self.store.get_entity(pid):
            res.outcome = "skipped"
            res.reasons.append(f"이미 있는 명제 {pid}")
            return
        if decision.risk == REJECTED:
            res.outcome = "rejected"
            return
        status = "accepted" if decision.risk == LOW else "proposed"
        stmt = p["statement"]
        self.store.upsert_entity(pid, "Proposition", stmt if len(stmt) <= 80 else stmt[:78] + "…",
                                 props={"statement": stmt, "statement_en": p.get("statement_en", ""),
                                        "locator": p.get("locator", ""), "year": p.get("year"),
                                        "certainty": p.get("certainty", "paraphrase"),
                                        **self._run_props(decision.risk)},
                                 start_year=p.get("year"), origin="ai", status=status, actor=f"ai:{self.run_id}")
        sub = OpResult(res.index, "add_edge", "", decision.risk, "pending")
        self._add_edge({"source": p["author"], "predicate": "proposes", "target": pid, "evidence_status": "direct"},
                       evidence, decision, sub)
        res.refs += sub.refs
        if p.get("work"):
            self._add_edge({"source": p["work"], "predicate": "contains", "target": pid, "evidence_status": "direct"},
                           [], decision, sub)
            res.refs += sub.refs[-1:]
        for c in p.get("concepts", []):
            if self.store.get_entity(c):
                self._add_edge({"source": pid, "predicate": "about", "target": c, "evidence_status": "direct"},
                               [], decision, sub)
            else:
                res.reasons.append(f"개념 {c} 없음 — 연결 생략")
        res.outcome = "applied_accepted" if status == "accepted" else "applied_proposed"

    def _op_add_evidence(self, op, evidence, decision, res):
        eid = op.get("edge_id")
        if not eid and op.get("edge"):
            e = self.store.find_edge(op["edge"]["source"], op["edge"]["predicate"], op["edge"]["target"])
            eid = e["id"] if e else None
        edge = self.store.get_edge(eid or "")
        if not edge:
            raise KeyError(f"edge not found: {eid}")
        res.summary = (f"증거 추가 → {eid}: {self._label(edge['source'])} —{O.RELATION_TYPES[edge['predicate']].label_ko}→ "
                       f"{self._label(edge['target'])}")
        res.refs = [eid]
        if decision.risk == REJECTED:
            res.outcome = "rejected"
            return
        before = edge["confidence"]
        added = [self.store.add_evidence(eid, **self._evidence_kwargs(ev))["id"] for ev in evidence]
        after = self.store.get_edge(eid)["confidence"]
        res.refs += added
        res.reasons.append(f"확신도 {before:.2f} → {after:.2f}")
        if decision.risk == HIGH:
            # 반대 증거: 증거는 기록하되 상태 전환(이의 제기)은 사람이 결정
            res.outcome = "pending"
            res.reasons.append("반대 증거는 기록했으며, '이의 제기' 전환은 검토자가 결정")
        else:
            if decision.risk == LOW:
                self._log_auto("edge", eid, decision.reasons)
            res.outcome = "applied_accepted" if decision.risk == LOW else "applied_proposed"

    def _op_update_entity(self, op, evidence, decision, res):
        res.summary = f"수정 제안: {self._label(op['id'])} {json.dumps(op.get('changes', {}), ensure_ascii=False)[:80]}"
        res.refs = [op["id"]]
        res.outcome = "rejected" if decision.risk == REJECTED else "pending"

    def _op_set_status(self, op, evidence, decision, res):
        res.summary = f"상태 변경 제안: {op.get('edge_id')} → {op.get('status')} ({op.get('reason', '')})"
        res.refs = [op.get("edge_id", "")]
        res.outcome = "pending"

    def _op_schema_change(self, op, evidence, decision, res):
        res.summary = f"스키마 변경 제안: {op.get('description', '')[:100]}"
        res.outcome = "pending"
        assert decision.risk == STRUCTURAL


# --------------------------------------------------------------------- batch
def approve_run(store: Store, run_id: str, actor: str, reason: str = "", risks=(MEDIUM,)) -> dict:
    """주기 단위 묶음 승인 — 해당 주기에서 제안 상태로 들어온 항목을 승인한다."""
    if not actor or actor.startswith(("ai", "system", "policy")):
        raise ReviewError("묶음 승인에는 사람 검토자 이름이 필요합니다")
    rv = Reviewer(store)
    approved, failed = [], []
    for e in store.list_edges(statuses=["proposed"]):
        props = e.get("props") or {}
        if props.get("run") == run_id and props.get("risk") in risks:
            try:
                rv.approve(e["id"], actor, reason or f"{run_id} 묶음 승인")
                approved.append(e["id"])
            except ReviewError as exc:
                failed.append({"id": e["id"], "error": str(exc)})
    for ent in store.list_entities(limit=10**9):
        props = ent.get("props") or {}
        if ent.get("status") == "proposed" and props.get("run") == run_id and props.get("risk") in risks:
            props = {**props, "review": {"status": "accepted", "actor": actor, "at": round(time.time()),
                                         "reason": reason or f"{run_id} 묶음 승인"}}
            store.upsert_entity(ent["id"], ent["type"], ent["label"], label_ko=ent.get("label_ko"),
                                aliases=ent.get("aliases", []), description=ent.get("description", ""), props=props,
                                start_year=ent.get("start_year"), end_year=ent.get("end_year"),
                                origin=ent.get("origin", "ai"), status="accepted", actor=actor)
            approved.append(ent["id"])
    return {"run_id": run_id, "approved": approved, "failed": failed}


def load_changeset(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data.get("operations"), list):
        raise ValueError("changeset 에 operations 목록이 없음")
    return data
