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
"""
from __future__ import annotations

import argparse
import json
import sys

from . import export
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
    ap.add_argument("--db", default="higo.db")
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
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .server import serve
        serve(args.db, args.host, args.port)
        return

    h = HIGO(args.db)
    if args.cmd != "import":
        h.seed()
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


if __name__ == "__main__":
    main()
