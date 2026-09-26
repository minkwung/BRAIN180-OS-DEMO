"""Store 위에 올라가는 인메모리 그래프 인덱스.

추론·탐색·발견 엔진은 모두 이 인덱스를 사용한다. Store 의 revision 이 바뀌면
자동으로 다시 만든다.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from . import ontology as O
from .store import Store

DEFAULT_STATUSES = ("accepted", "revised", "proposed", "contested")


class GraphIndex:
    def __init__(self, store: Store):
        self.store = store
        self._rev = -1
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.out: dict[str, list[str]] = defaultdict(list)
        self.inc: dict[str, list[str]] = defaultdict(list)
        self.refresh()

    def refresh(self, force: bool = False) -> "GraphIndex":
        if not force and self._rev == self.store.revision:
            return self
        self.nodes = {e["id"]: e for e in self.store.list_entities()}
        self.edges = {e["id"]: e for e in self.store.list_edges()}
        self.out = defaultdict(list)
        self.inc = defaultdict(list)
        for e in self.edges.values():
            self.out[e["source"]].append(e["id"])
            self.inc[e["target"]].append(e["id"])
        self._rev = self.store.revision
        return self

    # ------------------------------------------------------------- helpers
    def label(self, nid: str) -> str:
        n = self.nodes.get(nid)
        if not n:
            return nid
        return n.get("label_ko") or n["label"]

    def year(self, nid: str) -> int | None:
        n = self.nodes.get(nid) or {}
        y = n.get("start_year")
        if y is None and n.get("type") == "Proposition":
            y = (n.get("props") or {}).get("year")
        return y

    def floruit(self, nid: str) -> int | None:
        """활동 전성기 추정치: 인물은 출생 + 40년(사망 연도 상한), 그 밖에는 시작 연도."""
        n = self.nodes.get(nid) or {}
        y = self.year(nid)
        if n.get("type") == "Person" and y is not None:
            end = n.get("end_year")
            return min(y + 40, end) if end is not None else y + 40
        return y

    def of_type(self, *types: str) -> list[dict]:
        return [n for n in self.nodes.values() if n["type"] in types]

    def edges_of(self, nid: str, *, direction: str = "both", predicates: Iterable[str] | None = None,
                 statuses: Iterable[str] | None = DEFAULT_STATUSES) -> list[dict]:
        preds = set(predicates) if predicates else None
        sts = set(statuses) if statuses else None
        ids: list[str] = []
        if direction in ("out", "both"):
            ids += self.out.get(nid, [])
        if direction in ("in", "both"):
            ids += self.inc.get(nid, [])
        res = []
        for eid in ids:
            e = self.edges[eid]
            if preds and e["predicate"] not in preds:
                continue
            if sts and e["epistemic_status"] not in sts:
                continue
            res.append(e)
        return res

    def targets(self, nid: str, predicate: str, **kw) -> list[str]:
        return [e["target"] for e in self.edges_of(nid, direction="out", predicates=[predicate], **kw)]

    def sources(self, nid: str, predicate: str, **kw) -> list[str]:
        return [e["source"] for e in self.edges_of(nid, direction="in", predicates=[predicate], **kw)]

    def other(self, edge: dict, nid: str) -> str:
        return edge["target"] if edge["source"] == nid else edge["source"]

    # ----------------------------------------------------------- domains
    def domain_ancestors(self, domain_id: str) -> list[str]:
        chain, cur, seen = [], domain_id, set()
        while cur and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            parents = self.targets(cur, "subclass_of")
            cur = parents[0] if parents else None
        return chain

    def top_domain(self, domain_id: str) -> str:
        return self.domain_ancestors(domain_id)[-1]

    def domains_of(self, nid: str) -> set[str]:
        """노드가 속한 분야. 명제는 about 개념의 분야를, 인물은 저작·명제의 분야를 물려받는다."""
        n = self.nodes.get(nid)
        if not n:
            return set()
        direct = set(self.targets(nid, "belongs_to_domain"))
        if direct:
            return direct
        t = n["type"]
        if t == "Proposition":
            out: set[str] = set()
            for c in self.targets(nid, "about"):
                out |= set(self.targets(c, "belongs_to_domain"))
            return out
        if t == "Person":
            out = set()
            for w in self.targets(nid, "authored"):
                out |= set(self.targets(w, "belongs_to_domain"))
            return out
        return set()

    def subgraph(self, seeds: Iterable[str], depth: int = 1, *, statuses=DEFAULT_STATUSES,
                 max_nodes: int = 250, exclude_types: Iterable[str] = ("Era", "Domain")) -> dict:
        excl = set(exclude_types)
        seen = {s for s in seeds if s in self.nodes}
        frontier = list(seen)
        edge_ids: set[str] = set()
        for _ in range(depth):
            nxt = []
            for nid in frontier:
                for e in self.edges_of(nid, statuses=statuses):
                    o = self.other(e, nid)
                    if self.nodes[o]["type"] in excl and o not in seen:
                        continue
                    edge_ids.add(e["id"])
                    if o not in seen and len(seen) < max_nodes:
                        seen.add(o)
                        nxt.append(o)
            frontier = nxt
        if depth == 0:  # 시드 노드들 사이의 유도 부분그래프
            sts = set(statuses) if statuses else None
            edge_ids = {eid for nid in seen for eid in self.out.get(nid, [])
                        if self.edges[eid]["target"] in seen
                        and (sts is None or self.edges[eid]["epistemic_status"] in sts)}
        edge_ids = {eid for eid in edge_ids
                    if self.edges[eid]["source"] in seen and self.edges[eid]["target"] in seen}
        return self.to_view(seen, edge_ids)

    def to_view(self, node_ids: Iterable[str], edge_ids: Iterable[str]) -> dict:
        nodes = []
        for nid in node_ids:
            n = self.nodes[nid]
            nodes.append({"id": nid, "type": n["type"], "label": n["label"], "label_ko": n.get("label_ko"),
                          "year": self.year(nid), "status": n.get("status"),
                          "degree": len(self.out.get(nid, [])) + len(self.inc.get(nid, []))})
        edges = []
        for eid in edge_ids:
            e = self.edges[eid]
            rel = O.RELATION_TYPES[e["predicate"]]
            edges.append({"id": eid, "source": e["source"], "target": e["target"], "predicate": e["predicate"],
                          "category": rel.category, "confidence": e["confidence"],
                          "epistemic_status": e["epistemic_status"], "evidence_status": e["evidence_status"],
                          "origin": e["origin"]})
        return {"nodes": nodes, "edges": edges}

    def full_view(self, *, types: Iterable[str] | None = None, statuses=DEFAULT_STATUSES,
                  predicates: Iterable[str] | None = None) -> dict:
        ts = set(types) if types else None
        ps = set(predicates) if predicates else None
        node_ids = {nid for nid, n in self.nodes.items() if not ts or n["type"] in ts}
        edge_ids = {eid for eid, e in self.edges.items()
                    if e["source"] in node_ids and e["target"] in node_ids
                    and (not statuses or e["epistemic_status"] in statuses)
                    and (not ps or e["predicate"] in ps)}
        return self.to_view(node_ids, edge_ids)
