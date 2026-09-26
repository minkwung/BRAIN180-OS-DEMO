"""HIGO HTTP API + 웹 UI 서버 (표준 라이브러리 전용).

    python -m higo serve --db higo.db --port 8180
"""
from __future__ import annotations

import json
import mimetypes
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import export
from . import ontology as O
from .core import HIGO
from .ids import make_id
from .validation import ReviewError, validate_edge

WEB_DIR = Path(__file__).parent / "web"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _routes():
    """(method, regex, handler_name) 목록."""
    r = [
        ("GET", r"/api/stats", "stats"),
        ("GET", r"/api/schema", "schema"),
        ("GET", r"/api/llm", "llm_status"),
        ("GET", r"/api/entities", "list_entities"),
        ("POST", r"/api/entities", "create_entity"),
        ("GET", r"/api/entities/(?P<id>[^/]+)", "get_entity"),
        ("GET", r"/api/entities/(?P<id>[^/]+)/neighbors", "neighbors"),
        ("GET", r"/api/entities/(?P<id>[^/]+)/history", "entity_history"),
        ("GET", r"/api/graph", "graph"),
        ("GET", r"/api/search", "search"),
        ("POST", r"/api/edges", "create_edge"),
        ("GET", r"/api/edges/(?P<id>[^/]+)", "get_edge"),
        ("POST", r"/api/edges/(?P<id>[^/]+)/evidence", "add_evidence"),
        ("POST", r"/api/edges/(?P<id>[^/]+)/review", "review_edge"),
        ("GET", r"/api/connection", "connection"),
        ("GET", r"/api/genealogy/(?P<id>[^/]+)", "genealogy"),
        ("GET", r"/api/contradictions", "contradictions"),
        ("GET", r"/api/cross-domain", "cross_domain"),
        ("GET", r"/api/dna/(?P<id>[^/]+)", "dna"),
        ("GET", r"/api/landscape", "landscape"),
        ("GET", r"/api/compare", "compare"),
        ("GET", r"/api/timeline", "timeline"),
        ("POST", r"/api/ask", "ask"),
        ("POST", r"/api/discover", "discover"),
        ("POST", r"/api/discover/commit", "discover_commit"),
        ("GET", r"/api/review/queue", "review_queue"),
        ("POST", r"/api/extract", "extract"),
        ("GET", r"/api/candidates", "candidates"),
        ("POST", r"/api/candidates/(?P<id>[^/]+)/(?P<action>approve|reject)", "candidate_action"),
        ("GET", r"/api/documents", "documents"),
        ("GET", r"/api/validate", "validate"),
        ("GET", r"/api/history", "history"),
        ("GET", r"/api/versions", "versions"),
        ("POST", r"/api/versions", "snapshot"),
        ("GET", r"/api/export/(?P<fmt>json|cypher|turtle)", "export"),
        ("GET", r"/api/gaps", "gaps"),
        ("GET", r"/api/runs", "runs"),
        ("GET", r"/api/runs/(?P<id>R[\w\-]+)", "run_detail"),
        ("POST", r"/api/runs/(?P<id>R[\w\-]+)/approve", "run_approve"),
    ]
    return [(m, re.compile("^" + p + "$"), h) for m, p, h in r]


ROUTES = _routes()


class Api:
    """HTTP 와 무관한 API 로직 — 테스트에서 직접 호출할 수 있다."""

    def __init__(self, higo: HIGO):
        self.h = higo

    def persist(self) -> None:
        """웹 UI 에서 한 검토·수정을 data/ 파일에 반영한다 (Ontology as Code)."""
        from . import datafiles
        if self.h.data_dir and datafiles.has_data(self.h.data_dir) and self.h.store.path == ":memory:":
            self.h.export_data()

    def dispatch(self, method: str, path: str, query: dict, body: dict | None):
        for m, rx, name in ROUTES:
            if m != method:
                continue
            match = rx.match(path)
            if match:
                params = {k: unquote(v) for k, v in match.groupdict().items()}
                return getattr(self, name)(query=query, body=body or {}, **params)
        raise ApiError(404, f"no route: {method} {path}")

    @staticmethod
    def _q(query: dict, key: str, default=None):
        v = query.get(key)
        if not v:
            return default
        return v[0] if isinstance(v, list) else v

    def _need(self, id: str) -> None:
        if not self.h.store.get_entity(id):
            raise ApiError(404, f"entity not found: {id}")

    # ------------------------------------------------------------ basics
    def stats(self, **_):
        return self.h.store.stats()

    def schema(self, **_):
        return O.schema_as_dict()

    def llm_status(self, **_):
        return self.h.llm.status()

    def list_entities(self, query, **_):
        return self.h.store.list_entities(type=self._q(query, "type"), q=self._q(query, "q"),
                                          limit=int(self._q(query, "limit", 2000)))

    def get_entity(self, query, id, **_):
        self._need(id)
        return self.h.reasoner.entity_detail(id)

    def neighbors(self, query, id, **_):
        self._need(id)
        depth = int(self._q(query, "depth", 1))
        statuses = self._statuses(query)
        return self.h.graph.refresh().subgraph([id], depth=depth, statuses=statuses)

    def entity_history(self, query, id, **_):
        return self.h.store.history(id)

    def _statuses(self, query):
        s = self._q(query, "status")
        if s == "all":
            return None
        if s:
            return tuple(s.split(","))
        return ("accepted", "revised", "proposed", "contested")

    def graph(self, query, **_):
        types = self._q(query, "types")
        preds = self._q(query, "predicates")
        return self.h.graph.refresh().full_view(types=types.split(",") if types else None,
                                                statuses=self._statuses(query),
                                                predicates=preds.split(",") if preds else None)

    def search(self, query, **_):
        q = self._q(query, "q", "")
        types = self._q(query, "types")
        return self.h.search(q, k=int(self._q(query, "k", 15)), types=types.split(",") if types else None)

    # ----------------------------------------------------------- writes
    def create_entity(self, body, **_):
        typ = body.get("type")
        label = body.get("label")
        if typ not in O.ENTITY_TYPES or not label:
            raise ApiError(400, "type and label required")
        eid = body.get("id") or make_id(typ, label)
        return self.h.store.upsert_entity(eid, typ, label, label_ko=body.get("label_ko"),
                                          aliases=body.get("aliases") or [], description=body.get("description", ""),
                                          props=body.get("props") or {}, start_year=body.get("start_year"),
                                          end_year=body.get("end_year"), origin="human",
                                          actor=body.get("actor", "human"))

    def create_edge(self, body, **_):
        for k in ("source", "predicate", "target"):
            if not body.get(k):
                raise ApiError(400, f"{k} required")
        if body["predicate"] not in O.RELATION_TYPES:
            raise ApiError(400, f"unknown predicate {body['predicate']}")
        probe = {"source": body["source"], "predicate": body["predicate"], "target": body["target"],
                 "epistemic_status": "proposed", "evidence_status": body.get("evidence_status", "direct")}
        rep = validate_edge(self.h.store, probe)
        if not rep.ok:
            raise ApiError(400, "; ".join(i.message for i in rep.issues if i.level == "error"))
        edge = self.h.store.add_edge(body["source"], body["predicate"], body["target"],
                                     evidence_status=body.get("evidence_status", "direct"),
                                     epistemic_status="proposed", origin="human", note=body.get("note", ""),
                                     actor=body.get("actor", "human"))
        for ev in body.get("evidence", []):
            self.h.store.add_evidence(edge["id"], added_by=body.get("actor", "human"), **ev)
        return self.h.store.get_edge(edge["id"], with_evidence=True)

    def get_edge(self, query, id, **_):
        e = self.h.store.get_edge(id, with_evidence=True)
        if not e:
            raise ApiError(404, "edge not found")
        g = self.h.graph.refresh()
        e["source_label"], e["target_label"] = g.label(e["source"]), g.label(e["target"])
        rel = O.RELATION_TYPES[e["predicate"]]
        e["predicate_ko"], e["category"] = rel.label_ko, rel.category
        e["history"] = self.h.store.history(id)
        e["validation"] = validate_edge(self.h.store, e).as_dict()
        return e

    def add_evidence(self, body, id, **_):
        try:
            tier = int(body.get("tier", 0))
            return self.h.store.add_evidence(
                id, tier=tier, source_id=body.get("source_id") or None, citation=body.get("citation", ""),
                stance=body.get("stance", "supports"), locator=body.get("locator", ""),
                quotation=body.get("quotation", ""), interpretation=body.get("interpretation", ""),
                added_by=body.get("actor", "human"))
        except (ValueError, KeyError) as exc:
            raise ApiError(400, str(exc)) from exc

    def review_edge(self, body, id, **_):
        action = body.get("action")
        actor = body.get("actor", "")
        reason = body.get("reason", "")
        rv = self.h.reviewer
        try:
            if action == "approve":
                return rv.approve(id, actor, reason)
            if action == "reject":
                return rv.reject(id, actor, reason)
            if action == "contest":
                return rv.contest(id, actor, reason, body.get("counter_evidence"))
            if action == "revise":
                return rv.revise(id, actor, reason, **(body.get("changes") or {}))
            if action == "propose":
                return rv.transition(id, "proposed", actor, reason)
        except ReviewError as exc:
            raise ApiError(400, str(exc)) from exc
        raise ApiError(400, "action must be approve|reject|contest|revise|propose")

    # -------------------------------------------------------- reasoning
    def connection(self, query, **_):
        a, b = self._q(query, "a"), self._q(query, "b")
        self._need(a)
        self._need(b)
        return self.h.reasoner.explain_connection(a, b, max_depth=int(self._q(query, "depth", 5)),
                                                  include_hypotheses=self._q(query, "hyp") == "1")

    def genealogy(self, query, id, **_):
        self._need(id)
        return self.h.reasoner.concept_genealogy(id)

    def contradictions(self, **_):
        return self.h.reasoner.contradiction_graph()

    def cross_domain(self, **_):
        return self.h.reasoner.cross_domain()

    def dna(self, query, id, **_):
        self._need(id)
        return self.h.reasoner.thinker_dna(id)

    def landscape(self, query, **_):
        ids = self._q(query, "ids")
        return self.h.reasoner.landscape(ids.split(",") if ids else None)

    def compare(self, query, **_):
        a, b = self._q(query, "a"), self._q(query, "b")
        self._need(a)
        self._need(b)
        return self.h.reasoner.compare(a, b, topic=self._q(query, "topic"), vector_index=self.h.vectors)

    def timeline(self, query, **_):
        types = self._q(query, "types", "Person,Work,Event")
        return self.h.reasoner.timeline(types.split(","))

    def ask(self, body, **_):
        q = (body.get("question") or "").strip()
        if not q:
            raise ApiError(400, "question required")
        return self.h.ask(q, use_llm=body.get("use_llm", True), include_hypotheses=bool(body.get("include_hypotheses")))

    # -------------------------------------------------------- discovery
    def discover(self, body, **_):
        return self.h.discovery.run(commit=bool(body.get("commit")))

    def discover_commit(self, body, **_):
        try:
            return self.h.discovery.commit(body)
        except (ValueError, KeyError) as exc:
            raise ApiError(400, str(exc)) from exc

    def review_queue(self, **_):
        return self.h.reviewer.queue()

    # ------------------------------------------------------- extraction
    def extract(self, body, **_):
        text = body.get("text", "")
        if not text.strip():
            raise ApiError(400, "text required")
        return self.h.extractor.ingest(body.get("title") or "untitled", text, body.get("author_id") or None,
                                       body.get("work_id") or None, use_llm=bool(body.get("use_llm")))

    def candidates(self, query, **_):
        return self.h.store.list_candidates(self._q(query, "status", "pending"))

    def candidate_action(self, body, id, action, **_):
        actor = body.get("actor", "")
        if not actor or actor.startswith(("ai", "system")):
            raise ApiError(400, "검토자(actor) 이름이 필요합니다")
        try:
            if action == "approve":
                return self.h.extractor.approve_candidate(id, actor, body.get("overrides"))
            self.h.extractor.reject_candidate(id, actor)
            return {"candidate": id, "status": "rejected"}
        except (ValueError, KeyError) as exc:
            raise ApiError(400, str(exc)) from exc

    def documents(self, **_):
        return self.h.store.list_documents()

    # ---------------------------------------------------- governance
    def validate(self, **_):
        return self.h.validate()

    def history(self, query, **_):
        return self.h.store.history(limit=int(self._q(query, "limit", 100)))

    def versions(self, **_):
        return self.h.store.list_versions()

    def snapshot(self, body, **_):
        if not body.get("version"):
            raise ApiError(400, "version required")
        return self.h.store.snapshot_version(body["version"], body.get("note", ""))

    # ------------------------------------------------------ autonomy
    def _runs_dir(self):
        from pathlib import Path
        return Path(self.h.data_dir) / "runs" if self.h.data_dir else None

    def gaps(self, query, **_):
        from . import gaps
        return gaps.analyze(self.h.store, gaps.load_roadmap(self.h.data_dir), limit=int(self._q(query, "limit", 40)))

    def runs(self, **_):
        d = self._runs_dir()
        if not d or not d.is_dir():
            return []
        out = []
        for f in sorted(d.glob("R*.json"), reverse=True):
            rec = json.loads(f.read_text(encoding="utf-8"))
            results = (rec.get("changeset") or {}).get("results", [])
            counts: dict = {}
            for r in results:
                counts[r["risk"]] = counts.get(r["risk"], 0) + 1
            pending = sum(1 for e in self.h.store.list_edges(statuses=["proposed"])
                          if (e.get("props") or {}).get("run") == rec["run_id"])
            out.append({"run_id": rec["run_id"], "ok": rec.get("ok"), "started": rec.get("started"),
                        "risk_counts": counts, "pending_batch": pending,
                        "score": (rec.get("benchmark_after") or {}).get("score")})
        return out

    def run_detail(self, query, id, **_):
        d = self._runs_dir()
        f = d / f"{id}.json" if d else None
        if not f or not f.is_file():
            raise ApiError(404, f"run not found: {id}")
        rec = json.loads(f.read_text(encoding="utf-8"))
        md = (d / f"{id}.md")
        rec["report"] = md.read_text(encoding="utf-8") if md.is_file() else ""
        return rec

    def run_approve(self, body, id, **_):
        from .changeset import approve_run
        try:
            return approve_run(self.h.store, id, body.get("actor", ""), body.get("reason", ""))
        except ReviewError as exc:
            raise ApiError(400, str(exc)) from exc

    def export(self, query, fmt, **_):
        if fmt == "json":
            return export.to_json(self.h.store)
        if fmt == "cypher":
            return ("text/plain; charset=utf-8", export.to_cypher(self.h.store))
        return ("text/turtle; charset=utf-8", export.to_turtle(self.h.store))


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HIGO/0.1"

        def log_message(self, fmt, *args):  # 조용히
            pass

        def _send(self, status: int, payload, content_type: str = "application/json; charset=utf-8"):
            if isinstance(payload, (bytes, bytearray)):
                data = bytes(payload)
            elif isinstance(payload, str) and not content_type.startswith("application/json"):
                data = payload.encode("utf-8")
            else:
                data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str):
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                return self._static(url.path)
            body = None
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, {"error": "invalid JSON"})
            try:
                result = api.dispatch(method, url.path, parse_qs(url.query), body)
                if method == "POST" and url.path not in ("/api/ask", "/api/discover"):
                    api.persist()
                if isinstance(result, tuple):
                    ctype, text = result
                    return self._send(200, text, ctype)
                self._send(200, result)
            except ApiError as exc:
                self._send(exc.status, {"error": str(exc)})
            except KeyError as exc:
                self._send(404, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover
                traceback.print_exc()
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        def _static(self, path: str):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve() or not target.is_file():
                return self._send(404, {"error": "not found"})
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def serve(db: str = ":memory:", host: str = "127.0.0.1", port: int = 8180, seed: bool = True,
          data_dir=None) -> None:
    h = HIGO(db, data_dir=data_dir)
    if seed:
        h.seed()
    httpd = ThreadingHTTPServer((host, port), make_handler(Api(h)))
    print(f"HIGO serving on http://{host}:{port}  (db={db}, data={data_dir}, llm={h.llm.status()})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
