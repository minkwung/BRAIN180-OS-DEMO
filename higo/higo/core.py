"""HIGO 시스템 파사드 — 저장소·그래프·벡터·추론·발견·추출·RAG·검증을 하나로 묶는다.

    Primary Sources → Document Pipeline → AI Extraction → Ontology Layer
      → Knowledge Graph + Evidence Graph → Reasoning → Discovery → Human Validation
      → Living Ontology
"""
from __future__ import annotations

from .discovery import DiscoveryEngine
from .extraction import Extractor
from .graph import GraphIndex
from .llm import LLMClient
from .rag import GraphRAG
from .reasoning import Reasoner
from .store import Store
from .validation import Reviewer, validate_graph
from .vector import VectorIndex, entity_text


class HIGO:
    def __init__(self, db_path: str = ":memory:", llm: LLMClient | None = None, data_dir=None):
        self.data_dir = data_dir
        self.store = Store(db_path)
        self.graph = GraphIndex(self.store)
        self.llm = llm if llm is not None else LLMClient()
        self._vectors = VectorIndex()
        self._vec_rev = -1
        self.reasoner = Reasoner(self.graph)
        self.reviewer = Reviewer(self.store)
        self.extractor = Extractor(self.store, self.graph, self.llm)

    @property
    def vectors(self) -> VectorIndex:
        if self._vec_rev != self.store.revision:
            self.graph.refresh()
            items = [(n["id"], entity_text(n), {"type": n["type"]}) for n in self.graph.nodes.values()
                     if n["type"] not in ("Era", "Domain", "Source")]
            self._vectors = VectorIndex().build(items)
            self._vec_rev = self.store.revision
        return self._vectors

    @property
    def discovery(self) -> DiscoveryEngine:
        return DiscoveryEngine(self.store, self.graph.refresh(), self.vectors)

    @property
    def rag(self) -> GraphRAG:
        return GraphRAG(self.graph.refresh(), self.vectors, self.reasoner, self.extractor, self.llm)

    def ask(self, question: str, use_llm: bool = True, include_hypotheses: bool = False) -> dict:
        return self.rag.answer(question, use_llm=use_llm, include_hypotheses=include_hypotheses)

    def search(self, q: str, k: int = 15, types=None) -> list[dict]:
        g = self.graph.refresh()
        hits = self.vectors.search(q, k, types=types, min_score=0.02)
        # 이름 일치를 우선
        exact = [n["id"] for n in self.store.list_entities(q=q, limit=10)]
        ordered = exact + [i for i, _ in hits if i not in exact]
        scores = dict(hits)
        return [{"id": i, "type": g.nodes[i]["type"], "label": g.label(i), "score": round(scores.get(i, 1.0), 3),
                 "year": g.year(i)} for i in ordered[:k] if i in g.nodes]

    def validate(self) -> dict:
        return validate_graph(self.store).as_dict()

    def seed(self) -> dict:
        """빈 저장소를 채운다: 데이터 파일(data/)이 있으면 그것을, 없으면 Phase 1 seed 를 적재."""
        from . import datafiles
        from .seed import load_seed
        if self.store.stats()["entities"]:
            return {"skipped": True, **self.store.stats()}
        if self.data_dir is not None and datafiles.has_data(self.data_dir):
            datafiles.load_data(self.store, self.data_dir)
            return self.store.stats()
        return load_seed(self.store)

    def export_data(self, data_dir=None) -> dict:
        from . import datafiles
        return datafiles.export_data(self.store, data_dir or self.data_dir or datafiles.DEFAULT_DATA_DIR)
