"""위험도별 자율성 정책 — 무엇을 자동 반영하고 무엇을 사람에게 올릴지 정한다.

    low         자동 반영 (상태 accepted), 주기 보고서에 기록 + 표본 감사
    medium      반영하되 상태 proposed → 주기별 묶음 승인
    high        관계는 hypothesis 로만 기록, 수정·상태 변경은 반영하지 않음 → 개별 승인
    structural  스키마 변경 제안 → 반영하지 않음, 개별 승인 + 온톨로지 버전 올림

원칙
- 영향·계승·비판(인과 관계)과 대립·모순 판단은 해석의 문제이므로 항상 high.
- 기존 사실의 수정·삭제·상태 변경은 항상 high (자동으로 지식을 지우지 않는다).
- low 는 '원문 대조 통과'가 전제다. 증거가 하나라도 원문 대조를 통과하지 못하면 medium 이상.
- 원문 대조 결과가 not_found(원문에 없음)이면 출처 날조 의심으로 해당 작업 전체를 기각한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import ontology as O
from .verify import FETCH_FAILED, NO_QUOTE, NO_URL, NOT_FOUND, PARTIAL, VERIFIED

LOW, MEDIUM, HIGH, STRUCTURAL, REJECTED = "low", "medium", "high", "structural", "rejected"
RISK_ORDER = [LOW, MEDIUM, HIGH, STRUCTURAL]
RISK_KO = {LOW: "낮음 (자동 반영)", MEDIUM: "중간 (묶음 승인)", HIGH: "높음 (개별 승인)",
           STRUCTURAL: "구조 변경 (개별 승인)", REJECTED: "자동 기각"}

# 사실 확인형 관계 — 원문 대조를 통과하면 자동 반영할 수 있다
LOW_RISK_PREDICATES = {"authored", "belongs_to_domain", "active_in", "affiliated_with", "member_of"}
# 해석이 들어가는 관계 — 항상 사람의 개별 판단
HIGH_RISK_PREDICATES = {"contradicted_by", "opposed_to", "contrasts_with"}
# 날짜 등 사실 속성을 자동 반영할 수 있는 엔티티 유형
FACTUAL_ENTITY_TYPES = {"Person", "Work", "Event", "Institution"}
# 자동 반영에 필요한 원문 대조 통과 증거 조건
MIN_VERIFIED_LOW_TIER = 2          # 이 등급 이하(1·2등급) 증거 1건이 원문 대조를 통과하거나
MIN_INDEPENDENT_VERIFIED = 2       # 서로 다른 출처(도메인) 2건 이상이 원문 대조를 통과해야 한다


@dataclass
class Decision:
    risk: str
    reasons: list[str] = field(default_factory=list)

    def escalate(self, to: str, reason: str) -> None:
        if to == REJECTED or RISK_ORDER.index(to) > RISK_ORDER.index(self.risk):
            self.risk = to
        self.reasons.append(reason)


def base_risk(op: dict) -> Decision:
    kind = op.get("op")
    if kind == "schema_change":
        return Decision(STRUCTURAL, ["스키마 변경은 구조 변경으로 분류"])
    if kind in ("update_entity", "set_status", "delete_entity", "delete_edge"):
        return Decision(HIGH, ["기존 지식의 수정·삭제·상태 변경은 사람이 개별 판단"])
    if kind == "add_edge":
        pred = (op.get("edge") or {}).get("predicate", "")
        cat = O.RELATION_TYPES[pred].category if pred in O.RELATION_TYPES else ""
        if cat in O.CAUSAL_CATEGORIES:
            return Decision(HIGH, [f"'{pred}'은(는) 인과 관계(영향·계승·비판) — 해석 판단이 필요"])
        if pred in HIGH_RISK_PREDICATES:
            return Decision(HIGH, [f"'{pred}'은(는) 대립·모순 판단 — 해석 판단이 필요"])
        if pred in LOW_RISK_PREDICATES:
            return Decision(LOW, [f"'{pred}'은(는) 사실 확인형 관계"])
        return Decision(MEDIUM, [f"'{pred}'은(는) 개념·내용 관계 — 묶음 승인"])
    if kind == "add_entity":
        typ = (op.get("entity") or {}).get("type", "")
        if typ in FACTUAL_ENTITY_TYPES:
            return Decision(LOW, [f"{typ} 기본 정보(이름·연도)는 사실 확인형"])
        return Decision(MEDIUM, [f"{typ} 는 개념적 판단이 들어감 — 묶음 승인"])
    if kind == "add_proposition":
        return Decision(MEDIUM, ["명제의 요약·원전 위치는 묶음 승인"])
    if kind == "add_evidence":
        evs = op.get("evidence") or []
        if any(e.get("stance") == "contradicts" for e in evs):
            return Decision(HIGH, ["반대 증거는 기존 관계에 이의를 제기하므로 개별 판단"])
        return Decision(LOW, ["기존 관계에 지지 증거 추가"])
    return Decision(HIGH, [f"알 수 없는 작업 '{kind}' — 사람이 판단"])


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def apply_verification(decision: Decision, evidence: list[dict], verdicts: list[str]) -> Decision:
    """원문 대조 결과로 위험도를 조정한다. verdicts 는 evidence 와 같은 순서의 판정 목록."""
    if any(v == NOT_FOUND for v in verdicts):
        decision.escalate(REJECTED, "원문 대조 결과 인용문이 출처에 없음 — 출처 날조 의심으로 자동 기각")
        return decision
    if decision.risk != LOW:
        if any(v in (PARTIAL, FETCH_FAILED) for v in verdicts):
            decision.reasons.append("일부 증거가 원문 대조를 완전히 통과하지 못함 — 검토 시 확인 필요")
        return decision
    verified = [(e, v) for e, v in zip(evidence, verdicts) if v == VERIFIED]
    strong = [e for e, _ in verified if int(e.get("tier", 9)) <= MIN_VERIFIED_LOW_TIER]
    domains = {_domain(e.get("url", "")) for e, _ in verified}
    if not evidence:
        decision.escalate(MEDIUM, "증거가 없어 자동 반영 불가")
    elif not (strong or len(domains) >= MIN_INDEPENDENT_VERIFIED):
        missing = {NO_URL: "URL 없음", NO_QUOTE: "인용문 없음", PARTIAL: "부분 일치", FETCH_FAILED: "문서 열기 실패"}
        why = ", ".join(sorted({missing.get(v, v) for v in verdicts if v != VERIFIED})) or "독립 출처 부족"
        decision.escalate(MEDIUM, f"자동 반영 조건(1·2등급 원문 일치 1건 또는 독립 출처 2곳 일치) 미충족: {why}")
    else:
        decision.reasons.append(f"원문 대조 통과 {len(verified)}건 (출처 {len(domains)}곳)")
    return decision
