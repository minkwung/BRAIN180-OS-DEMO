"""공백 분석기 — 온톨로지의 가장 약한 곳을 찾아 다음 작업 목록을 만든다.

재귀적 개선의 출발점이다. 매 주기 조사 에이전트는 이 목록의 상위 항목부터 처리하고,
처리 결과가 반영되면 다음 주기의 공백 분석 결과가 달라진다.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import ontology as O
from .graph import DEFAULT_STATUSES, GraphIndex
from .store import Store

TASK_KO = {
    "unverified_evidence": "원문 대조 실패·미확인 증거 재확인",
    "weak_influence": "확신도가 낮은 인과 관계 보강",
    "secondary_only": "2차 문헌뿐인 인과 관계에 원전 근거 확보",
    "pending_review": "검토 대기 중인 가설·이의 관계 근거 조사",
    "quote_missing": "원전 인용문 확보 (URL + 원문)",
    "thin_thinker": "명제가 부족한 사상가 보강",
    "concept_without_propositions": "명제가 없는 개념 보강",
    "work_without_propositions": "명제가 없는 저작 보강",
    "proposed_backlog": "승인 대기 중인 자동 추가 항목",
    "domain_coverage": "분야 확장 (로드맵)",
}

# 로드맵 기본값: 분야별 목표 인물 수 (data/roadmap.json 으로 덮어쓸 수 있다)
DEFAULT_ROADMAP = {
    "phase": 2,
    "domain_targets": {"domain:philosophy": 30, "domain:economics": 15, "domain:politics": 12,
                       "domain:science": 15, "domain:mathematics": 10, "domain:theology": 8,
                       "domain:literature": 10, "domain:art": 8, "domain:psychology": 6,
                       "domain:sociology": 6, "domain:law": 6},
    "min_propositions_per_thinker": 3,
}


def load_roadmap(data_dir: str | Path | None) -> dict:
    if data_dir:
        p = Path(data_dir) / "roadmap.json"
        if p.is_file():
            return {**DEFAULT_ROADMAP, **json.loads(p.read_text(encoding="utf-8"))}
    return DEFAULT_ROADMAP


def analyze(store: Store, roadmap: dict | None = None, limit: int = 40) -> dict:
    g = GraphIndex(store)
    rm = roadmap or DEFAULT_ROADMAP
    tasks: list[dict] = []

    def add(kind: str, priority: float, target: str | None, action: str, detail: str = "", **extra):
        tasks.append({"type": kind, "label_ko": TASK_KO[kind], "priority": round(priority, 3), "target": target,
                      "target_label": g.label(target) if target else None, "action": action, "detail": detail,
                      **extra})

    def importance(nid: str) -> float:
        return min(1.0, (len(g.out.get(nid, [])) + len(g.inc.get(nid, []))) / 60)

    evidence_by_edge: dict[str, list[dict]] = defaultdict(list)
    for ev in store.all_evidence():
        evidence_by_edge[ev["edge_id"]].append(ev)

    # 1) 원문 대조 실패·미확인
    for ev in store.all_evidence():
        v = ev.get("verification") or ""
        if ev.get("url") and v in ("", "partial", "fetch_failed", "not_found"):
            e = g.edges.get(ev["edge_id"])
            add("unverified_evidence", 0.95 if v == "not_found" else 0.8, e["source"] if e else None,
                f"{ev['id']} 의 URL·인용문을 다시 확인하거나 다른 판본으로 교체",
                detail=f"판정: {v or '미실행'} · {ev['url']}", edge_id=ev["edge_id"], evidence_id=ev["id"])

    # 2~4) 인과 관계의 증거 품질
    for e in g.edges.values():
        cat = O.RELATION_TYPES[e["predicate"]].category
        st = e["epistemic_status"]
        if cat in O.CAUSAL_CATEGORIES and st in DEFAULT_STATUSES:
            evs = evidence_by_edge.get(e["id"], [])
            desc = f"{g.label(e['source'])} —{O.RELATION_TYPES[e['predicate']].label_ko}→ {g.label(e['target'])}"
            if e["confidence"] < 0.7:
                add("weak_influence", 0.75 + (0.7 - e["confidence"]) * 0.3, e["source"],
                    f"{e['id']} 에 1·2등급 원전 증거(URL+인용문) 추가, 또는 반대 증거 조사", detail=desc,
                    edge_id=e["id"], confidence=e["confidence"])
            elif evs and all(ev["tier"] >= 3 for ev in evs if ev["stance"] == "supports"):
                add("secondary_only", 0.6 + importance(e["source"]) * 0.2, e["source"],
                    f"{e['id']} 에 원전(1등급) 근거 추가", detail=desc, edge_id=e["id"])
        if st in ("hypothesis", "contested"):
            add("pending_review", 0.7 if st == "contested" else 0.55, e["source"],
                f"{e['id']} 의 지지·반대 증거를 조사해 검토자 판단 자료 마련",
                detail=f"{g.label(e['source'])} —{O.RELATION_TYPES[e['predicate']].label_ko}→ {g.label(e['target'])} ({st})",
                edge_id=e["id"])

    # 5) 원전 인용문이 비어 있는 1·2등급 증거 (저작 단위로 묶음)
    by_work: Counter = Counter()
    for ev in store.all_evidence():
        if ev["tier"] <= 2 and ev.get("source_id") and not (ev.get("quotation") or "").strip():
            by_work[ev["source_id"]] += 1
    for work, n in by_work.most_common():
        add("quote_missing", 0.35 + min(0.3, n / 40) + importance(work) * 0.1, work,
            f"『{g.label(work)}』의 공개 원문(URL)에서 인용문 {n}건 확보", detail=f"인용문 없는 증거 {n}건", count=n)

    # 6~8) 내용이 얇은 곳
    min_props = rm.get("min_propositions_per_thinker", 3)
    for p in g.of_type("Person"):
        n = len(g.targets(p["id"], "proposes"))
        if n < min_props:
            add("thin_thinker", 0.5 + importance(p["id"]) * 0.3 + (min_props - n) * 0.03, p["id"],
                f"대표 저작에서 명제 {min_props - n}개 이상 추가 (원전 위치·인용 포함)", detail=f"현재 명제 {n}개")
    for c in g.of_type("Concept"):
        if not g.sources(c["id"], "about"):
            add("concept_without_propositions", 0.4 + importance(c["id"]) * 0.2, c["id"],
                "이 개념을 다루는 원전 명제 추가")
    for w in g.of_type("Work"):
        if not g.targets(w["id"], "contains"):
            add("work_without_propositions", 0.3 + importance(w["id"]) * 0.2, w["id"], "이 저작의 핵심 명제 추가")

    # 9) 승인 대기 중인 자동 추가 항목
    runs = Counter((e.get("props") or {}).get("run") for e in g.edges.values()
                   if e["epistemic_status"] == "proposed" and (e.get("props") or {}).get("run"))
    for run, n in runs.items():
        add("proposed_backlog", 0.9, None, f"`higo approve --run {run} --actor 이름` 으로 묶음 승인 또는 검토",
            detail=f"{run}: 제안 상태 관계 {n}건", run=run, count=n)

    # 10) 분야 확장
    persons_by_top: Counter = Counter()
    for p in g.of_type("Person"):
        for top in {g.top_domain(d) for d in g.targets(p["id"], "belongs_to_domain")}:
            persons_by_top[top] += 1
    for dom, target in rm.get("domain_targets", {}).items():
        have = persons_by_top.get(dom, 0)
        if have < target:
            add("domain_coverage", 0.2 + 0.4 * (1 - have / target), dom,
                f"{g.label(dom)} 분야 핵심 인물·저작 {target - have}명 추가", detail=f"현재 {have}/{target}명",
                have=have, target_count=target)

    tasks.sort(key=lambda t: -t["priority"])
    summary = Counter(t["type"] for t in tasks)
    return {"generated_at": time.time(), "total": len(tasks),
            "summary": {k: {"label_ko": TASK_KO[k], "count": n} for k, n in summary.most_common()},
            "tasks": tasks[:limit]}


def to_markdown(result: dict, top: int = 15) -> str:
    lines = ["| 유형 | 건수 |", "|---|---|"]
    for k, v in result["summary"].items():
        lines.append(f"| {v['label_ko']} | {v['count']} |")
    lines += ["", f"우선순위 상위 {min(top, len(result['tasks']))}개:", "",
              "| # | 우선순위 | 작업 | 대상 | 할 일 |", "|---|---|---|---|---|"]
    for i, t in enumerate(result["tasks"][:top], 1):
        target = t["target_label"] or "—"
        lines.append(f"| {i} | {t['priority']:.2f} | {t['label_ko']} | {target} | {t['action']} |")
    return "\n".join(lines)
