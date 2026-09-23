"""증거 번들로부터 관계의 확신도(confidence)를 계산한다.

    support = 1 - Π(1 - w_tier)            (지지 증거들의 noisy-OR)
    contra  = 1 - Π(1 - w_tier)            (반대 증거들의 noisy-OR)
    conf    = support × status_factor × (1 - 0.6·contra)

- 원전(Tier 1) 하나만 있어도 0.9, 여러 독립 증거가 쌓일수록 1 에 가까워진다.
- 'disputed' / 'inferred' 관계는 증거가 많아도 상한이 낮아진다.
- 반대 증거가 제출되면 확신도가 떨어지고, 검증 워크플로에서 'contested' 로 전환할 근거가 된다.
- 증거가 필요 없는 관계(분류·시대 등)는 증거가 없으면 1.0 으로 둔다.
"""
from __future__ import annotations

from . import ontology as O


def noisy_or(weights: list[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - p


def compute_confidence(evidence: list[dict], evidence_status: str,
                       override: float | None = None, requires_evidence: bool = True) -> float:
    if override is not None:
        return round(max(0.0, min(1.0, override)), 4)
    support = [O.EVIDENCE_TIERS[e["tier"]].weight for e in evidence if e.get("stance", "supports") == "supports"]
    contra = [O.EVIDENCE_TIERS[e["tier"]].weight for e in evidence if e.get("stance") == "contradicts"]
    if not support and not contra:
        return 1.0 if not requires_evidence else 0.0
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
