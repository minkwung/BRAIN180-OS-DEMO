"""HIGO Ontology v0.1 — 엔티티·관계·증거·인식론적 상태의 스키마 정의.

설계 원칙
---------
1. 인물 그래프가 아니라 '사상 그래프': Person 은 여러 노드 타입 중 하나일 뿐이다.
2. 관계는 의미 범주(category)를 가진다. 특히 '영향(causal)'과 '유사성(non-causal)'은
   절대 섞지 않는다. 추론 엔진은 category 로 둘을 구분한다.
3. 모든 중요한 Edge 는 Evidence Bundle 을 가질 수 있고, 출처 위계(Tier 1~6)에 따라
   확신도(confidence)가 계산된다.
4. AI 가 만든 연결은 처음부터 사실이 아니라 'hypothesis' 로 저장되며, 사람의 검증을
   거쳐야만 'accepted' 가 된다 (AI = Discovery Engine, Human = Epistemic Authority).
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityType:
    name: str
    prefix: str
    label_ko: str
    description: str
    properties: tuple[str, ...] = ()


ENTITY_TYPES: dict[str, EntityType] = {
    t.name: t
    for t in [
        EntityType("Person", "person", "인물", "사상가·과학자·작가 등 지적 행위자",
                   ("born", "died", "nationality")),
        EntityType("Work", "work", "저작", "책·논문·편지·강연 등 원전",
                   ("year", "language", "original_title")),
        EntityType("Concept", "concept", "개념", "사상의 기본 단위가 되는 개념",
                   ("definition",)),
        EntityType("Proposition", "prop", "명제", "특정 저작에서 특정 저자가 제시한 주장",
                   ("statement", "statement_en", "locator", "year", "certainty", "interpretation")),
        EntityType("Argument", "arg", "논증", "전제 명제들로부터 결론 명제를 이끌어내는 구조",
                   ("form",)),
        EntityType("School", "school", "학파", "공통 교설을 공유하는 사상가 집단", ()),
        EntityType("Movement", "movement", "사조", "시대를 가로지르는 지적 흐름", ()),
        EntityType("Domain", "domain", "분야", "지식 분야 온톨로지의 노드", ()),
        EntityType("Era", "era", "시대", "시대 축의 구간", ()),
        EntityType("Institution", "inst", "기관", "대학·아카데미·학회 등", ()),
        EntityType("Event", "event", "사건", "사상의 역사적 맥락이 되는 사건", ()),
        EntityType("Source", "source", "출처", "2차 연구·백과사전 등 증거의 출처",
                   ("tier", "publisher", "url")),
        EntityType("Interpretation", "interp", "해석", "명제나 관계에 대한 학자의 해석", ()),
    ]
}

# ---------------------------------------------------------------------------
# Relation types
# ---------------------------------------------------------------------------

# 관계 범주 — 추론 엔진은 이 범주를 기준으로 경로의 의미를 판정한다.
CAT_AUTHORSHIP = "authorship"      # 저작·명제 귀속
CAT_CONTENT = "content"            # 저작/명제가 무엇을 다루는가
CAT_INFLUENCE = "influence"        # 인과적 영향 (증거 필수)
CAT_SUCCESSION = "succession"      # 지적 계승·변형 (인과적)
CAT_CRITIQUE = "critique"          # 반론·비판 (인과적, 대립)
CAT_CONCEPTUAL = "conceptual"      # 개념 간 논리적 관계
CAT_SIMILARITY = "similarity"      # 구조적 유사성 (비인과적!)
CAT_OPPOSITION = "opposition"      # 개념적 대립 (비인과적)
CAT_HISTORICAL = "historical"      # 시대·맥락
CAT_EVIDENCE = "evidence"          # 증거·출처
CAT_TAXONOMY = "taxonomy"          # 분류 체계
CAT_ARGUMENT = "argument"          # 논증 구조

CAUSAL_CATEGORIES = {CAT_INFLUENCE, CAT_SUCCESSION, CAT_CRITIQUE}
NON_CAUSAL_CATEGORIES = {CAT_SIMILARITY, CAT_OPPOSITION}

ANY = "*"
AGENTS = ("Person", "School", "Movement", "Work")
IDEAS = ("Concept", "Proposition", "Argument", "Work", "School", "Movement")
INTELLECTUAL = ("Person", "Work", "Concept", "Proposition", "Argument", "School", "Movement")


@dataclass(frozen=True)
class RelationType:
    name: str
    category: str
    label_ko: str
    description: str
    domain: tuple[str, ...] = (ANY,)
    range: tuple[str, ...] = (ANY,)
    inverse: str | None = None
    symmetric: bool = False
    requires_evidence: bool = False
    temporal_order: bool = False  # source 가 target 보다 시간적으로 앞서야 하는가


RELATION_TYPES: dict[str, RelationType] = {
    r.name: r
    for r in [
        # --- authorship
        RelationType("authored", CAT_AUTHORSHIP, "저술", "인물이 저작을 썼다",
                     ("Person",), ("Work",), inverse="authored_by"),
        RelationType("proposes", CAT_AUTHORSHIP, "주장", "인물이 명제를 주장했다",
                     ("Person", "School"), ("Proposition", "Argument"), inverse="proposed_by"),
        RelationType("held_by", CAT_AUTHORSHIP, "해석 주체", "해석을 제시한 학자·출처",
                     ("Interpretation",), ("Person", "Source")),
        # --- content
        RelationType("contains", CAT_CONTENT, "포함", "저작이 명제·논증을 포함한다",
                     ("Work",), ("Proposition", "Argument"), inverse="contained_in"),
        RelationType("discusses", CAT_CONTENT, "다룸", "저작이 개념·인물을 다룬다",
                     ("Work",), ("Concept", "Person", "Work", "Event")),
        RelationType("defines", CAT_CONTENT, "정의", "저작·인물·학파가 개념을 정의/도입했다",
                     ("Work", "Person", "School", "Movement"), ("Concept",)),
        RelationType("about", CAT_CONTENT, "관련 개념", "명제가 다루는 개념",
                     ("Proposition", "Argument", "Interpretation"), ("Concept",)),
        RelationType("interprets", CAT_CONTENT, "해석 대상", "해석이 대상으로 삼는 명제/저작/인물",
                     ("Interpretation",), INTELLECTUAL),
        # --- influence (causal, evidence required)
        RelationType("influenced", CAT_INFLUENCE, "영향", "source 가 target 에 역사적으로 영향을 주었다",
                     INTELLECTUAL + ("Event",), INTELLECTUAL + ("Event",),
                     inverse="influenced_by", requires_evidence=True, temporal_order=True),
        RelationType("student_of", CAT_INFLUENCE, "사사", "직접 배운 관계 (target 이 스승)",
                     ("Person",), ("Person",), inverse="teacher_of", requires_evidence=True),
        RelationType("responds_to", CAT_INFLUENCE, "응답", "명시적으로 응답·대화했다",
                     INTELLECTUAL, INTELLECTUAL, requires_evidence=True),
        # --- succession (causal)
        RelationType("adopted", CAT_SUCCESSION, "수용", "개념·명제를 받아들였다",
                     AGENTS + ("Concept",), IDEAS, requires_evidence=True),
        RelationType("extended", CAT_SUCCESSION, "확장", "기존 사상을 확장했다",
                     AGENTS + ("Concept", "Proposition"), IDEAS, requires_evidence=True),
        RelationType("modified", CAT_SUCCESSION, "변형", "기존 사상을 수정했다",
                     AGENTS + ("Concept", "Proposition"), IDEAS, requires_evidence=True),
        RelationType("reinterpreted", CAT_SUCCESSION, "재해석", "다른 틀에서 재해석했다",
                     AGENTS + ("Concept",), IDEAS, requires_evidence=True),
        RelationType("transformed_into", CAT_SUCCESSION, "변형되어 이어짐", "개념이 다른 개념으로 변형되었다",
                     ("Concept",), ("Concept",), requires_evidence=True, temporal_order=True),
        # --- critique (causal, oppositional)
        RelationType("criticized", CAT_CRITIQUE, "비판", "명시적으로 비판했다",
                     INTELLECTUAL, INTELLECTUAL, requires_evidence=True),
        RelationType("rejected", CAT_CRITIQUE, "거부", "받아들이지 않았다",
                     INTELLECTUAL, IDEAS, requires_evidence=True),
        RelationType("refuted", CAT_CRITIQUE, "논박", "논박을 시도했다",
                     INTELLECTUAL, IDEAS, requires_evidence=True),
        RelationType("challenged", CAT_CRITIQUE, "도전", "문제를 제기했다",
                     INTELLECTUAL, IDEAS, requires_evidence=True),
        # --- conceptual (logical)
        RelationType("depends_on", CAT_CONCEPTUAL, "의존", "개념이 다른 개념에 의존한다",
                     IDEAS, IDEAS),
        RelationType("presupposes", CAT_CONCEPTUAL, "전제", "논리적으로 전제한다",
                     IDEAS, IDEAS),
        RelationType("supports", CAT_CONCEPTUAL, "지지", "명제가 다른 명제를 지지한다",
                     ("Proposition", "Argument"), ("Proposition", "Argument")),
        RelationType("contradicted_by", CAT_CONCEPTUAL, "모순", "명제가 다른 명제와 양립 불가능하다",
                     ("Proposition",), ("Proposition",), symmetric=True),
        # --- similarity (NON-causal)
        RelationType("similar_to", CAT_SIMILARITY, "유사", "구조적으로 유사하다 (영향을 함의하지 않음)",
                     INTELLECTUAL, INTELLECTUAL, symmetric=True),
        RelationType("analogous_to", CAT_SIMILARITY, "유비", "다른 분야에서 유비적 구조를 가진다",
                     INTELLECTUAL, INTELLECTUAL, symmetric=True),
        # --- opposition (NON-causal)
        RelationType("contrasts_with", CAT_OPPOSITION, "대조", "개념적으로 대조된다",
                     IDEAS, IDEAS, symmetric=True),
        RelationType("opposed_to", CAT_OPPOSITION, "대립", "근본적 논쟁 축의 반대편에 있다",
                     IDEAS, IDEAS, symmetric=True),
        # --- taxonomy
        RelationType("subclass_of", CAT_TAXONOMY, "하위개념", "개념/분야의 하위 분류",
                     ("Concept", "Domain", "School", "Movement"), ("Concept", "Domain", "School", "Movement")),
        RelationType("member_of", CAT_TAXONOMY, "소속", "인물이 학파·사조에 속한다",
                     ("Person",), ("School", "Movement")),
        RelationType("belongs_to_domain", CAT_TAXONOMY, "분야", "개념·저작이 속한 분야",
                     IDEAS + ("Person",), ("Domain",)),
        RelationType("affiliated_with", CAT_TAXONOMY, "소속 기관", "인물이 기관에 소속되었다",
                     ("Person",), ("Institution",)),
        # --- historical
        RelationType("preceded", CAT_HISTORICAL, "선행", "시간적으로 앞선다",
                     (ANY,), (ANY,), inverse="followed"),
        RelationType("contemporary_with", CAT_HISTORICAL, "동시대", "동시대에 활동했다",
                     ("Person",), ("Person",), symmetric=True),
        RelationType("active_in", CAT_HISTORICAL, "활동 시대", "인물·저작의 시대",
                     ("Person", "Work", "School", "Movement", "Event"), ("Era",)),
        RelationType("contextualized_by", CAT_HISTORICAL, "역사적 맥락", "사건·조건 속에서 나왔다",
                     INTELLECTUAL, ("Event", "Era", "Institution")),
        RelationType("interdisciplinary_connection", CAT_HISTORICAL, "학제 연결",
                     "서로 다른 분야를 잇는 연결", INTELLECTUAL + ("Domain",), INTELLECTUAL + ("Domain",),
                     symmetric=True),
        # --- evidence
        RelationType("derived_from", CAT_EVIDENCE, "유래", "다른 원천에서 유래했다",
                     IDEAS, IDEAS + ("Source",), requires_evidence=True),
        RelationType("documented_by", CAT_EVIDENCE, "기록", "출처에 기록되어 있다",
                     (ANY,), ("Source", "Work")),
        RelationType("quoted_in", CAT_EVIDENCE, "인용", "다른 저작에서 인용되었다",
                     ("Proposition", "Work"), ("Work", "Source")),
        # --- argument structure
        RelationType("premise_of", CAT_ARGUMENT, "전제", "명제가 논증의 전제이다",
                     ("Proposition",), ("Argument",)),
        RelationType("concludes", CAT_ARGUMENT, "결론", "논증이 명제를 결론으로 한다",
                     ("Argument",), ("Proposition",)),
    ]
}

# ---------------------------------------------------------------------------
# Evidence & epistemic status
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceTier:
    tier: int
    name: str
    label_ko: str
    weight: float


EVIDENCE_TIERS: dict[int, EvidenceTier] = {
    1: EvidenceTier(1, "primary_source", "원전 (책·논문·편지·강연·직접 기록)", 0.90),
    2: EvidenceTier(2, "direct_testimony", "영향에 대한 당사자/동시대인의 직접 기록", 0.80),
    3: EvidenceTier(3, "scholarly_research", "전문 학자의 연구", 0.65),
    4: EvidenceTier(4, "academic_encyclopedia", "학술 백과사전", 0.50),
    5: EvidenceTier(5, "popular_secondary", "대중적 2차 자료", 0.30),
    6: EvidenceTier(6, "ai_inference", "AI 가 추론한 연결", 0.15),
}

# 관계 자체의 증거 성격
EVIDENCE_STATUS = {
    "direct": ("직접", 1.00),      # 당사자가 명시적으로 언급
    "indirect": ("간접", 0.85),    # 매개자를 통하거나 암묵적
    "disputed": ("논쟁 중", 0.60),  # 학계에서 다툼이 있음
    "inferred": ("추론", 0.50),    # 정황상 추론
}

# 관계의 인식론적 생애주기
EPISTEMIC_STATUS = {
    "hypothesis": "가설 — AI/자동 추론으로 제안됨, 검증 전",
    "proposed": "제안 — 사람이 등록했으나 검토 전",
    "accepted": "승인 — 검증된 지식",
    "contested": "이의 제기 — 반대 증거가 제출됨",
    "revised": "수정 — 새 증거에 따라 내용이 변경됨",
    "rejected": "기각 — 증거 부족 또는 반증",
}

# 허용되는 상태 전이 (검증 워크플로)
STATUS_TRANSITIONS = {
    "hypothesis": {"proposed", "accepted", "rejected"},
    "proposed": {"accepted", "rejected", "contested"},
    "accepted": {"contested", "revised", "rejected"},
    "contested": {"accepted", "revised", "rejected"},
    "revised": {"accepted", "contested", "rejected"},
    "rejected": {"proposed", "hypothesis"},
}

ORIGINS = {"seed", "human", "extraction", "ai", "import"}

# 경로 해석 결과 분류 (reasoning 에서 사용)
CONNECTION_KINDS = {
    "DIRECT_INFLUENCE": "직접 영향 — 증거가 있는 단일 인과 관계",
    "INDIRECT_INFLUENCE": "간접 영향 — 인과 관계의 사슬",
    "CONCEPTUAL_CONTINUITY": "개념적 연속성 — 개념 계보를 통한 연결",
    "CRITICAL_ENGAGEMENT": "비판적 관여 — 비판·반론을 통한 연결",
    "STRUCTURAL_SIMILARITY": "구조적 유사성 — 영향이 아닌 유사성",
    "CONCEPTUAL_OPPOSITION": "개념적 대립 — 논쟁 축의 반대편",
    "SHARED_PROBLEM": "공통 문제의식 — 같은 개념·문제를 다루지만 영향 관계는 아님",
    "HISTORICAL_CO_OCCURRENCE": "역사적 공존 — 같은 시대·맥락",
}


def relation(name: str) -> RelationType:
    try:
        return RELATION_TYPES[name]
    except KeyError as exc:
        raise KeyError(f"unknown relation: {name}") from exc


def is_causal(predicate: str) -> bool:
    return relation(predicate).category in CAUSAL_CATEGORIES


def schema_as_dict() -> dict:
    """UI·문서·export 용 스키마 직렬화."""
    return {
        "version": SCHEMA_VERSION,
        "entity_types": [
            {"name": t.name, "prefix": t.prefix, "label_ko": t.label_ko,
             "description": t.description, "properties": list(t.properties)}
            for t in ENTITY_TYPES.values()
        ],
        "relation_types": [
            {"name": r.name, "category": r.category, "label_ko": r.label_ko,
             "description": r.description, "domain": list(r.domain), "range": list(r.range),
             "inverse": r.inverse, "symmetric": r.symmetric,
             "requires_evidence": r.requires_evidence, "temporal_order": r.temporal_order}
            for r in RELATION_TYPES.values()
        ],
        "evidence_tiers": [
            {"tier": t.tier, "name": t.name, "label_ko": t.label_ko, "weight": t.weight}
            for t in EVIDENCE_TIERS.values()
        ],
        "evidence_status": {k: {"label_ko": v[0], "factor": v[1]} for k, v in EVIDENCE_STATUS.items()},
        "epistemic_status": EPISTEMIC_STATUS,
        "status_transitions": {k: sorted(v) for k, v in STATUS_TRANSITIONS.items()},
        "connection_kinds": CONNECTION_KINDS,
        "categories": {
            "causal": sorted(CAUSAL_CATEGORIES),
            "non_causal": sorted(NON_CAUSAL_CATEGORIES),
        },
    }


@dataclass
class ValidationIssue:
    level: str  # "error" | "warning"
    code: str
    message: str
    ref: str | None = None

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "ref": self.ref}


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def error(self, code: str, message: str, ref: str | None = None) -> None:
        self.issues.append(ValidationIssue("error", code, message, ref))

    def warn(self, code: str, message: str, ref: str | None = None) -> None:
        self.issues.append(ValidationIssue("warning", code, message, ref))

    def as_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.as_dict() for i in self.issues]}
