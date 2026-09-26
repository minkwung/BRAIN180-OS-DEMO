"""품질 기준 질문 세트 — 매 주기 전후로 답변 품질을 측정한다.

각 질문은 기대하는 질문 유형(intent), 답변 근거에 반드시 등장해야 하는 노드(must_link),
답변 본문에 들어가야 하는 표현(must_mention), 들어가면 안 되는 표현(must_not)을 가진다.
LLM 없이(템플릿 합성) 채점하므로 결과가 결정적이다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_BENCH = Path(__file__).resolve().parent.parent / "data" / "benchmark.json"


def load_benchmark(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else DEFAULT_BENCH
    return json.loads(p.read_text(encoding="utf-8"))["questions"] if p.is_file() else []


def _grounded_ids(result: dict) -> set[str]:
    ids = {n["id"] for n in result.get("graph", {}).get("nodes", [])}
    ids |= {x["id"] for x in result.get("linked", [])}
    ids |= {p["id"] for p in result.get("propositions", [])}
    ids |= set(re.findall(r"(?:person|concept|work|prop|school):[\w\-]+", json.dumps(result.get("analysis", {}),
                                                                                 ensure_ascii=False)))
    return ids


def run_benchmark(higo, questions: list[dict]) -> dict:
    items = []
    for q in questions:
        r = higo.ask(q["question"], use_llm=False)
        checks = []
        if q.get("intent"):
            checks.append(("intent", r["intent"] == q["intent"], f"{r['intent']} (기대 {q['intent']})"))
        ids = _grounded_ids(r)
        for nid in q.get("must_link", []):
            checks.append(("link", nid in ids, nid))
        for s in q.get("must_mention", []):
            checks.append(("mention", s in r["answer"], s))
        for s in q.get("must_not", []):
            checks.append(("must_not", s not in r["answer"], s))
        checks.append(("citations", not r["unsupported_citations"], "근거 없는 인용 없음"))
        passed = sum(1 for _, ok, _ in checks if ok)
        items.append({"id": q["id"], "question": q["question"], "score": passed / len(checks),
                      "failed": [f"{k}: {d}" for k, ok, d in checks if not ok]})
    score = sum(i["score"] for i in items) / len(items) if items else 0.0
    return {"score": round(score, 4), "n": len(items), "items": items}
