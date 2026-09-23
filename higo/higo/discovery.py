"""Discovery Engine — 그래프에 없는 연결 '후보'를 찾는다.

발견된 것은 절대 사실로 저장되지 않는다. commit=True 일 때만 origin='ai',
epistemic_status='hypothesis', Tier 6 증거를 가진 Hypothesis Edge 로 기록되며,
사람의 검증(Reviewer)을 통과해야 승인된다.

발견 유형
  semantic_similarity   서로 다른 사상가의 명제 사이 의미적 유사성 (→ similar_to 가설)
  transitive_influence  A→B→C 인과 사슬이 있으나 A→C 기록이 없음 (→ 간접 영향으로만 보고)
  concept_cooccurrence  같은 명제들에 반복해서 함께 등장하는 개념 쌍 (→ depends_on 가설)
  cross_domain_bridge   여러 분야의 명제에 걸쳐 쓰이는 개념 (→ interdisciplinary_connection)
  latent_contradiction  서로 비판하는 사상가들이 같은 개념에 대해 낸 명제 (→ contradicted_by 가설)
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from . import ontology as O
from .graph import DEFAULT_STATUSES, GraphIndex
from .reasoning import Reasoner, flow_of
from .store import Store
from .vector import VectorIndex


class DiscoveryEngine:
    def __init__(self, store: Store, graph: GraphIndex, vectors: VectorIndex):
        self.store = store
        self.g = graph
        self.v = vectors
        self.r = Reasoner(graph)

    def _connected(self, a: str, b: str, predicates: set[str] | None = None) -> bool:
        for e in self.g.edges_of(a, statuses=None):
            if self.g.other(e, a) == b and (predicates is None or e["predicate"] in predicates):
                return True
        return False

    def semantic_similarity(self, threshold: float = 0.22, limit: int = 30) -> list[dict]:
        g = self.g.refresh()
        out = []
        seen = set()
        for p in g.of_type("Proposition"):
            authors = set(g.sources(p["id"], "proposes"))
            for q, score in self.v.similar(p["id"], k=6, types=["Proposition"], min_score=threshold):
                key = tuple(sorted((p["id"], q)))
                if key in seen:
                    continue
                seen.add(key)
                q_authors = set(g.sources(q, "proposes"))
                if authors & q_authors or self._connected(p["id"], q):
                    continue
                shared = set(g.targets(p["id"], "about")) & set(g.targets(q, "about"))
                out.append({
                    "type": "semantic_similarity", "score": round(score, 3),
                    "source": key[0], "target": key[1], "predicate": "similar_to",
                    "source_label": g.label(key[0]), "target_label": g.label(key[1]),
                    "authors": [g.label(a) for a in authors | q_authors],
                    "rationale": ("두 명제가 의미적으로 유사함 (TF-IDF cosine "
                                  f"{score:.2f})" + (f"; 공유 개념: {', '.join(g.label(c) for c in shared)}"
                                                     if shared else "") +
                                  " — 영향이 아닌 구조적 유사성 가설"),
                })
        out.sort(key=lambda x: -x["score"])
        return out[:limit]

    def transitive_influence(self, limit: int = 30) -> list[dict]:
        g = self.g.refresh()
        flows: dict[str, list[tuple[str, dict]]] = {}
        for e in g.edges.values():
            if e["epistemic_status"] not in DEFAULT_STATUSES:
                continue
            if O.RELATION_TYPES[e["predicate"]].category not in (O.CAT_INFLUENCE,):
                continue
            f = flow_of(e)
            if f and g.nodes[f[0]]["type"] == "Person" and g.nodes[f[1]]["type"] == "Person":
                flows.setdefault(f[0], []).append((f[1], e))
        out = []
        for a, nexts in flows.items():
            for b, e1 in nexts:
                for c, e2 in flows.get(b, []):
                    if c == a or self._connected(a, c):
                        continue
                    score = e1["confidence"] * e2["confidence"] * 0.8
                    out.append({"type": "transitive_influence", "score": round(score, 3),
                                "source": a, "target": c, "via": b, "predicate": "influenced",
                                "source_label": g.label(a), "target_label": g.label(c), "via_label": g.label(b),
                                "rationale": f"{g.label(a)} → {g.label(b)} → {g.label(c)} 사슬. "
                                             "직접 영향의 증거는 없으므로 '간접 영향'으로만 보고함.",
                                "commit_as": "report_only"})
        out.sort(key=lambda x: -x["score"])
        return out[:limit]

    def concept_cooccurrence(self, min_count: int = 2, limit: int = 30) -> list[dict]:
        g = self.g.refresh()
        pairs: Counter = Counter()
        for p in g.of_type("Proposition"):
            cs = sorted(set(g.targets(p["id"], "about")))
            for a, b in combinations(cs, 2):
                pairs[(a, b)] += 1
        out = []
        for (a, b), n in pairs.most_common():
            if n < min_count:
                break
            if self._connected(a, b):
                continue
            out.append({"type": "concept_cooccurrence", "score": round(min(1.0, n / 5), 3),
                        "source": a, "target": b, "predicate": "depends_on",
                        "source_label": g.label(a), "target_label": g.label(b),
                        "rationale": f"{n}개의 명제에서 함께 다뤄지지만 두 개념 사이 관계가 정의되지 않음"})
        return out[:limit]

    def cross_domain_bridges(self, limit: int = 20) -> list[dict]:
        g = self.g.refresh()
        out = []
        for c in g.of_type("Concept"):
            own = {g.top_domain(d) for d in g.targets(c["id"], "belongs_to_domain")}
            used = Counter()
            for p in g.sources(c["id"], "about"):
                for c2 in g.targets(p, "about"):
                    for d in g.targets(c2, "belongs_to_domain"):
                        used[g.top_domain(d)] += 1
            foreign = {d: n for d, n in used.items() if d not in own}
            if own and foreign:
                d, n = max(foreign.items(), key=lambda x: x[1])
                if self._connected(c["id"], d):
                    continue
                out.append({"type": "cross_domain_bridge", "score": round(min(1.0, n / 4), 3),
                            "source": c["id"], "target": d, "predicate": "interdisciplinary_connection",
                            "source_label": g.label(c["id"]), "target_label": g.label(d),
                            "rationale": f"'{g.label(c['id'])}' 개념이 {g.label(d)} 분야 명제 {n}건에서 함께 쓰임"})
        out.sort(key=lambda x: -x["score"])
        return out[:limit]

    def latent_contradictions(self, limit: int = 20) -> list[dict]:
        g = self.g.refresh()
        out = []
        for e in g.edges.values():
            if O.RELATION_TYPES[e["predicate"]].category != O.CAT_CRITIQUE or e["epistemic_status"] not in DEFAULT_STATUSES:
                continue
            a, b = e["source"], e["target"]
            if g.nodes[a]["type"] != "Person" or g.nodes[b]["type"] != "Person":
                continue
            pa = {c: p for p in g.targets(a, "proposes") for c in g.targets(p, "about")}
            pb = {c: p for p in g.targets(b, "proposes") for c in g.targets(p, "about")}
            for c in set(pa) & set(pb):
                if pa[c] == pb[c] or self._connected(pa[c], pb[c]):
                    continue
                out.append({"type": "latent_contradiction", "score": round(0.5 * e["confidence"], 3),
                            "source": pa[c], "target": pb[c], "predicate": "contradicted_by",
                            "source_label": g.label(pa[c]), "target_label": g.label(pb[c]),
                            "rationale": f"{g.label(a)} 는 {g.label(b)} 를 비판했고 ({e['id']}), 두 사람 모두 "
                                         f"'{g.label(c)}' 에 대한 명제를 남김"})
        out.sort(key=lambda x: -x["score"])
        return out[:limit]

    def run(self, commit: bool = False, actor: str = "ai:discovery") -> dict:
        results = {
            "semantic_similarity": self.semantic_similarity(),
            "transitive_influence": self.transitive_influence(),
            "concept_cooccurrence": self.concept_cooccurrence(),
            "cross_domain_bridge": self.cross_domain_bridges(),
            "latent_contradiction": self.latent_contradictions(),
        }
        committed = []
        if commit:
            for kind, items in results.items():
                for it in items:
                    if it.get("commit_as") == "report_only":
                        continue
                    committed.append(self.commit(it, actor=actor)["id"])
        return {"results": results, "committed": committed,
                "counts": {k: len(v) for k, v in results.items()}}

    def commit(self, item: dict, actor: str = "ai:discovery") -> dict:
        """발견 결과를 Hypothesis Edge 로 기록한다 (Tier 6 = AI 추론 증거)."""
        if item.get("commit_as") == "report_only":
            raise ValueError("이 발견은 보고 전용이다 (간접 영향은 직접 영향 관계로 저장하지 않음)")
        edge = self.store.add_edge(item["source"], item["predicate"], item["target"], origin="ai",
                                   evidence_status="inferred", epistemic_status="hypothesis",
                                   note=f"discovery:{item['type']}", actor=actor)
        if not self.store.list_evidence(edge["id"]):
            self.store.add_evidence(edge["id"], tier=6, citation=f"HIGO discovery engine ({item['type']})",
                                    interpretation=item.get("rationale", ""), added_by=actor)
        return self.store.get_edge(edge["id"], with_evidence=True)  # type: ignore[return-value]
