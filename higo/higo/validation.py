"""스키마 검증과 인간 검증(Human Validation) 워크플로.

- validate_edge: domain/range, 증거 요구, 시간 순서, 영향/유사성 혼동 등을 검사
- validate_graph: 전체 그래프 감사(audit)
- Reviewer: 가설 → 승인/기각/이의제기/수정 상태 전이를 기록하는 검증 게이트
"""
from __future__ import annotations

import time

from . import ontology as O
from .store import Store


def _type_ok(allowed: tuple[str, ...], t: str) -> bool:
    return O.ANY in allowed or t in allowed


def _year_span(entity: dict) -> tuple[int | None, int | None]:
    return entity.get("start_year"), entity.get("end_year")


def validate_edge(store: Store, edge: dict, report: O.ValidationReport | None = None) -> O.ValidationReport:
    report = report or O.ValidationReport()
    ref = edge.get("id")
    try:
        rel = O.relation(edge["predicate"])
    except KeyError:
        report.error("unknown_predicate", f"알 수 없는 관계: {edge['predicate']}", ref)
        return report
    src, tgt = store.get_entity(edge["source"]), store.get_entity(edge["target"])
    if not src or not tgt:
        report.error("dangling_edge", "존재하지 않는 엔티티를 가리킴", ref)
        return report
    if not _type_ok(rel.domain, src["type"]):
        report.error("domain_violation",
                     f"{rel.name} 의 source 는 {rel.domain} 이어야 함 (현재 {src['type']}: {src['id']})", ref)
    if not _type_ok(rel.range, tgt["type"]):
        report.error("range_violation",
                     f"{rel.name} 의 target 은 {rel.range} 이어야 함 (현재 {tgt['type']}: {tgt['id']})", ref)
    if src["id"] == tgt["id"]:
        report.error("self_loop", "자기 자신을 가리키는 관계", ref)

    status = edge.get("epistemic_status")
    evidence = store.list_evidence(ref) if ref else edge.get("evidence", [])
    if rel.requires_evidence and status == "accepted" and not evidence:
        report.error("missing_evidence", f"'{rel.name}' 관계는 승인 전에 증거가 필요함", ref)
    if status == "accepted" and edge.get("origin") == "ai":
        # AI 가 만든 관계는 반드시 사람이 승인해야 하며, 승인자가 history 에 남아야 한다.
        approvals = [h for h in store.history(ref) if h["action"] == "review"
                     and (h.get("after") or {}).get("epistemic_status") == "accepted"
                     and not str(h.get("actor", "")).startswith(("ai", "system"))]
        if not approvals:
            report.error("unreviewed_ai_edge", "AI 가 생성한 관계가 인간 검증 없이 승인 상태임", ref)
    if evidence and all(e["tier"] == 6 for e in evidence) and status == "accepted":
        report.warn("ai_only_evidence", "승인된 관계의 증거가 AI 추론(Tier 6)뿐임", ref)

    # 시간 순서: 영향은 과거에서 미래로만 흐른다.
    if rel.temporal_order:
        s0, s1 = _year_span(src)
        t0, t1 = _year_span(tgt)
        if s0 is not None and t1 is not None and s0 > t1:
            report.error("anachronism", f"{src['label']}({s0}) 는 {tgt['label']}(~{t1}) 이후라 영향을 줄 수 없음", ref)
        elif s0 is not None and t0 is not None and s0 > t0 + 60:
            report.warn("late_influence", f"source({s0}) 가 target({t0}) 보다 훨씬 늦음 — 방향 확인 필요", ref)

    # 영향과 유사성의 혼동 방지: 유사성 관계에 '직접' 증거 상태를 두는 것은 의미상 모순에 가깝다.
    if rel.category in O.NON_CAUSAL_CATEGORIES and edge.get("evidence_status") == "direct":
        note = (edge.get("note") or "").lower()
        if "influence" in note or "영향" in note:
            report.warn("similarity_as_influence",
                        "유사성 관계의 메모가 영향을 암시함 — 'influenced' 관계로 따로 등록하고 증거를 붙일 것", ref)
    return report


def validate_graph(store: Store) -> O.ValidationReport:
    report = O.ValidationReport()
    for edge in store.list_edges():
        validate_edge(store, edge, report)
    # 고립 노드 (Domain/Era 제외)
    linked = set()
    for e in store.list_edges():
        linked.add(e["source"])
        linked.add(e["target"])
    for ent in store.list_entities():
        if ent["id"] not in linked and ent["type"] not in ("Domain", "Era", "Source"):
            report.warn("isolated_entity", f"연결이 없는 엔티티: {ent['label']}", ent["id"])
    # 명제는 저자와 저작이 있어야 한다
    for p in store.list_entities(type="Proposition"):
        if not store.list_edges(target=p["id"], predicate="proposes"):
            report.warn("orphan_proposition", f"저자가 없는 명제: {p['label']}", p["id"])
        if not store.list_edges(target=p["id"], predicate="contains"):
            report.warn("unsourced_proposition", f"저작이 없는 명제: {p['label']}", p["id"])
    return report


class ReviewError(Exception):
    pass


class Reviewer:
    """AI = Discovery Engine, Human = Epistemic Authority.

    모든 상태 전이는 사람(actor)과 사유(reason)를 남긴다.
    """

    def __init__(self, store: Store):
        self.store = store

    def transition(self, edge_id: str, new_status: str, actor: str, reason: str = "") -> dict:
        edge = self.store.get_edge(edge_id)
        if not edge:
            raise ReviewError(f"edge not found: {edge_id}")
        if not actor or actor.startswith(("ai", "system")):
            raise ReviewError("검증 상태 변경은 사람 검토자(actor)가 필요합니다")
        cur = edge["epistemic_status"]
        if new_status not in O.STATUS_TRANSITIONS.get(cur, set()):
            raise ReviewError(f"허용되지 않는 전이: {cur} → {new_status}")
        if new_status == "accepted":
            probe = dict(edge, epistemic_status="accepted")
            rep = O.ValidationReport()
            validate_edge(self.store, {**probe, "origin": "human"}, rep)
            errors = [i for i in rep.issues if i.level == "error"]
            if errors:
                raise ReviewError("; ".join(i.message for i in errors))
        with self.store.tx() as c:
            c.execute("UPDATE edges SET epistemic_status=?, version=version+1, updated_at=?"
                      " WHERE id=?", (new_status, time.time(), edge_id))
            self.store._log(c, "edge", edge_id, "review", {"epistemic_status": cur},
                            {"epistemic_status": new_status}, actor, reason)
        return self.store.get_edge(edge_id, with_evidence=True)  # type: ignore[return-value]

    def approve(self, edge_id: str, actor: str, reason: str = "") -> dict:
        return self.transition(edge_id, "accepted", actor, reason)

    def reject(self, edge_id: str, actor: str, reason: str = "") -> dict:
        return self.transition(edge_id, "rejected", actor, reason)

    def contest(self, edge_id: str, actor: str, reason: str, counter_evidence: dict | None = None) -> dict:
        if counter_evidence:
            self.store.add_evidence(edge_id, stance="contradicts", added_by=actor, **counter_evidence)
        return self.transition(edge_id, "contested", actor, reason)

    def revise(self, edge_id: str, actor: str, reason: str, **changes) -> dict:
        if changes:
            self.store.update_edge(edge_id, actor=actor, reason=reason, **changes)
        return self.transition(edge_id, "revised", actor, reason)

    def queue(self, include_contested: bool = True) -> list[dict]:
        statuses = ["hypothesis", "proposed"] + (["contested"] if include_contested else [])
        edges = self.store.list_edges(statuses=statuses)
        out = []
        for e in edges:
            e = dict(e)
            e["evidence"] = self.store.list_evidence(e["id"])
            s, t = self.store.get_entity(e["source"]), self.store.get_entity(e["target"])
            e["source_label"] = (s or {}).get("label_ko") or (s or {}).get("label")
            e["target_label"] = (t or {}).get("label_ko") or (t or {}).get("label")
            e["validation"] = validate_edge(self.store, dict(e, epistemic_status="accepted", origin="human")).as_dict()
            out.append(e)
        out.sort(key=lambda e: (-e["confidence"], e["id"]))
        return out
