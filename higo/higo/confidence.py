"""증거 번들로부터 관계의 확신도(confidence)를 계산한다.

    support = 1 - Π(1 - w_tier)            (지지 증거들의 noisy-OR)
    contra  = 1 - Π(1 - w_tier)            (반대 증거들의 noisy-OR)
    conf    = support × status_factor × (1 - 0.6·contra)

- 원전(Tier 1) 하나만 있어도 0.9, 여러 독립 증거가 쌓일수록 1 에 가까워진다.
- 'disputed' / 'inferred' 관계는 증거가 많아도 상한이 낮아진다.
- 반대 증거가 제출되면 확신도가 떨어지고, 검증 워크플로에서 'contested' 로 전환할 근거가 된다.
- 증거가 필요 없는 관계(분류·귀속·시대 등)는 1.0 이며, 반대 증거가 있을 때만 낮아진다.
- URL 이 달린 증거와 AI 가 추가한 증거는 원문 대조를 통과해야만 계산에 들어간다.
"""
from __future__ import annotations

from . import ontology as O


def noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - p


def counts_toward_confidence(e: dict) -> bool:
    """URL 이 달린 증거와, AI 가 원전·학술 자료(1~5등급)라고 제시한 증거는 원문 대조를 통과(verified)해야
    확신도에 반영된다. 6등급(AI 추론임을 명시한 증거)과 사람이 큐레이션한 URL 없는 증거는 그대로 반영한다."""
    ai_claimed_source = str(e.get("added_by", "")).startswith("ai:") and int(e.get("tier", 6)) < 6
    if e.get("url") or ai_claimed_source:
        return e.get("verification") == "verified"
    return True


def compute_confidence(evidence: list[dict], evidence_status: str,
                       override: float | None = None, requires_evidence: bool = True) -> float:
    if override is not None:
        return round(max(0.0, min(1.0, override)), 4)
    evidence = [e for e in evidence if counts_toward_confidence(e)]
    support = [O.EVIDENCE_TIERS[e["tier"]].weight for e in evidence if e.get("stance", "supports") == "supports"]
    contra = [O.EVIDENCE_TIERS[e["tier"]].weight for e in evidence if e.get("stance") == "contradicts"]
    if not requires_evidence:
        # 분류·귀속 같은 관계는 증거가 없어도 성립한다. 반대 증거만 확신도를 낮춘다.
        return round(1.0 - 0.6 * noisy_or(contra), 4)
    if not support and not contra:
        return 0.0
    factor = O.EVIDENCE_STATUS.get(evidence_status, ("", 0.5))[1]
    value = noisy_or(support) * factor * (1.0 - 0.6 * noisy_or(contra))
    return round(value, 4)


def confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.6:
        return "medium"
    if value >= 0.3:
        return "low"
    return "speculative"
