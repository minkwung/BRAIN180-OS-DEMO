"""2단계 조사 에이전트 테스트 — 실제 API 대신 각본대로 응답하는 가짜 클라이언트를 쓴다."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

os.environ["HIGO_LLM"] = "off"

from higo import HIGO  # noqa: E402
from higo.agent import (CostMeter, Researcher, TaskLog, _sanitize_for_echo, research_changeset,  # noqa: E402
                        select_tasks, validate_operation)
from higo.cycle import run_cycle  # noqa: E402
from higo.verify import QuoteVerifier  # noqa: E402

from test_autonomy import REPO_DATA, LocalSite  # noqa: E402

TEST_SOURCES = {"allowed_domains": ["127.0.0.1", "plato.stanford.edu"], "tier_hints": {}}


def usage(inp=10_000, out=1_000, cr=0, cw=0, searches=0):
    return NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=cr, cache_creation_input_tokens=cw,
              server_tool_use=NS(web_search_requests=searches))


def resp(stop, content, **u):
    return NS(stop_reason=stop, content=content, usage=usage(**u), model="claude-opus-5")


def tool_use(i, name, args):
    return NS(type="tool_use", id=i, name=name, input=args)


def text(t):
    return NS(type="text", text=t)


class FakeClient:
    """researcher 호출과 reviewer 호출(구조화 출력)을 구분해 각본을 돌려준다."""

    def __init__(self, research_script, review_fn):
        self.research_script = list(research_script)
        self.review_fn = review_fn
        self.calls = []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if (kw.get("output_config") or {}).get("format"):
            return self.review_fn(kw)
        if not self.research_script:
            return resp("end_turn", [text("더 할 일 없음")])
        item = self.research_script.pop(0)
        return item(kw) if callable(item) else item


def proposals(base):
    return [
        {"op": "add_entity", "entity": {"id": "person:ferguson", "type": "Person", "label": "Adam Ferguson",
                                        "label_ko": "애덤 퍼거슨", "start_year": 1723, "end_year": 1816},
         "evidence": [{"tier": 1, "url": base + "/ferguson.html", "quotation": "born in 1723 and died in 1816"}],
         "rationale": "분야 확장"},
        {"op": "add_edge", "edge": {"source": "person:ferguson", "predicate": "influenced", "target": "person:hayek",
                                    "evidence_status": "direct"},
         "evidence": [{"tier": 1, "url": base + "/ferguson.html",
                       "quotation": "the result of human action, but not the execution of any human design"}]},
        {"op": "add_edge", "edge": {"source": "person:ferguson", "predicate": "inspired", "target": "person:hume"}},
        {"op": "add_evidence", "edge_id": "E01393",
         "evidence": [{"tier": 1, "url": base + "/hume.txt", "quotation": "an invented sentence that is not there"}]},
    ]


class TestCostMeter(unittest.TestCase):
    def test_pricing(self):
        m = CostMeter(10)
        m.record(NS(usage=usage(inp=1_000_000, out=0), model="claude-opus-5"))
        self.assertAlmostEqual(m.spent_usd, 5.0)
        m.record(NS(usage=usage(inp=0, out=0, cr=1_000_000), model="claude-opus-5"))
        self.assertAlmostEqual(m.spent_usd, 5.5)
        m.record(NS(usage=usage(inp=0, out=0, cw=1_000_000), model="claude-opus-5"))
        self.assertAlmostEqual(m.spent_usd, 11.75)
        m2 = CostMeter(10)
        m2.record(NS(usage=usage(inp=0, out=0, searches=100), model="claude-opus-5"))
        self.assertAlmostEqual(m2.spent_usd, 1.0)
        m3 = CostMeter(10)
        m3.record(NS(usage=usage(inp=1_000_000, out=0), model="some-future-model"))
        self.assertGreaterEqual(m3.spent_usd, 5.0)  # 모르는 모델은 보수적으로
        self.assertFalse(CostMeter(0.1).can_afford())

    def test_sanitize_fallback(self):
        blocks = [NS(type="thinking"), NS(type="tool_use", id="a"), NS(type="text", text="x"),
                  NS(type="server_tool_use", id="s1"), NS(type="web_search_tool_result", tool_use_id="s1"),
                  NS(type="server_tool_use", id="s2"), NS(type="fallback"), NS(type="text", text="y"),
                  NS(type="tool_use", id="b")]
        kept = [b.type + (getattr(b, "id", "") or "") for b in _sanitize_for_echo(blocks)]
        self.assertEqual(kept, ["text", "server_tool_uses1", "web_search_tool_result", "fallback", "text", "tool_useb"])
        plain = [NS(type="text", text="a")]
        self.assertIs(_sanitize_for_echo(plain), plain)


class TestResearcher(unittest.TestCase):
    def setUp(self):
        self.h = HIGO(data_dir=REPO_DATA)
        self.h.seed()

    def test_validate_operation_messages(self):
        bad = validate_operation(self.h, {"op": "add_edge", "edge": {"source": "person:nobody", "predicate": "x",
                                                                      "target": "person:kant"}}, set())
        self.assertTrue(any("predicate" in b for b in bad) and any("does not exist" in b for b in bad))
        self.assertEqual(validate_operation(self.h, {"op": "delete_everything"}, set())[0][:6], "op mus")
        ev = {"op": "add_evidence", "edge_id": "E01393", "evidence": [{"tier": 1, "quotation": "q",
                                                                       "url": "https://random-blog.example/post"}]}
        allowed = ["plato.stanford.edu", "www.gutenberg.org"]
        self.assertTrue(any("allowed source" in x for x in validate_operation(self.h, ev, set(), allowed)))
        ev["evidence"][0]["url"] = "https://gutenberg.org/ebooks/1"
        self.assertEqual(validate_operation(self.h, ev, set(), allowed), [])

    def test_loop_tools_pause_and_review(self):
        with LocalSite() as site:
            script = [
                resp("tool_use", [text("찾아보자"), tool_use("t1", "search_ontology", {"query": "하이에크"})]),
                resp("pause_turn", [NS(type="server_tool_use", id="s1", name="web_search", input={"query": "Ferguson"})],
                     searches=1),
                resp("tool_use", [tool_use("t2", "propose_changes", {"operations": proposals(site.base)})]),
                resp("end_turn", [text("퍼거슨과 하이에크 연결을 제안했다.")]),
            ]

            def review(kw):
                return resp("end_turn", [text(json.dumps({"reviews": [
                    {"index": 0, "verdict": "keep", "reason": "생몰년 일치"},
                    {"index": 1, "verdict": "downgrade", "reason": "인용은 유사한 표현일 뿐 직접 영향의 근거는 아님"},
                    {"index": 2, "verdict": "keep", "reason": "?"}]}))])

            client = FakeClient(script, review)
            meter = CostMeter(5.0)
            agent = Researcher(self.h, meter, client=client, sources=TEST_SOURCES)
            task = {"type": "domain_coverage", "label_ko": "분야 확장", "action": "경제학 인물 추가", "target": "domain:economics"}
            log = TaskLog(task)
            ops = agent.research(task, log)
            self.assertEqual(log.requests, 4)
            self.assertEqual(log.stop, "end_turn")
            self.assertEqual(len(ops), 3)  # 잘못된 predicate 는 도구가 거부
            reviewed = agent.review(task, ops, log)
            self.assertEqual((log.kept, log.downgraded, log.dropped), (2, 1, 0))

            first = client.calls[0]
            self.assertEqual(first["fallbacks"], "default")
            self.assertEqual(first["cache_control"], {"type": "ephemeral"})
            names = {t["name"] for t in first["tools"]}
            self.assertTrue({"web_search", "web_fetch", "propose_changes", "search_ontology"} <= names)
            ws = next(t for t in first["tools"] if t["name"] == "web_search")
            self.assertIn("plato.stanford.edu", ws["allowed_domains"])
            # pause_turn 뒤에는 사용자 메시지를 덧붙이지 않고 그대로 이어 보낸다
            third = client.calls[2]["messages"]
            self.assertEqual(third[-1]["role"], "assistant")
            self.assertEqual(meter.web_searches, 1)

            # 1단계 관문 통과
            tmp = Path(tempfile.mkdtemp()) / "data"
            shutil.copytree(REPO_DATA, tmp)
            rec = run_cycle(tmp, {"agent": {"model": "fake", "cost": meter.summary(),
                                            "tasks": []}, "operations": reviewed}, verifier=QuoteVerifier())
        self.assertTrue(rec["ok"])
        outcomes = {r["index"]: (r["risk"], r["outcome"]) for r in rec["changeset"]["results"]}
        self.assertEqual(outcomes[0], ("low", "applied_accepted"))
        self.assertEqual(outcomes[1], ("high", "applied_hypothesis"))
        self.assertEqual(outcomes[2], ("rejected", "rejected"))   # 날조 인용
        h2 = HIGO(data_dir=tmp)
        h2.seed()
        infl = h2.store.find_edge("person:ferguson", "influenced", "person:hayek")
        self.assertEqual((infl["epistemic_status"], infl["evidence_status"]), ("hypothesis", "inferred"))
        self.assertIn("독립 검토 강등", infl["note"])
        self.assertIn("조사 비용", rec["report"])

    def test_downgraded_fact_is_not_auto_accepted(self):
        with LocalSite() as site:
            op = proposals(site.base)[0]
            script = [resp("tool_use", [tool_use("t", "propose_changes", {"operations": [op]})]),
                      resp("end_turn", [text("끝")])]
            client = FakeClient(script, lambda kw: resp("end_turn", [text(json.dumps(
                {"reviews": [{"index": 0, "verdict": "downgrade", "reason": "출처가 약함"}]}))]))
            agent = Researcher(self.h, CostMeter(5), client=client, sources=TEST_SOURCES)
            task = {"type": "x", "label_ko": "x", "action": "x"}
            log = TaskLog(task)
            ops = agent.review(task, agent.research(task, log), log)
            tmp = Path(tempfile.mkdtemp()) / "data"
            shutil.copytree(REPO_DATA, tmp)
            rec = run_cycle(tmp, {"operations": ops}, verifier=QuoteVerifier())
        self.assertEqual(rec["changeset"]["results"][0]["risk"], "medium")

    def test_budget_stops_before_overspending(self):
        endless = [lambda kw: resp("tool_use", [tool_use("t", "search_ontology", {"query": "칸트"})],
                                   inp=40_000, out=4_000)] * 50
        client = FakeClient(endless, lambda kw: resp("end_turn", [text('{"reviews": []}')]))
        tmp = Path(tempfile.mkdtemp()) / "data"
        shutil.copytree(REPO_DATA, tmp)
        cs = research_changeset(tmp, budget_usd=1.0, max_tasks=4, client=client)
        cost = cs["agent"]["cost"]
        self.assertLessEqual(cost["spent_usd"], 1.0)
        self.assertTrue(any(t["stop"] == "budget" for t in cs["agent"]["tasks"]))

    def test_task_selection_mixes_types(self):
        tasks = select_tasks(self.h, REPO_DATA, 6)
        self.assertEqual(len(tasks), 6)
        self.assertGreaterEqual(len({t["type"] for t in tasks}), 3)


if __name__ == "__main__":
    unittest.main()
