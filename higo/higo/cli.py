"""HIGO 명령행 도구.

    python -m higo init                     # DB 생성 + Phase 1 seed
    python -m higo serve                    # 웹 UI + API (http://127.0.0.1:8180)
    python -m higo ask "자유라는 개념은 고대부터 현대까지 어떻게 변화했는가?"
    python -m higo connect person:aristotle person:jefferson
    python -m higo genealogy concept:freedom
    python -m higo compare person:marx person:nietzsche
    python -m higo dna person:kant
    python -m higo discover [--commit]
    python -m higo queue | review E00123 approve --actor 홍길동 --reason "원전 확인"
    python -m higo ingest 파일.txt --title ... --author person:x [--llm]
    python -m higo validate | stats | export cypher > higo.cypher

  자동 갱신 (1단계: 검증 기반)
    python -m higo data export              # 현재 온톨로지를 data/ 파일로 저장
    python -m higo gaps [--json]            # 공백 분석 — 다음에 보강할 곳
    python -m higo verify                   # 기존 증거의 URL·인용문 원문 대조
    python -m higo cycle --changeset p.json # 변경 묶음 적용 → 검증 → 보고서(data/runs/)
    python -m higo approve --run R… --actor 이름   # 주기 단위 묶음 승인
    python -m higo bench                    # 품질 기준 질문 채점

  자동 갱신 (2단계: 조사 에이전트)
    python -m higo research --budget 5 --max-tasks 8   # 조사 → 독립 검토 → 관문 → 보고서

데이터의 원본은 data/ 디렉터리의 텍스트 파일이다 (--db 를 주지 않으면 메모리에서 작업 후
변경 명령은 data/ 에 다시 저장한다).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import datafiles, export
from .core import HIGO
from .validation import ReviewError


def _p(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _resolve(h: HIGO, ref: str) -> str:
    if h.store.get_entity(ref):
        return ref
    hits = h.search(ref, k=1)
    if not hits:
        sys.exit(f"entity not found: {ref}")
    return hits[0]["id"]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="higo", description="Human Intellectual Genealogy Ontology")
    ap.add_argument("--db", default=":memory:", help="SQLite 캐시 경로 (기본: 메모리)")
    ap.add_argument("--data", default=str(datafiles.DEFAULT_DATA_DIR), help="온톨로지 데이터 디렉터리")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8180)
    s = sub.add_parser("ask")
    s.add_argument("question")
    s.add_argument("--no-llm", action="store_true")
    s.add_argument("--hyp", action="store_true", help="가설 관계도 포함")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("connect")
    s.add_argument("a")
    s.add_argument("b")
    s = sub.add_parser("genealogy")
    s.add_argument("concept")
    s = sub.add_parser("compare")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--topic")
    s = sub.add_parser("dna")
    s.add_argument("person")
    sub.add_parser("landscape")
    sub.add_parser("contradictions")
    sub.add_parser("cross-domain")
    s = sub.add_parser("discover")
    s.add_argument("--commit", action="store_true")
    sub.add_parser("queue")
    s = sub.add_parser("review")
    s.add_argument("edge")
    s.add_argument("action", choices=["approve", "reject", "contest", "propose"])
    s.add_argument("--actor", required=True)
    s.add_argument("--reason", default="")
    s = sub.add_parser("evidence")
    s.add_argument("edge")
    s.add_argument("--tier", type=int, required=True)
    s.add_argument("--source")
    s.add_argument("--citation", default="")
    s.add_argument("--locator", default="")
    s.add_argument("--quote", default="")
    s.add_argument("--contradicts", action="store_true")
    s.add_argument("--actor", default="human")
    s = sub.add_parser("ingest")
    s.add_argument("file")
    s.add_argument("--title")
    s.add_argument("--author")
    s.add_argument("--work")
    s.add_argument("--llm", action="store_true")
    s = sub.add_parser("search")
    s.add_argument("q")
    sub.add_parser("validate")
    sub.add_parser("stats")
    s = sub.add_parser("export")
    s.add_argument("fmt", choices=["json", "cypher", "turtle"])
    s = sub.add_parser("import")
    s.add_argument("file")
    s = sub.add_parser("snapshot")
    s.add_argument("version")
    s.add_argument("--note", default="")
    s = sub.add_parser("history")
    s.add_argument("id", nargs="?")
    s = sub.add_parser("data", help="데이터 파일 관리")
    s.add_argument("action", choices=["export", "check", "reseed"])
    s = sub.add_parser("gaps")
    s.add_argument("--json", action="store_true")
    s.add_argument("--limit", type=int, default=40)
    s = sub.add_parser("verify")
    s.add_argument("--edge", action="append", help="특정 관계의 증거만")
    s = sub.add_parser("cycle")
    s.add_argument("--changeset")
    s.add_argument("--no-reverify", action="store_true")
    s.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 보고서만 출력")
    s = sub.add_parser("approve")
    s.add_argument("--run", required=True)
    s.add_argument("--actor", required=True)
    s.add_argument("--reason", default="")
    sub.add_parser("bench")
    s = sub.add_parser("research", help="Claude 조사 에이전트로 한 주기 실행 (ANTHROPIC_API_KEY 필요)")
    s.add_argument("--budget", type=float, default=5.0, help="주기당 API 비용 상한 (달러)")
    s.add_argument("--max-tasks", type=int, default=8)
    s.add_argument("--model", default=None)
    s.add_argument("--no-review", action="store_true", help="독립 검토 생략 (권장하지 않음)")
    s.add_argument("--dry-run", action="store_true", help="조사는 하되 data/ 에 반영하지 않음")
    s.add_argument("--report", help="보고서를 이 경로에도 저장 (PR 본문용)")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .server import serve
        serve(args.db, args.host, args.port, data_dir=args.data)
        return
    if args.cmd == "research":
        from .agent import MODEL, research_changeset
        from .cycle import run_cycle
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            sys.exit("ANTHROPIC_API_KEY 가 필요합니다 (pip install anthropic 도 필요)")
        cs = research_changeset(args.data, budget_usd=args.budget, max_tasks=args.max_tasks,
                                model=args.model or MODEL, review=not args.no_review)
        cost = cs["agent"]["cost"]
        print(f"조사 완료: 제안 {len(cs['operations'])}건, 비용 ${cost['spent_usd']:.2f} / ${cost['budget_usd']:.2f}",
              file=sys.stderr)
        rec = run_cycle(args.data, cs, write=not args.dry_run)
        if not args.dry_run:
            (Path(args.data) / "runs" / f"{rec['run_id']}.changeset.json").write_text(
                json.dumps(cs, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if args.report:
            Path(args.report).write_text(rec["report"], encoding="utf-8")
        print(rec["report"])
        sys.exit(0 if rec["ok"] else 2)
    if args.cmd == "cycle":
        from .changeset import load_changeset
        from .cycle import run_cycle
        cs = load_changeset(args.changeset) if args.changeset else None
        rec = run_cycle(args.data, cs, reverify_existing=not args.no_reverify, write=not args.dry_run)
        print(rec["report"])
        if not args.dry_run:
            print(f"\n기록: {args.data}/runs/{rec['run_id']}.json · 보고서: {args.data}/runs/{rec['run_id']}.md",
                  file=sys.stderr)
        sys.exit(0 if rec["ok"] else 2)

    h = HIGO(args.db, data_dir=args.data)
    if args.cmd == "data" and args.action == "reseed":
        from .seed import load_seed
        load_seed(h.store)
        _p(h.export_data(args.data))
        return
    if args.cmd != "import":
        h.seed()
    mutating = {"review", "evidence", "ingest", "import", "snapshot", "approve", "verify"}
    r = h.reasoner
    if args.cmd == "init":
        _p(h.store.stats())
    elif args.cmd == "ask":
        res = h.ask(args.question, use_llm=not args.no_llm, include_hypotheses=args.hyp)
        if args.json:
            res.pop("graph", None)
            _p(res)
        else:
            print(res["answer"])
            print("\n--- trace ---")
            for t in res["trace"]:
                print(f"[{t['step']}] {t['detail']}")
    elif args.cmd == "connect":
        res = r.explain_connection(_resolve(h, args.a), _resolve(h, args.b))
        res.pop("graph")
        _p(res)
    elif args.cmd == "genealogy":
        res = r.concept_genealogy(_resolve(h, args.concept))
        res.pop("graph")
        _p(res)
    elif args.cmd == "compare":
        _p(r.compare(_resolve(h, args.a), _resolve(h, args.b), topic=args.topic, vector_index=h.vectors))
    elif args.cmd == "dna":
        _p(r.thinker_dna(_resolve(h, args.person)))
    elif args.cmd == "landscape":
        _p(r.landscape())
    elif args.cmd == "contradictions":
        res = r.contradiction_graph()
        res.pop("graph")
        _p(res)
    elif args.cmd == "cross-domain":
        _p(r.cross_domain())
    elif args.cmd == "discover":
        _p(h.discovery.run(commit=args.commit))
    elif args.cmd == "queue":
        for e in h.reviewer.queue():
            print(f"{e['id']}  [{e['epistemic_status']:>10}] {e['source_label']} —{e['predicate']}→ "
                  f"{e['target_label']}  conf={e['confidence']:.2f} origin={e['origin']}")
    elif args.cmd == "review":
        try:
            fn = {"approve": h.reviewer.approve, "reject": h.reviewer.reject,
                  "contest": lambda i, a, rsn: h.reviewer.contest(i, a, rsn),
                  "propose": lambda i, a, rsn: h.reviewer.transition(i, "proposed", a, rsn)}[args.action]
            _p(fn(args.edge, args.actor, args.reason))
        except ReviewError as exc:
            sys.exit(f"review failed: {exc}")
    elif args.cmd == "evidence":
        _p(h.store.add_evidence(args.edge, tier=args.tier, source_id=args.source, citation=args.citation,
                                locator=args.locator, quotation=args.quote,
                                stance="contradicts" if args.contradicts else "supports", added_by=args.actor))
        _p(h.store.get_edge(args.edge))
    elif args.cmd == "ingest":
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
        res = h.extractor.ingest(args.title or args.file, text, args.author, args.work, use_llm=args.llm)
        _p({k: v for k, v in res.items() if k != "candidates"} | {"candidates": len(res["candidates"])})
    elif args.cmd == "search":
        _p(h.search(args.q))
    elif args.cmd == "validate":
        _p(h.validate())
    elif args.cmd == "stats":
        _p(h.store.stats())
    elif args.cmd == "export":
        if args.fmt == "json":
            _p(export.to_json(h.store))
        elif args.fmt == "cypher":
            sys.stdout.write(export.to_cypher(h.store))
        else:
            sys.stdout.write(export.to_turtle(h.store))
    elif args.cmd == "import":
        with open(args.file, encoding="utf-8") as f:
            _p(export.import_json(h.store, json.load(f)))
    elif args.cmd == "snapshot":
        _p(h.store.snapshot_version(args.version, args.note))
    elif args.cmd == "history":
        _p(h.store.history(args.id))
    elif args.cmd == "data":
        if args.action == "export":
            _p(h.export_data(args.data))
        else:
            _p({"loaded": h.store.stats(), "validation": h.validate()["ok"]})
    elif args.cmd == "gaps":
        from . import gaps
        res = gaps.analyze(h.store, gaps.load_roadmap(args.data), limit=args.limit)
        _p(res) if args.json else print(gaps.to_markdown(res, top=args.limit))
    elif args.cmd == "verify":
        from .verify import QuoteVerifier
        ids = None
        if args.edge:
            ids = [ev["id"] for e in args.edge for ev in h.store.list_evidence(e)]
        _p(QuoteVerifier().verify_store(h.store, ids)["counts"])
    elif args.cmd == "approve":
        from .changeset import approve_run
        try:
            _p(approve_run(h.store, args.run, args.actor, args.reason))
        except ReviewError as exc:
            sys.exit(f"approve failed: {exc}")
    elif args.cmd == "bench":
        from .bench import load_benchmark, run_benchmark
        res = run_benchmark(h, load_benchmark(f"{args.data}/benchmark.json"))
        print(f"품질 기준 점수: {res['score']:.1%} ({res['n']}문항)")
        for i in res["items"]:
            print(f"  {'✓' if not i['failed'] else '✗'} {i['question']}" + (f"  — {'; '.join(i['failed'])}" if i["failed"] else ""))
    if args.cmd in mutating and args.db == ":memory:" and datafiles.has_data(args.data):
        h.export_data(args.data)
        print(f"(data/ 에 저장됨: {args.data})", file=sys.stderr)


if __name__ == "__main__":
    main()
