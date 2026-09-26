"""1단계 자동 갱신 기반 테스트 — 데이터 파일화 · 원문 대조 · 위험도 정책 · 주기 실행 · 묶음 승인."""
import os
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["HIGO_LLM"] = "off"

from higo import HIGO, datafiles, gaps  # noqa: E402
from higo.changeset import ChangesetApplier, approve_run  # noqa: E402
from higo.cycle import run_cycle  # noqa: E402
from higo.policy import HIGH, LOW, MEDIUM, REJECTED, STRUCTURAL  # noqa: E402
from higo.validation import ReviewError  # noqa: E402
from higo.verify import FETCH_FAILED, NO_URL, NOT_FOUND, PARTIAL, VERIFIED, QuoteVerifier, normalize  # noqa: E402

REPO_DATA = Path(__file__).resolve().parent.parent / "data"

PAGES = {
    "/ferguson.html": """<html><head><style>p{}</style><script>var x='nope';</script></head><body>
      <h1>Adam Ferguson (1723–1816)</h1>
      <p>Adam Ferguson was a Scottish philosopher of the Enlightenment, born in 1723 and died in 1816.</p>
      <p>Nations stumble upon establishments, which are indeed the result of human action,
         but not the execution of any human design.</p></body></html>""",
    "/ferguson-essay.html": """<html><body><p>An Essay on the History of Civil Society was published in 1767
      by Adam Ferguson.</p></body></html>""",
    "/hume.txt": "HUME. All reasonings concerning matter of fact seem to be founded on the relation of Cause and Effect.",
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8" if self.path.endswith(".html") else "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class LocalSite:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()


def example_changeset(base: str) -> dict:
    ev = lambda path, quote, tier=1, **kw: {"tier": tier, "url": base + path, "quotation": quote,  # noqa: E731
                                           "citation": f"test {path}", **kw}
    return {"agent": {"model": "test", "prompt_version": "t1"}, "operations": [
        {"op": "add_entity", "entity": {"id": "person:ferguson", "type": "Person", "label": "Adam Ferguson",
                                        "label_ko": "애덤 퍼거슨", "start_year": 1723, "end_year": 1816},
         "evidence": [ev("/ferguson.html", "born in 1723 and died in 1816")], "rationale": "스코틀랜드 계몽주의"},
        {"op": "add_entity", "entity": {"id": "person:fake", "type": "Person", "label": "Fabricated Person",
                                        "start_year": 1700, "end_year": 1750},
         "evidence": [ev("/ferguson.html", "a sentence that is not on the page at all, invented by the model")]},
        {"op": "add_entity", "entity": {"id": "work:essay-civil-society", "type": "Work",
                                        "label": "An Essay on the History of Civil Society", "start_year": 1767},
         "evidence": [ev("/ferguson-essay.html", "History of Civil Society was published in 1767")]},
        {"op": "add_edge", "edge": {"source": "person:ferguson", "predicate": "authored",
                                    "target": "work:essay-civil-society"},
         "evidence": [ev("/ferguson-essay.html", "published in 1767 by Adam Ferguson")]},
        {"op": "add_edge", "edge": {"source": "person:ferguson", "predicate": "influenced", "target": "person:hayek",
                                    "evidence_status": "direct"},
         "evidence": [ev("/ferguson.html", "the result of human action, but not the execution of any human design")]},
        {"op": "add_proposition", "proposition": {"author": "person:ferguson", "work": "work:essay-civil-society",
                                                  "statement": "제도는 인간 행위의 결과이지만 인간 설계의 산물은 아니다.",
                                                  "locator": "Part III §2", "year": 1767,
                                                  "concepts": ["concept:spontaneous-order", "concept:no-such"]},
         "evidence": [ev("/ferguson.html", "result of human action, but not the execution of any human design")]},
        {"op": "add_evidence", "edge": {"source": "person:hume", "predicate": "influenced", "target": "person:kant"},
         "evidence": [ev("/hume.txt", "All reasonings concerning matter of fact seem to be founded on the relation of Cause and Effect")]},
        {"op": "add_evidence", "edge": {"source": "person:hume", "predicate": "influenced", "target": "person:kant"},
         "evidence": [ev("/hume.txt", "Cause and Effect", tier=3, stance="contradicts")]},
        {"op": "add_edge", "edge": {"source": "person:ferguson", "predicate": "member_of",
                                    "target": "school:enlightenment"},
         "evidence": [ev("/missing.html", "anything")]},
        {"op": "update_entity", "id": "person:kant", "changes": {"end_year": 1805}},
        {"op": "schema_change", "description": "새 관계 유형 'translated' 추가", "proposal": {"relation": "translated"}},
        {"op": "add_edge", "edge": {"source": "person:ferguson", "predicate": "no_such_relation", "target": "person:hume"}},
    ]}


class TestVerifier(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("  “Cause”—and\nEFFECT! "), "cause and effect")

    def test_verdicts(self):
        with LocalSite() as site:
            v = QuoteVerifier()
            url = site.base + "/ferguson.html"
            self.assertEqual(v.check(url, "the result of human action, but not the execution").status, VERIFIED)
            self.assertEqual(v.check(url, "var x").status, NOT_FOUND)  # 스크립트 내용은 본문이 아님
            self.assertEqual(v.check(url, "Nations stumble upon establishments, which are indeed the result of "
                                          "human action, but not the execution of any human plan").status, PARTIAL)
            self.assertEqual(v.check(url, "completely invented sentence about nothing here").status, NOT_FOUND)
            self.assertEqual(v.check(site.base + "/nope", "x").status, FETCH_FAILED)
            self.assertEqual(v.check("", "x").status, NO_URL)
            self.assertEqual(v.check("file:///etc/passwd", "root").status, FETCH_FAILED)


class TestDataFiles(unittest.TestCase):
    def test_repo_data_loads_and_round_trips(self):
        h = HIGO(data_dir=REPO_DATA)
        h.seed()
        self.assertTrue(h.validate()["ok"])
        self.assertGreaterEqual(h.store.stats()["entities_by_type"]["Person"], 30)
        out = Path(tempfile.mkdtemp())
        datafiles.export_data(h.store, out)
        for sub in ("entities", "edges"):
            for f in (REPO_DATA / sub).glob("*.jsonl"):
                self.assertEqual(f.read_text(encoding="utf-8"), (out / sub / f.name).read_text(encoding="utf-8"), f.name)

    def test_new_ids_continue_after_loaded_ones(self):
        h = HIGO(data_dir=REPO_DATA)
        h.seed()
        max_id = max(e["id"] for e in h.store.list_edges())
        e = h.store.add_edge("person:hume", "influenced", "person:mill", evidence_status="inferred")
        self.assertGreater(e["id"], max_id)


class TestChangesetPolicy(unittest.TestCase):
    def setUp(self):
        self.h = HIGO(data_dir=REPO_DATA)
        self.h.seed()

    def test_policy_outcomes(self):
        with LocalSite() as site:
            cs = example_changeset(site.base)
            out = ChangesetApplier(self.h.store, QuoteVerifier(), "R20260101-01").apply(cs)
        r = {i: res for i, res in enumerate(out["results"])}
        self.assertEqual((r[0]["risk"], r[0]["outcome"]), (LOW, "applied_accepted"))      # 사실 확인 + 원문 일치
        self.assertEqual((r[1]["risk"], r[1]["outcome"]), (REJECTED, "rejected"))          # 날조 인용
        self.assertIsNone(self.h.store.get_entity("person:fake"))
        self.assertEqual((r[2]["risk"], r[2]["outcome"]), (LOW, "applied_accepted"))
        self.assertEqual((r[3]["risk"], r[3]["outcome"]), (LOW, "applied_accepted"))
        self.assertEqual((r[4]["risk"], r[4]["outcome"]), (HIGH, "applied_hypothesis"))    # 영향은 항상 가설
        self.assertEqual((r[5]["risk"], r[5]["outcome"]), (MEDIUM, "applied_proposed"))
        self.assertTrue(any("concept:no-such" in x for x in r[5]["reasons"]))
        self.assertEqual((r[6]["risk"], r[6]["outcome"]), (LOW, "applied_accepted"))
        self.assertEqual((r[7]["risk"], r[7]["outcome"]), (HIGH, "pending"))              # 반대 증거
        self.assertEqual((r[8]["risk"], r[8]["outcome"]), (MEDIUM, "applied_proposed"))   # 문서 열기 실패 → 강등
        self.assertEqual((r[9]["risk"], r[9]["outcome"]), (HIGH, "pending"))              # 기존 사실 수정은 안 함
        self.assertEqual(self.h.store.get_entity("person:kant")["end_year"], 1804)
        self.assertEqual((r[10]["risk"], r[10]["outcome"]), (STRUCTURAL, "pending"))
        self.assertEqual(r[11]["outcome"], "rejected")
        self.assertEqual(out["audit_sample"] and len(out["audit_sample"]), 1)

        infl = self.h.store.find_edge("person:ferguson", "influenced", "person:hayek")
        self.assertEqual(infl["epistemic_status"], "hypothesis")
        auth = self.h.store.find_edge("person:ferguson", "authored", "work:essay-civil-society")
        self.assertEqual(auth["epistemic_status"], "accepted")
        ev = self.h.store.list_evidence(auth["id"])[0]
        self.assertEqual(ev["verification"], VERIFIED)
        self.assertTrue(ev["content_hash"].startswith("sha256:"))
        self.assertTrue(self.h.validate()["ok"], self.h.validate()["issues"][:3])
        # 원문 대조를 통과하지 못한 AI 증거는 확신도에 반영되지 않는다
        member = self.h.store.find_edge("person:ferguson", "member_of", "school:enlightenment")
        self.assertEqual(self.h.store.list_evidence(member["id"])[0]["verification"], FETCH_FAILED)
        e = self.h.store.add_edge("person:ferguson", "influenced", "person:smith", evidence_status="direct")
        self.h.store.add_evidence(e["id"], tier=1, citation="x", url="http://x", verification=FETCH_FAILED,
                                  added_by="ai:R1")
        self.assertEqual(self.h.store.get_edge(e["id"])["confidence"], 0.0)
        self.h.store.add_evidence(e["id"], tier=1, citation="y", added_by="ai:R1")  # URL 없는 AI 증거
        self.assertEqual(self.h.store.get_edge(e["id"])["confidence"], 0.0)

    def test_batch_approval(self):
        with LocalSite() as site:
            ChangesetApplier(self.h.store, QuoteVerifier(), "R20260101-02").apply(example_changeset(site.base))
        with self.assertRaises(ReviewError):
            approve_run(self.h.store, "R20260101-02", "policy:auto")
        res = approve_run(self.h.store, "R20260101-02", "연구자A")
        self.assertTrue(res["approved"])
        prop = [e for e in self.h.store.list_entities(type="Proposition") if (e["props"] or {}).get("run") == "R20260101-02"][0]
        self.assertEqual(prop["status"], "accepted")
        # 가설(영향)은 묶음 승인 대상이 아니다
        infl = self.h.store.find_edge("person:ferguson", "influenced", "person:hayek")
        self.assertEqual(infl["epistemic_status"], "hypothesis")


class TestCycle(unittest.TestCase):
    def test_full_cycle_writes_files_and_report(self):
        tmp = Path(tempfile.mkdtemp()) / "data"
        shutil.copytree(REPO_DATA, tmp)
        with LocalSite() as site:
            rec = run_cycle(tmp, example_changeset(site.base), verifier=QuoteVerifier())
        self.assertTrue(rec["ok"], rec["validation"])
        self.assertFalse(rec["regression"])
        rid = rec["run_id"]
        self.assertTrue((tmp / "runs" / f"{rid}.md").is_file())
        report = (tmp / "runs" / f"{rid}.md").read_text(encoding="utf-8")
        for heading in ("자동 반영", "묶음 승인 대기", "개별 판단 필요", "구조 변경 제안", "자동 기각", "다음 주기 작업"):
            self.assertIn(heading, report)
        self.assertIn("애덤 퍼거슨", (tmp / "entities" / "person.jsonl").read_text(encoding="utf-8"))
        # 다시 적재해도 같은 상태
        h = HIGO(data_dir=tmp)
        h.seed()
        self.assertTrue(h.validate()["ok"])
        self.assertEqual(h.store.find_edge("person:ferguson", "influenced", "person:hayek")["epistemic_status"],
                         "hypothesis")

    def test_cycle_without_changeset_is_noop_on_data(self):
        tmp = Path(tempfile.mkdtemp()) / "data"
        shutil.copytree(REPO_DATA, tmp)
        before = {f.name: f.read_text(encoding="utf-8") for f in (tmp / "edges").glob("*.jsonl")}
        rec = run_cycle(tmp, None, verifier=QuoteVerifier())
        self.assertTrue(rec["ok"])
        after = {f.name: f.read_text(encoding="utf-8") for f in (tmp / "edges").glob("*.jsonl")}
        self.assertEqual(before, after)


class TestGaps(unittest.TestCase):
    def test_gap_analysis(self):
        h = HIGO(data_dir=REPO_DATA)
        h.seed()
        res = gaps.analyze(h.store)
        kinds = set(res["summary"])
        self.assertIn("quote_missing", kinds)
        self.assertIn("domain_coverage", kinds)
        self.assertIn("pending_review", kinds)
        pr = [t["priority"] for t in res["tasks"]]
        self.assertEqual(pr, sorted(pr, reverse=True))
        self.assertIn("| 유형 | 건수 |", gaps.to_markdown(res))


if __name__ == "__main__":
    unittest.main()
