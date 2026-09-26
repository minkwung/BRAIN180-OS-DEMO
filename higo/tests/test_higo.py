"""HIGO 테스트 — python -m unittest discover -s tests"""
import json
import os
import unittest

os.environ["HIGO_LLM"] = "off"

from higo import HIGO  # noqa: E402
from higo import export  # noqa: E402
from higo import ontology as O  # noqa: E402
from higo.confidence import compute_confidence  # noqa: E402
from higo.server import Api, ApiError  # noqa: E402
from higo.validation import ReviewError, validate_edge  # noqa: E402


class SeededCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = HIGO(":memory:")
        cls.h.seed()

    def edge(self, s, p, t):
        return self.h.store.find_edge(s, p, t)


class TestSchemaAndSeed(SeededCase):
    def test_seed_passes_schema_validation(self):
        report = self.h.validate()
        self.assertTrue(report["ok"], [i for i in report["issues"] if i["level"] == "error"])

    def test_phase1_scope(self):
        stats = self.h.store.stats()
        self.assertGreaterEqual(stats["entities_by_type"]["Person"], 30)
        self.assertGreaterEqual(stats["entities_by_type"]["Proposition"], 100)
        self.assertGreater(stats["evidence"], 300)

    def test_every_influence_edge_has_evidence(self):
        for e in self.h.store.list_edges(predicate="influenced"):
            self.assertTrue(self.h.store.list_evidence(e["id"]), e)

    def test_every_proposition_has_author_and_work(self):
        g = self.h.graph.refresh()
        for p in g.of_type("Proposition"):
            self.assertTrue(g.sources(p["id"], "proposes"), p["id"])
            self.assertTrue(g.sources(p["id"], "contains"), p["id"])


class TestConfidence(unittest.TestCase):
    def test_tiers_and_status(self):
        self.assertAlmostEqual(compute_confidence([{"tier": 1}], "direct"), 0.9)
        self.assertLess(compute_confidence([{"tier": 1}], "disputed"), compute_confidence([{"tier": 1}], "direct"))
        more = compute_confidence([{"tier": 3}, {"tier": 1}], "direct")
        self.assertGreater(more, 0.9)
        contra = compute_confidence([{"tier": 1}, {"tier": 1, "stance": "contradicts"}], "direct")
        self.assertLess(contra, 0.5)
        self.assertEqual(compute_confidence([], "direct", requires_evidence=True), 0.0)
        self.assertEqual(compute_confidence([], "direct", requires_evidence=False), 1.0)


class TestInfluenceVsSimilarity(SeededCase):
    def test_plato_kant_kept_separate(self):
        inf = self.edge("person:plato", "influenced", "person:kant")
        sim = self.edge("person:plato", "similar_to", "person:kant")
        self.assertIsNotNone(inf)
        self.assertIsNotNone(sim)
        self.assertEqual(inf["evidence_status"], "indirect")
        self.assertIn(O.RELATION_TYPES["similar_to"].category, O.NON_CAUSAL_CATEGORIES)

    def test_similarity_path_never_classified_as_influence(self):
        conn = self.h.reasoner.explain_connection("prop:plato-city-division-of-labor", "prop:smith-division-of-labor")
        kinds = {s["kind"] for s in conn["summary"]}
        self.assertIn("STRUCTURAL_SIMILARITY", kinds)
        self.assertNotIn("DIRECT_INFLUENCE", kinds)

    def test_aristotle_jefferson_is_not_direct(self):
        conn = self.h.reasoner.explain_connection("person:aristotle", "person:jefferson")
        kinds = [s["kind"] for s in conn["summary"]]
        self.assertNotIn("DIRECT_INFLUENCE", kinds)
        self.assertIn("INDIRECT_INFLUENCE", kinds)
        chains = [c for c in conn["connections"]["INDIRECT_INFLUENCE"] if len(c["steps"]) > 1]
        via = {s["to_label"] for c in chains for s in c["steps"]}
        self.assertTrue({"토마스 아퀴나스", "로크"} <= via, via)

    def test_direct_influence_detected(self):
        conn = self.h.reasoner.explain_connection("person:hume", "person:kant")
        self.assertEqual(conn["summary"][0]["kind"], "DIRECT_INFLUENCE")


class TestValidationWorkflow(unittest.TestCase):
    def setUp(self):
        self.h = HIGO(":memory:")
        self.h.seed()
        self.s = self.h.store

    def test_anachronism_rejected(self):
        rep = validate_edge(self.s, {"source": "person:kant", "predicate": "influenced", "target": "person:plato",
                                     "epistemic_status": "proposed"})
        self.assertIn("anachronism", [i.code for i in rep.issues])

    def test_domain_range_enforced(self):
        rep = validate_edge(self.s, {"source": "concept:justice", "predicate": "authored", "target": "person:plato"})
        codes = [i.code for i in rep.issues]
        self.assertIn("domain_violation", codes)
        self.assertIn("range_violation", codes)

    def test_ai_actor_cannot_review(self):
        e = self.s.find_edge("person:plato", "influenced", "person:smith")
        with self.assertRaises(ReviewError):
            self.h.reviewer.approve(e["id"], "ai:discovery")

    def test_hypothesis_needs_better_evidence_then_can_be_rejected(self):
        e = self.s.find_edge("person:plato", "influenced", "person:smith")
        self.assertEqual(e["epistemic_status"], "hypothesis")
        self.assertLess(e["confidence"], 0.2)
        done = self.h.reviewer.reject(e["id"], "연구자A", "원전 증거 없음 — 유사성일 뿐")
        self.assertEqual(done["epistemic_status"], "rejected")
        self.assertEqual(self.s.history(e["id"])[0]["actor"], "연구자A")

    def test_unevidenced_influence_cannot_be_approved(self):
        e = self.s.add_edge("person:epicurus", "influenced", "person:hume", epistemic_status="proposed")
        with self.assertRaises(ReviewError):
            self.h.reviewer.approve(e["id"], "연구자A")
        self.s.add_evidence(e["id"], tier=3, citation="test citation", added_by="연구자A")
        ok = self.h.reviewer.approve(e["id"], "연구자A", "증거 보강")
        self.assertEqual(ok["epistemic_status"], "accepted")

    def test_new_evidence_raises_confidence_and_is_logged(self):
        e = self.s.find_edge("person:hobbes", "influenced", "person:locke")
        before = e["confidence"]
        self.s.add_evidence(e["id"], tier=1, citation="new primary evidence", added_by="연구자A")
        after = self.s.get_edge(e["id"])["confidence"]
        self.assertGreater(after, before)
        self.assertIn("confidence", [h["action"] for h in self.s.history(e["id"])])

    def test_counter_evidence_contests(self):
        e = self.s.find_edge("person:hume", "influenced", "person:kant")
        res = self.h.reviewer.contest(e["id"], "연구자B", "반론 제기",
                                      {"tier": 3, "citation": "hypothetical counter-study"})
        self.assertEqual(res["epistemic_status"], "contested")
        self.assertLess(res["confidence"], e["confidence"])

    def test_invalid_transition(self):
        e = self.s.find_edge("person:marx", "student_of", "person:hegel")
        self.assertEqual(e["epistemic_status"], "rejected")
        with self.assertRaises(ReviewError):
            self.h.reviewer.approve(e["id"], "연구자A")


class TestReasoning(SeededCase):
    def test_freedom_genealogy_spans_eras(self):
        g = self.h.reasoner.concept_genealogy("concept:freedom")
        self.assertGreaterEqual(len(g["by_era"]), 5)
        fam = {f["id"] for f in g["family"]}
        self.assertTrue({"concept:negative-freedom", "concept:positive-freedom"} <= fam)
        props = [t["proposition"] for t in g["timeline"] if t["kind"] == "proposition"]
        self.assertEqual(len(props), len(set(props)), "duplicate proposition entries")

    def test_marx_nietzsche_issues(self):
        c = self.h.reasoner.compare("person:marx", "person:nietzsche", vector_index=self.h.vectors)
        labels = {i["label"] for i in c["issues"]}
        self.assertTrue({"근대성", "종교 비판"} <= labels, labels)

    def test_smith_marx_division_of_labor_divergence(self):
        c = self.h.reasoner.compare("person:smith", "person:marx")
        dol = [i for i in c["issues"] if i["concept"] == "concept:division-of-labor"][0]
        self.assertEqual(dol["stance"], "divergence")

    def test_dna_and_landscape(self):
        d = self.h.reasoner.thinker_dna("person:kant")
        self.assertTrue(d["domains"] and d["concepts"] and d["similar"])
        land = self.h.reasoner.landscape()
        self.assertGreater(len(land["points"]), 20)

    def test_contradictions_and_cross_domain(self):
        c = self.h.reasoner.contradiction_graph()
        pairs = {tuple(sorted(s["label"] for s in a["sides"])) for a in c["axes"]}
        self.assertIn(("경험론", "합리론"), pairs)
        x = self.h.reasoner.cross_domain()
        self.assertTrue(x["domain_pairs"])
        self.assertIn("뉴턴", [b["label"] for b in x["bridge_thinkers"]])


class TestDiscoveryAndExtraction(unittest.TestCase):
    def setUp(self):
        self.h = HIGO(":memory:")
        self.h.seed()

    def test_discovery_commits_only_hypotheses(self):
        r = self.h.discovery.run()
        self.assertTrue(any(r["counts"].values()))
        item = r["results"]["semantic_similarity"][0]
        e = self.h.discovery.commit(item)
        self.assertEqual(e["epistemic_status"], "hypothesis")
        self.assertEqual(e["origin"], "ai")
        self.assertEqual([x["tier"] for x in e["evidence"]], [6])
        with self.assertRaises(ValueError):
            self.h.discovery.commit(r["results"]["transitive_influence"][0])

    def test_extraction_to_candidates_to_hypothesis(self):
        text = "Spinoza was influenced by Descartes. 헤겔은 칸트를 비판했다. 키르케고르는 '진리는 주체성이다'라고 주장했다."
        res = self.h.extractor.ingest("t", text)
        edges = [c for c in res["candidates"] if c["kind"] == "edge"]
        pairs = {(c["payload"]["source"], c["payload"]["predicate"], c["payload"]["target"]) for c in edges}
        self.assertIn(("person:descartes", "influenced", "person:spinoza"), pairs)
        self.assertIn(("person:hegel", "criticized", "person:kant"), pairs)
        # 이미 있는 관계는 add_edge 가 기존 것을 돌려준다; 새 관계 후보를 채택해 보자
        new = self.h.store.add_candidate("edge", {"source": "person:kierkegaard", "predicate": "influenced",
                                                  "target": "person:camus", "sentence": "test"})
        out = self.h.extractor.approve_candidate(new["id"], "연구자A")
        self.assertEqual(out["created"]["epistemic_status"], "hypothesis")
        self.assertEqual(out["created"]["evidence"][0]["tier"], 5)


class TestGraphRAG(SeededCase):
    QUESTIONS = {
        "자유라는 개념은 고대부터 현대까지 어떻게 변화했는가?": "genealogy",
        "근대적 합리주의는 어디에서 시작되어 어떻게 변형되었는가?": "genealogy",
        "플라톤 → 아리스토텔레스 → 아퀴나스 → 데카르트 → 칸트의 인식론적 연속성과 단절을 찾아라": "chain",
        "마르크스와 니체는 근대성에 대해 어떤 공통 문제의식을 가지고 있었으며 어디에서 갈라지는가?": "compare",
        "동일한 개념이 철학·경제학·정치학에서 어떻게 다른 의미로 변형되었는가?": "cross_domain",
    }

    def test_validation_questions(self):
        for q, intent in self.QUESTIONS.items():
            r = self.h.ask(q)
            self.assertEqual(r["intent"], intent, q)
            self.assertEqual(r["unsupported_citations"], [], q)
            self.assertTrue(r["answer"].strip())
        chain = self.h.ask(list(self.QUESTIONS)[2])
        self.assertEqual(len(chain["analysis"]["chain"]), 5)


class TestApiAndExport(SeededCase):
    def test_api_dispatch(self):
        api = Api(self.h)
        self.assertIn("entities", api.dispatch("GET", "/api/stats", {}, None))
        d = api.dispatch("GET", "/api/entities/person:kant", {}, None)
        self.assertEqual(d["entity"]["id"], "person:kant")
        with self.assertRaises(ApiError):
            api.dispatch("POST", "/api/edges", {}, {"source": "person:kant", "predicate": "influenced",
                                                    "target": "person:plato"})
        with self.assertRaises(ApiError):
            api.dispatch("GET", "/api/nope", {}, None)

    def test_exports_and_roundtrip(self):
        self.assertIn("MERGE", export.to_cypher(self.h.store))
        ttl = export.to_turtle(self.h.store)
        self.assertIn("owl:ObjectProperty", ttl)
        data = json.loads(json.dumps(export.to_json(self.h.store), default=str))
        other = HIGO(":memory:")
        counts = export.import_json(other.store, data)
        self.assertEqual(counts["edges"], len(data["edges"]))
        self.assertEqual(other.store.stats()["evidence"], self.h.store.stats()["evidence"])


if __name__ == "__main__":
    unittest.main()
