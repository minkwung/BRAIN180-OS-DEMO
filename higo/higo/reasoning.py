"""Reasoning Engine — 계보·연결 해석·개념 계보·대립 구조·학제 연결·사상 DNA·비교.

핵심 원칙: 두 노드 사이의 '연결'을 하나의 영향 주장으로 뭉뚱그리지 않는다.
경로를 이루는 관계의 범주와 지적 흐름의 방향을 보고 다음으로 분류한다.

    DIRECT_INFLUENCE / INDIRECT_INFLUENCE / CONCEPTUAL_CONTINUITY /
    CRITICAL_ENGAGEMENT / STRUCTURAL_SIMILARITY / CONCEPTUAL_OPPOSITION /
    SHARED_PROBLEM / HISTORICAL_CO_OCCURRENCE
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from typing import Iterable

from . import ontology as O
from .graph import DEFAULT_STATUSES, GraphIndex

# 지적 흐름(flow)의 방향: 관계가 주어졌을 때 사상이 어디에서 어디로 흘렀는가.
#   "forward"  = source → target
#   "backward" = target → source
FLOW = {
    "influenced": "forward",
    "transformed_into": "forward",
    "student_of": "backward",       # A student_of B  ⇒  B → A
    "responds_to": "backward",      # A responds_to B ⇒  B → A
    "adopted": "backward",          # A adopted X     ⇒  X → A
    "extended": "backward",
    "modified": "backward",
    "reinterpreted": "backward",
    "criticized": "backward",       # A criticized B  ⇒  B 의 사상이 A 에게 도달
    "rejected": "backward",
    "refuted": "backward",
    "challenged": "backward",
    "derived_from": "backward",
    "authored": "forward",
    "proposes": "forward",
    "contains": "forward",
    "defines": "forward",
}
# 경로 탐색에서 매개 노드로 쓰지 않는 타입(시대·분야는 거의 모든 것을 잇기 때문)
HUB_TYPES = {"Era", "Domain", "Source", "Institution"}
SKIP_PREDICATES = {"belongs_to_domain", "active_in", "contemporary_with", "documented_by",
                   "affiliated_with", "preceded", "held_by", "interprets", "quoted_in"}


def flow_of(edge: dict) -> tuple[str, str] | None:
    d = FLOW.get(edge["predicate"])
    if d == "forward":
        return edge["source"], edge["target"]
    if d == "backward":
        return edge["target"], edge["source"]
    return None


class Reasoner:
    def __init__(self, graph: GraphIndex):
        self.g = graph

    # ================================================================ paths
    def _walk_edges(self, nid: str, statuses) -> list[dict]:
        return [e for e in self.g.edges_of(nid, statuses=statuses) if e["predicate"] not in SKIP_PREDICATES]

    def find_paths(self, a: str, b: str, *, max_depth: int = 5, max_paths: int = 30,
                   statuses=DEFAULT_STATUSES, max_expansions: int = 60000) -> list[list[tuple[dict, str, str]]]:
        """a→b 단순 경로를 짧은 순으로 찾는다. 각 스텝은 (edge, from, to)."""
        g = self.g.refresh()
        if a not in g.nodes or b not in g.nodes:
            return []
        results: list[list[tuple[dict, str, str]]] = []
        queue: deque[tuple[str, list[tuple[dict, str, str]], frozenset]] = deque([(a, [], frozenset([a]))])
        expansions = 0
        while queue and len(results) < max_paths and expansions < max_expansions:
            node, path, visited = queue.popleft()
            if len(path) >= max_depth:
                continue
            for e in self._walk_edges(node, statuses):
                expansions += 1
                nxt = g.other(e, node)
                if nxt in visited:
                    continue
                if nxt != b and g.nodes[nxt]["type"] in HUB_TYPES:
                    continue
                step = path + [(e, node, nxt)]
                if nxt == b:
                    results.append(step)
                else:
                    queue.append((nxt, step, visited | {nxt}))
        return results

    def classify_path(self, path: list[tuple[dict, str, str]]) -> dict:
        cats = [O.RELATION_TYPES[e["predicate"]].category for e, _, _ in path]
        flows = []
        for e, frm, to in path:
            f = flow_of(e)
            flows.append(None if f is None else (f == (frm, to)))
        strength = 1.0
        for e, _, _ in path:
            rel = O.RELATION_TYPES[e["predicate"]]
            strength *= e["confidence"] if rel.requires_evidence or e["confidence"] > 0 else 1.0
        # 경로가 길수록 약해진다
        strength *= 0.9 ** max(0, len(path) - 1)
        mid_types = {self.g.nodes[to]["type"] for _, _, to in path[:-1]}
        if O.CAT_SIMILARITY in cats:
            kind = "STRUCTURAL_SIMILARITY"
        elif O.CAT_OPPOSITION in cats:
            kind = "CONCEPTUAL_OPPOSITION"
        elif all(f is True for f in flows):
            causal = [c for c in cats if c in O.CAUSAL_CATEGORIES]
            if len(path) == 1 and cats[0] == O.CAT_INFLUENCE:
                kind = "DIRECT_INFLUENCE" if path[0][0]["evidence_status"] == "direct" else "INDIRECT_INFLUENCE"
            elif O.CAT_CRITIQUE in causal:
                kind = "CRITICAL_ENGAGEMENT"
            elif mid_types & {"Concept", "Proposition"} or O.CAT_SUCCESSION in cats:
                kind = "CONCEPTUAL_CONTINUITY"
            elif causal:
                kind = "INDIRECT_INFLUENCE"
            else:
                kind = "CONCEPTUAL_CONTINUITY"
        elif all(f is False for f in flows) and any(c in O.CAUSAL_CATEGORIES for c in cats):
            kind = "REVERSE"
        else:
            kind = "SHARED_PROBLEM"
        return {
            "kind": kind,
            "strength": round(strength, 4),
            "steps": [
                {"edge_id": e["id"], "from": frm, "to": to, "from_label": self.g.label(frm),
                 "to_label": self.g.label(to), "predicate": e["predicate"],
                 "predicate_ko": O.RELATION_TYPES[e["predicate"]].label_ko,
                 "forward": e["source"] == frm, "confidence": e["confidence"],
                 "evidence_status": e["evidence_status"], "epistemic_status": e["epistemic_status"]}
                for e, frm, to in path
            ],
        }

    def co_occurrence(self, a: str, b: str) -> list[dict]:
        g = self.g
        out = []
        na, nb = g.nodes.get(a, {}), g.nodes.get(b, {})
        sa, ea, sb, eb = na.get("start_year"), na.get("end_year"), nb.get("start_year"), nb.get("end_year")
        if None not in (sa, ea, sb, eb) and sa <= eb and sb <= ea:
            out.append({"reason": "생애/활동 기간이 겹침", "overlap": [max(sa, sb), min(ea, eb)]})
        for pred, label in (("active_in", "같은 시대"), ("affiliated_with", "같은 기관"),
                            ("member_of", "같은 학파/사조"), ("contextualized_by", "같은 역사적 맥락")):
            shared = set(g.targets(a, pred)) & set(g.targets(b, pred))
            for s in shared:
                out.append({"reason": label, "node": s, "label": g.label(s)})
        return out

    def explain_connection(self, a: str, b: str, *, max_depth: int = 5,
                           include_hypotheses: bool = False) -> dict:
        g = self.g.refresh()
        if a not in g.nodes or b not in g.nodes:
            raise KeyError("unknown node")
        # 이른 쪽을 출발점으로 삼는다
        ya, yb = g.year(a), g.year(b)
        if ya is not None and yb is not None and yb < ya:
            a, b = b, a
        statuses = DEFAULT_STATUSES + (("hypothesis",) if include_hypotheses else ())
        paths = self.find_paths(a, b, max_depth=max_depth, statuses=statuses)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for p in paths:
            c = self.classify_path(p)
            # 유사성·대립을 거치는 긴 경로는 우연한 연결일 가능성이 커서 버린다
            if c["kind"] in ("STRUCTURAL_SIMILARITY", "CONCEPTUAL_OPPOSITION") and len(p) > 4:
                continue
            if c["kind"] == "STRUCTURAL_SIMILARITY" and any(
                    O.RELATION_TYPES[s["predicate"]].category in O.CAUSAL_CATEGORIES for s in c["steps"]):
                continue
            grouped[c["kind"]].append(c)
        for k in grouped:
            grouped[k].sort(key=lambda c: (-c["strength"], len(c["steps"])))
            grouped[k] = grouped[k][:5]
        co = self.co_occurrence(a, b)
        if co:
            grouped["HISTORICAL_CO_OCCURRENCE"] = [{"kind": "HISTORICAL_CO_OCCURRENCE", "strength": 0.3,
                                                    "facts": co, "steps": []}]
        order = ["DIRECT_INFLUENCE", "INDIRECT_INFLUENCE", "CONCEPTUAL_CONTINUITY", "CRITICAL_ENGAGEMENT",
                 "SHARED_PROBLEM", "STRUCTURAL_SIMILARITY", "CONCEPTUAL_OPPOSITION",
                 "HISTORICAL_CO_OCCURRENCE", "REVERSE"]
        summary = []
        for k in order:
            if grouped.get(k):
                best = grouped[k][0]
                summary.append({"kind": k, "label_ko": O.CONNECTION_KINDS.get(k, "역방향 흐름"),
                                "count": len(grouped[k]), "best_strength": best["strength"]})
        edge_ids = {s["edge_id"] for k in grouped for c in grouped[k] for s in c.get("steps", [])}
        node_ids = {a, b} | {s[x] for k in grouped for c in grouped[k] for s in c.get("steps", [])
                             for x in ("from", "to")}
        verdict = self._verdict(summary)
        return {"from": a, "to": b, "from_label": g.label(a), "to_label": g.label(b),
                "summary": summary, "verdict": verdict,
                "connections": {k: grouped[k] for k in order if grouped.get(k)},
                "graph": g.to_view(node_ids, edge_ids)}

    @staticmethod
    def _verdict(summary: list[dict]) -> str:
        kinds = {s["kind"]: s for s in summary}
        if "DIRECT_INFLUENCE" in kinds:
            return "증거가 있는 직접 영향 관계가 존재한다."
        if "INDIRECT_INFLUENCE" in kinds or "CONCEPTUAL_CONTINUITY" in kinds:
            return ("직접 영향의 증거는 없지만, 매개자나 개념 계보를 통한 간접적 연속성이 있다. "
                    "'A가 B에게 영향을 주었다'고 단정해서는 안 된다.")
        if "CRITICAL_ENGAGEMENT" in kinds:
            return "비판·반론을 통한 관여가 있다 — 영향은 수용이 아니라 대결의 형태로 전달되었다."
        if "SHARED_PROBLEM" in kinds or "STRUCTURAL_SIMILARITY" in kinds:
            return "공통 문제의식 또는 구조적 유사성이 있으나, 이는 영향 관계를 함의하지 않는다."
        if "HISTORICAL_CO_OCCURRENCE" in kinds:
            return "같은 시대·맥락에 있었다는 사실 외에 그래프상 지적 연결은 확인되지 않는다."
        return "그래프 안에서 의미 있는 연결을 찾지 못했다."

    # =========================================================== genealogy
    def concept_family(self, concept_id: str) -> dict[str, str]:
        """개념 + 하위개념 + 변형 계열. {concept_id: relation_to_root}"""
        g = self.g.refresh()
        fam = {concept_id: "root"}
        queue = deque([concept_id])
        while queue:
            c = queue.popleft()
            for sub in g.sources(c, "subclass_of"):
                if sub not in fam and g.nodes[sub]["type"] == "Concept":
                    fam[sub] = "subclass"
                    queue.append(sub)
            for e in g.edges_of(c, predicates=["transformed_into"]):
                o = g.other(e, c)
                if o not in fam:
                    fam[o] = "transformation"
                    queue.append(o)
        return fam

    def concept_genealogy(self, concept_id: str) -> dict:
        g = self.g.refresh()
        if concept_id not in g.nodes:
            raise KeyError(concept_id)
        fam = self.concept_family(concept_id)
        entries = []
        persons: set[str] = set()
        seen_props: set[tuple] = set()
        for c in fam:
            for p in g.sources(c, "about"):
                authors = g.sources(p, "proposes")
                works = g.sources(p, "contains")
                props = g.nodes[p].get("props") or {}
                for a in authors or [None]:
                    if (p, a) in seen_props:
                        continue
                    seen_props.add((p, a))
                    if a:
                        persons.add(a)
                    entries.append({
                        "year": props.get("year") or (g.year(works[0]) if works else None) or (g.floruit(a) if a else None),
                        "kind": "proposition", "concept": c, "concept_label": g.label(c),
                        "person": a, "person_label": g.label(a) if a else None,
                        "work": works[0] if works else None, "work_label": g.label(works[0]) if works else None,
                        "proposition": p, "statement": props.get("statement") or g.nodes[p]["label"],
                        "locator": props.get("locator"),
                    })
            for e in g.edges_of(c, direction="in"):
                if e["predicate"] in ("adopted", "extended", "modified", "reinterpreted", "criticized",
                                      "rejected", "defines", "discusses") and \
                        g.nodes[e["source"]]["type"] in ("Person", "Work", "School", "Movement"):
                    src = e["source"]
                    stype = g.nodes[src]["type"]
                    if stype == "Work":
                        person = (g.sources(src, "authored") or [None])[0]
                    else:
                        person = src
                    if person and g.nodes[person]["type"] == "Person":
                        persons.add(person)
                    entries.append({
                        "year": g.year(src) if stype == "Work" else g.floruit(src), "kind": e["predicate"],
                        "relation_ko": O.RELATION_TYPES[e["predicate"]].label_ko,
                        "concept": c, "concept_label": g.label(c), "person": person,
                        "person_label": g.label(person) if person else None,
                        "work": src if stype == "Work" else None,
                        "work_label": g.label(src) if stype == "Work" else None,
                        "edge_id": e["id"], "confidence": e["confidence"],
                    })
        entries.sort(key=lambda x: (x["year"] if x["year"] is not None else 99999))
        # 타임라인에 등장한 인물 사이의 인과 관계 = 계보의 뼈대
        lineage = []
        for p in persons:
            for e in g.edges_of(p, direction="out"):
                if e["target"] in persons and O.RELATION_TYPES[e["predicate"]].category in O.CAUSAL_CATEGORIES:
                    f = flow_of(e)
                    if f:
                        lineage.append({"edge_id": e["id"], "from": f[0], "to": f[1], "from_label": g.label(f[0]),
                                        "to_label": g.label(f[1]), "predicate": e["predicate"],
                                        "predicate_ko": O.RELATION_TYPES[e["predicate"]].label_ko,
                                        "confidence": e["confidence"]})
        transformations = []
        for c in fam:
            for e in g.edges_of(c, direction="out"):
                if e["predicate"] in ("transformed_into", "subclass_of", "opposed_to", "contrasts_with",
                                      "depends_on", "presupposes") and g.nodes[e["target"]]["type"] == "Concept":
                    transformations.append({"edge_id": e["id"], "from": e["source"], "to": e["target"],
                                            "from_label": g.label(e["source"]), "to_label": g.label(e["target"]),
                                            "predicate": e["predicate"],
                                            "predicate_ko": O.RELATION_TYPES[e["predicate"]].label_ko})
        eras = defaultdict(list)
        for en in entries:
            eras[self.era_of_year(en["year"])].append(en)
        return {"concept": concept_id, "label": g.label(concept_id),
                "family": [{"id": c, "label": g.label(c), "relation": r} for c, r in fam.items()],
                "timeline": entries, "by_era": [{"era": k, "entries": v} for k, v in eras.items()],
                "lineage": lineage, "transformations": transformations,
                "graph": g.subgraph(list(fam) + list(persons), depth=0)}

    def era_of_year(self, year: int | None) -> str:
        if year is None:
            return "연대 미상"
        best = None
        for era in self.g.of_type("Era"):
            s, e = era.get("start_year"), era.get("end_year")
            if s is not None and e is not None and s <= year < e:
                if best is None or (e - s) < (best["end_year"] - best["start_year"]):
                    best = era
        return (best.get("label_ko") or best["label"]) if best else "기타"

    # ========================================================= contradictions
    def contradiction_graph(self) -> dict:
        g = self.g.refresh()
        axes = []
        seen = set()
        for e in g.edges.values():
            if e["predicate"] not in ("opposed_to", "contrasts_with") or e["epistemic_status"] not in DEFAULT_STATUSES:
                continue
            key = tuple(sorted((e["source"], e["target"])))
            if key in seen:
                continue
            seen.add(key)
            sides = []
            for c in key:
                fam = self.concept_family(c)
                people = Counter()
                for fc in fam:
                    for p in g.sources(fc, "about"):
                        for a in g.sources(p, "proposes"):
                            people[a] += 1
                    for ed in g.edges_of(fc, direction="in", predicates=["adopted", "extended", "defines"]):
                        if g.nodes[ed["source"]]["type"] == "Person":
                            people[ed["source"]] += 1
                    for ed in g.edges_of(fc, direction="in", predicates=["defines"]):
                        if g.nodes[ed["source"]]["type"] == "School":
                            for m in g.sources(ed["source"], "member_of"):
                                people[m] += 1
                sides.append({"concept": c, "label": g.label(c),
                              "thinkers": [{"id": p, "label": g.label(p), "weight": w} for p, w in people.most_common(12)]})
            left = {t["id"] for t in sides[0]["thinkers"]}
            right = {t["id"] for t in sides[1]["thinkers"]}
            clashes = []
            for x in left:
                for ed in g.edges_of(x, predicates=["criticized", "rejected", "refuted", "challenged"]):
                    o = g.other(ed, x)
                    if o in right:
                        clashes.append({"edge_id": ed["id"], "source": ed["source"], "target": ed["target"],
                                        "source_label": g.label(ed["source"]), "target_label": g.label(ed["target"]),
                                        "predicate": ed["predicate"]})
            axes.append({"edge_id": e["id"], "predicate": e["predicate"], "sides": sides, "clashes": clashes,
                         "weight": len(left) + len(right) + 2 * len(clashes)})
        axes.sort(key=lambda a: -a["weight"])
        prop_conflicts = []
        for e in g.edges.values():
            if e["predicate"] == "contradicted_by" and e["epistemic_status"] in DEFAULT_STATUSES + ("hypothesis",):
                prop_conflicts.append({
                    "edge_id": e["id"], "status": e["epistemic_status"],
                    "a": e["source"], "a_statement": g.label(e["source"]),
                    "a_author": [g.label(x) for x in g.sources(e["source"], "proposes")],
                    "b": e["target"], "b_statement": g.label(e["target"]),
                    "b_author": [g.label(x) for x in g.sources(e["target"], "proposes")],
                })
        critiques = [e for e in g.edges.values() if O.RELATION_TYPES[e["predicate"]].category == O.CAT_CRITIQUE
                     and e["epistemic_status"] in DEFAULT_STATUSES]
        node_ids = {x for e in critiques for x in (e["source"], e["target"])}
        for ax in axes:
            node_ids |= {s["concept"] for s in ax["sides"]}
        edge_ids = {e["id"] for e in critiques} | {a["edge_id"] for a in axes}
        return {"axes": axes, "proposition_conflicts": prop_conflicts,
                "graph": g.to_view(node_ids, edge_ids)}

    # ========================================================= cross-domain
    def cross_domain(self) -> dict:
        g = self.g.refresh()
        tops = {}

        def top_domains(nid):
            if nid not in tops:
                tops[nid] = {g.top_domain(d) for d in g.domains_of(nid)}
            return tops[nid]

        pairs: Counter = Counter()
        examples: dict[tuple, list] = defaultdict(list)
        for e in g.edges.values():
            if e["predicate"] in SKIP_PREDICATES or e["epistemic_status"] not in DEFAULT_STATUSES:
                continue
            if g.nodes[e["source"]]["type"] in HUB_TYPES or g.nodes[e["target"]]["type"] in HUB_TYPES:
                continue
            da, db = top_domains(e["source"]), top_domains(e["target"])
            if not da or not db or da & db:
                continue
            for x in da:
                for y in db:
                    key = tuple(sorted((x, y)))
                    pairs[key] += 1
                    if len(examples[key]) < 6:
                        examples[key].append({"edge_id": e["id"], "source_label": g.label(e["source"]),
                                              "target_label": g.label(e["target"]), "predicate": e["predicate"],
                                              "predicate_ko": O.RELATION_TYPES[e["predicate"]].label_ko})
        bridges = []
        for p in g.of_type("Person"):
            ds = set()
            for w in g.targets(p["id"], "authored"):
                ds |= top_domains(w)
            for pr in g.targets(p["id"], "proposes"):
                ds |= top_domains(pr)
            ds |= {g.top_domain(d) for d in g.targets(p["id"], "belongs_to_domain")}
            if len(ds) >= 2:
                bridges.append({"id": p["id"], "label": g.label(p["id"]), "domains": sorted(g.label(d) for d in ds),
                                "span": len(ds)})
        bridges.sort(key=lambda b: (-b["span"], b["label"]))
        return {
            "domain_pairs": [{"a": k[0], "b": k[1], "a_label": g.label(k[0]), "b_label": g.label(k[1]),
                              "count": n, "examples": examples[k]} for k, n in pairs.most_common()],
            "bridge_thinkers": bridges,
        }

    # ============================================================ thinker DNA
    def _person_evidence(self, pid: str) -> list[tuple[str, str, float]]:
        """(concept_id, via_label, weight) — 인물의 사상을 이루는 개념 분포의 원천."""
        g = self.g
        out = []
        for pr in g.targets(pid, "proposes"):
            for c in g.targets(pr, "about"):
                out.append((c, g.label(pr), 1.0))
        for e in g.edges_of(pid, direction="out"):
            t = e["target"]
            if g.nodes[t]["type"] != "Concept":
                continue
            w = {"defines": 1.0, "adopted": 0.8, "extended": 0.8, "modified": 0.6, "reinterpreted": 0.6,
                 "criticized": -0.6, "rejected": -0.8, "refuted": -0.8, "challenged": -0.4}.get(e["predicate"])
            if w is not None:
                out.append((t, f"{O.RELATION_TYPES[e['predicate']].label_ko}: {g.label(t)}", w))
        for w in g.targets(pid, "authored"):
            for c in g.targets(w, "discusses"):
                if g.nodes[c]["type"] == "Concept":
                    out.append((c, g.label(w), 0.4))
        for s in g.targets(pid, "member_of"):
            for c in g.targets(s, "defines"):
                out.append((c, f"학파: {g.label(s)}", 0.5))
        return out

    def thinker_vector(self, pid: str) -> tuple[dict[str, float], dict[str, list[str]]]:
        g = self.g.refresh()
        vec: dict[str, float] = defaultdict(float)
        why: dict[str, list[str]] = defaultdict(list)
        for c, via, w in self._person_evidence(pid):
            vec[c] += w
            why[c].append(via)
            # 상위 개념으로 절반 가중치 전파
            for parent in g.targets(c, "subclass_of"):
                if g.nodes[parent]["type"] == "Concept":
                    vec[parent] += 0.5 * w
                    why[parent].append(f"{via} (하위개념 {g.label(c)})")
            for d in g.targets(c, "belongs_to_domain"):
                for anc in g.domain_ancestors(d):
                    key = anc
                    vec[key] += abs(w) * (1.0 if anc == d else 0.5)
                    if len(why[key]) < 8:
                        why[key].append(via)
        return dict(vec), dict(why)

    def thinker_dna(self, pid: str) -> dict:
        g = self.g.refresh()
        if pid not in g.nodes:
            raise KeyError(pid)
        vec, why = self.thinker_vector(pid)
        domains, concepts = [], []
        for k, v in vec.items():
            item = {"id": k, "label": g.label(k), "score": round(v, 3), "because": why.get(k, [])[:6]}
            (domains if g.nodes[k]["type"] == "Domain" else concepts).append(item)
        dmax = max([d["score"] for d in domains] + [1e-9])
        for d in domains:
            d["normalized"] = round(d["score"] / dmax, 3)
            d["top"] = g.top_domain(d["id"]) == d["id"]
        domains.sort(key=lambda d: -d["score"])
        concepts.sort(key=lambda c: -abs(c["score"]))
        similar = self.similar_thinkers(pid, k=6)
        return {"id": pid, "label": g.label(pid), "domains": domains, "concepts": concepts[:25],
                "rejects": [c for c in concepts if c["score"] < 0][:10], "similar": similar}

    @staticmethod
    def _cos(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    def _concept_only(self, vec: dict[str, float]) -> dict[str, float]:
        return {k: v for k, v in vec.items() if self.g.nodes[k]["type"] == "Concept"}

    def similar_thinkers(self, pid: str, k: int = 6) -> list[dict]:
        g = self.g.refresh()
        base, _ = self.thinker_vector(pid)
        base_c = self._concept_only(base)
        out = []
        for p in g.of_type("Person"):
            if p["id"] == pid:
                continue
            v, _ = self.thinker_vector(p["id"])
            vc = self._concept_only(v)
            s = self._cos(base_c, vc)
            if s <= 0:
                continue
            shared = sorted(((c, base_c[c] * vc[c]) for c in base_c if c in vc and base_c[c] * vc[c] > 0),
                            key=lambda x: -x[1])[:5]
            opposed = [c for c in base_c if c in vc and base_c[c] * vc[c] < 0][:3]
            out.append({"id": p["id"], "label": g.label(p["id"]), "similarity": round(s, 3),
                        "why": [g.label(c) for c, _ in shared], "disagree_on": [g.label(c) for c in opposed]})
        out.sort(key=lambda x: -x["similarity"])
        return out[:k]

    def landscape(self, person_ids: Iterable[str] | None = None) -> dict:
        """사상 지형도: 개념 분포 벡터를 PCA 로 2차원에 투영한다."""
        g = self.g.refresh()
        pids = list(person_ids) if person_ids else [p["id"] for p in g.of_type("Person")]
        vecs = {}
        for p in pids:
            v = self._concept_only(self.thinker_vector(p)[0])
            if v:
                n = math.sqrt(sum(x * x for x in v.values()))
                vecs[p] = {k: x / n for k, x in v.items()}
        if len(vecs) < 3:
            return {"points": [], "axes": []}
        dims = sorted({k for v in vecs.values() for k in v})
        ids = list(vecs)
        X = [[vecs[i].get(d, 0.0) for d in dims] for i in ids]
        mean = [sum(col) / len(X) for col in zip(*X)]
        Xc = [[x - m for x, m in zip(row, mean)] for row in X]
        comps = []
        for _ in range(2):
            comp = _power_iteration(Xc, comps)
            comps.append(comp)
        pts = []
        for i, row in zip(ids, Xc):
            x = sum(a * b for a, b in zip(row, comps[0]))
            y = sum(a * b for a, b in zip(row, comps[1]))
            schools = g.targets(i, "member_of")
            pts.append({"id": i, "label": g.label(i), "x": round(x, 4), "y": round(y, 4), "year": g.year(i),
                        "group": g.label(schools[0]) if schools else "—"})
        axes = []
        for c in comps:
            top = sorted(range(len(dims)), key=lambda j: -abs(c[j]))[:6]
            axes.append({"loadings": [{"concept": dims[j], "label": g.label(dims[j]), "weight": round(c[j], 3)}
                                      for j in top]})
        return {"points": pts, "axes": axes}

    # ============================================================== compare
    def compare(self, a: str, b: str, topic: str | None = None, vector_index=None) -> dict:
        """두 사상가의 명제와 원전 증거를 따라가며 쟁점별로 비교한다 (말을 섞지 않는다)."""
        g = self.g.refresh()
        for x in (a, b):
            if x not in g.nodes:
                raise KeyError(x)
        va, wa = self.thinker_vector(a)
        vb, wb = self.thinker_vector(b)
        ca, cb = self._concept_only(va), self._concept_only(vb)
        props_a = self._props_by_concept(a)
        props_b = self._props_by_concept(b)
        topic_concepts: set[str] | None = None
        if topic:
            topic_concepts = self._match_concepts(topic, vector_index)
            for c in list(topic_concepts):
                topic_concepts |= set(self.concept_family(c))
        shared = [c for c in ca if c in cb]
        shared.sort(key=lambda c: -(abs(ca.get(c, 0)) + abs(cb.get(c, 0))))
        if topic_concepts is not None:
            # 주제 개념을 앞세우되, 나머지 공유 개념도 쟁점으로 남긴다
            focus = [c for c in shared if c in topic_concepts] or \
                [c for c in topic_concepts if c in ca or c in cb]
            shared = focus + [c for c in shared if c not in focus]
        issues = []
        for c in shared[:8]:
            pa = self._collect_props(props_a, c)
            pb = self._collect_props(props_b, c)
            if not pa and not pb:
                continue
            stance = self._concept_critique(a, b, c) or self._stance(a, b, pa, pb, ca.get(c, 0), cb.get(c, 0))
            issues.append({"concept": c, "label": g.label(c), "stance": stance["kind"],
                           "stance_ko": stance["label"], "basis": stance["basis"],
                           "a_positions": pa, "b_positions": pb})
        # 대립 축: a 의 개념이 b 의 개념과 opposed_to/contrasts_with
        cleavages = []
        for c1 in ca:
            for e in g.edges_of(c1, predicates=["opposed_to", "contrasts_with"]):
                c2 = g.other(e, c1)
                if c2 in cb and c2 not in ca and ca[c1] > 0 and cb[c2] > 0:
                    cleavages.append({"a_concept": g.label(c1), "b_concept": g.label(c2), "edge_id": e["id"]})
        direct = []
        for e in g.edges_of(a):
            if g.other(e, a) == b:
                direct.append({"edge_id": e["id"], "source_label": g.label(e["source"]),
                               "target_label": g.label(e["target"]), "predicate": e["predicate"],
                               "predicate_ko": O.RELATION_TYPES[e["predicate"]].label_ko,
                               "confidence": e["confidence"]})
        conn = self.explain_connection(a, b, max_depth=4)
        return {"a": a, "b": b, "a_label": g.label(a), "b_label": g.label(b), "topic": topic,
                "similarity": round(self._cos(ca, cb), 3), "issues": issues, "cleavages": cleavages[:8],
                "direct_relations": direct, "connection_summary": conn["summary"], "verdict": conn["verdict"],
                "only_a": [g.label(c) for c in sorted(ca, key=lambda c: -ca[c]) if c not in cb and ca[c] > 0][:8],
                "only_b": [g.label(c) for c in sorted(cb, key=lambda c: -cb[c]) if c not in ca and cb[c] > 0][:8]}

    def _props_by_concept(self, pid: str) -> dict[str, list[str]]:
        g = self.g
        out: dict[str, list[str]] = defaultdict(list)
        for pr in g.targets(pid, "proposes"):
            for c in g.targets(pr, "about"):
                out[c].append(pr)
                for parent in g.targets(c, "subclass_of"):
                    out[parent].append(pr)
        return out

    def _collect_props(self, by_concept: dict[str, list[str]], c: str) -> list[dict]:
        g = self.g
        res = []
        for fc in self.concept_family(c):
            for pr in by_concept.get(fc, []):
                if any(r["id"] == pr for r in res):
                    continue
                props = g.nodes[pr].get("props") or {}
                works = g.sources(pr, "contains")
                res.append({"id": pr, "statement": props.get("statement") or g.nodes[pr]["label"],
                            "work": g.label(works[0]) if works else None, "locator": props.get("locator"),
                            "year": props.get("year")})
        return res

    def _concept_critique(self, a: str, b: str, c: str) -> dict | None:
        """한쪽만 개념(또는 그 계열)을 명시적으로 비판·거부했다면 대립으로 본다."""
        g = self.g
        fam = set(self.concept_family(c))
        crit = {x: [e for e in g.edges_of(x, direction="out", predicates=["criticized", "rejected", "refuted", "challenged"])
                    if e["target"] in fam] for x in (a, b)}
        if bool(crit[a]) != bool(crit[b]):
            who = a if crit[a] else b
            e = crit[who][0]
            return {"kind": "divergence", "label": "대립",
                    "basis": f"{g.label(who)} — '{g.label(e['target'])}' {O.RELATION_TYPES[e['predicate']].label_ko} ({e['id']})"}
        return None

    def _stance(self, a, b, pa, pb, wa, wb) -> dict:
        g = self.g
        ids_a = {p["id"] for p in pa}
        ids_b = {p["id"] for p in pb}
        for x in ids_a:
            for e in g.edges_of(x, predicates=["contradicted_by"], statuses=DEFAULT_STATUSES + ("hypothesis",)):
                if g.other(e, x) in ids_b:
                    return {"kind": "divergence", "label": "대립", "basis": f"명제 간 모순 관계 {e['id']}"}
            for e in g.edges_of(x, predicates=["similar_to", "analogous_to"], statuses=DEFAULT_STATUSES):
                if g.other(e, x) in ids_b:
                    return {"kind": "convergence", "label": "수렴", "basis": f"명제 간 유사 관계 {e['id']}"}
        if wa * wb < 0:
            return {"kind": "divergence", "label": "대립", "basis": "한쪽은 수용, 다른 쪽은 비판/거부"}
        for e in g.edges_of(a, predicates=["criticized", "rejected", "refuted", "challenged"]):
            if g.other(e, a) == b:
                return {"kind": "divergence", "label": "대립",
                        "basis": f"{g.label(e['source'])} → {g.label(e['target'])} 비판 관계 {e['id']}"}
        return {"kind": "different_emphasis", "label": "다른 강조점",
                "basis": "같은 개념을 다루지만 직접적 모순·수렴 관계는 기록되지 않음"}

    def _match_concepts(self, text: str, vector_index=None) -> set[str]:
        g = self.g
        low = text.lower()
        hits = set()
        for c in g.of_type("Concept"):
            names = [c["label"].lower(), (c.get("label_ko") or "").lower()] + [x.lower() for x in c.get("aliases") or []]
            if any(n and n in low for n in names):
                hits.add(c["id"])
        if not hits and vector_index is not None:
            hits = {i for i, s in vector_index.search(text, 3, types=["Concept"], min_score=0.1)}
        return hits

    # ============================================================ timeline
    def timeline(self, types: Iterable[str] = ("Person", "Work", "Event")) -> list[dict]:
        g = self.g.refresh()
        items = []
        for n in g.of_type(*types):
            y = g.year(n["id"])
            if y is None:
                continue
            items.append({"id": n["id"], "type": n["type"], "label": g.label(n["id"]), "year": y,
                          "end_year": n.get("end_year"), "era": self.era_of_year(y)})
        items.sort(key=lambda x: x["year"])
        return items

    def entity_detail(self, nid: str) -> dict:
        g = self.g.refresh()
        n = g.nodes.get(nid)
        if not n:
            raise KeyError(nid)
        groups: dict[str, list] = defaultdict(list)
        for e in g.edges_of(nid, statuses=None):
            rel = O.RELATION_TYPES[e["predicate"]]
            outgoing = e["source"] == nid
            o = g.other(e, nid)
            key = f"{e['predicate']}{'' if outgoing else ' (역방향)'}"
            groups[key].append({"edge_id": e["id"], "other": o, "other_label": g.label(o),
                                "other_type": g.nodes[o]["type"], "outgoing": outgoing,
                                "predicate_ko": rel.label_ko, "category": rel.category,
                                "confidence": e["confidence"], "epistemic_status": e["epistemic_status"],
                                "evidence_status": e["evidence_status"],
                                "evidence_count": len(g.store.list_evidence(e["id"]))})
        return {"entity": n, "year": g.year(nid), "era": self.era_of_year(g.year(nid)),
                "domains": [{"id": d, "label": g.label(d)} for d in g.domains_of(nid)],
                "relations": dict(groups)}


def _power_iteration(X: list[list[float]], prev: list[list[float]], iters: int = 200) -> list[float]:
    n = len(X[0])
    v = [1.0 / math.sqrt(n) + (i % 7) * 1e-3 for i in range(n)]
    for _ in range(iters):
        # w = Xᵀ X v
        xv = [sum(a * b for a, b in zip(row, v)) for row in X]
        w = [0.0] * n
        for row, s in zip(X, xv):
            for j, a in enumerate(row):
                w[j] += a * s
        for p in prev:  # 이전 주성분과 직교화
            d = sum(a * b for a, b in zip(w, p))
            w = [a - d * b for a, b in zip(w, p)]
        norm = math.sqrt(sum(a * a for a in w)) or 1.0
        v = [a / norm for a in w]
    return v
