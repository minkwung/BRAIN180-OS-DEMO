"""SQLite 기반 온톨로지 저장소.

Graph DB(Neo4j 등)로 옮기기 전 단계의 참조 구현이다. 엔티티·관계·증거·변경이력·
추출 후보·문서·온톨로지 버전을 저장하고, 모든 변경을 history 테이블에 남긴다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterable

from . import ontology as O
from .confidence import compute_confidence

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    label_ko TEXT,
    aliases TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    props TEXT DEFAULT '{}',
    start_year INTEGER,
    end_year INTEGER,
    origin TEXT DEFAULT 'human',
    status TEXT DEFAULT 'accepted',
    version INTEGER DEFAULT 1,
    created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,
    target TEXT NOT NULL REFERENCES entities(id),
    props TEXT DEFAULT '{}',
    evidence_status TEXT DEFAULT 'direct',
    epistemic_status TEXT DEFAULT 'proposed',
    confidence REAL DEFAULT 0,
    confidence_override REAL,
    origin TEXT DEFAULT 'human',
    note TEXT DEFAULT '',
    valid_from INTEGER, valid_to INTEGER,
    version INTEGER DEFAULT 1,
    created_at REAL, updated_at REAL,
    UNIQUE(source, predicate, target)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_pred ON edges(predicate);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    edge_id TEXT NOT NULL REFERENCES edges(id) ON DELETE CASCADE,
    source_id TEXT REFERENCES entities(id),
    citation TEXT DEFAULT '',
    tier INTEGER NOT NULL,
    stance TEXT DEFAULT 'supports',
    locator TEXT DEFAULT '',
    quotation TEXT DEFAULT '',
    interpretation TEXT DEFAULT '',
    added_by TEXT DEFAULT 'seed',
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_evidence_edge ON evidence(edge_id);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_kind TEXT, object_id TEXT, action TEXT,
    before TEXT, after TEXT, actor TEXT, reason TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS idx_history_obj ON history(object_id);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, title TEXT, author_id TEXT, work_id TEXT,
    text TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,          -- entity | edge | proposition
    payload TEXT NOT NULL,
    origin TEXT DEFAULT 'extraction',
    document_id TEXT,
    score REAL DEFAULT 0,
    status TEXT DEFAULT 'pending',   -- pending | approved | rejected
    created_at REAL, reviewed_by TEXT, reviewed_at REAL
);
CREATE TABLE IF NOT EXISTS ontology_versions (
    version TEXT PRIMARY KEY, note TEXT, counts TEXT, created_at REAL
);
"""


def _now() -> float:
    return time.time()


def _loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


class Store:
    """Thread-safe SQLite 저장소. 쓰기 연산은 하나의 lock 으로 직렬화한다."""

    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA_SQL)
        self._revision = 0  # 그래프 캐시 무효화용
        if self.get_meta("schema_version") is None:
            self.set_meta("schema_version", O.SCHEMA_VERSION)

    # ------------------------------------------------------------------ meta
    @property
    def revision(self) -> int:
        return self._revision

    def _bump(self) -> None:
        self._revision += 1

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                self._bump()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def _next_id(self, counter: str, prefix: str, width: int = 5) -> str:
        with self._lock:
            cur = int(self.get_meta(f"counter:{counter}") or 0) + 1
            self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                               (f"counter:{counter}", str(cur)))
            return f"{prefix}{cur:0{width}d}"

    def _log(self, c, kind: str, oid: str, action: str, before: Any, after: Any,
             actor: str = "system", reason: str = "") -> None:
        c.execute(
            "INSERT INTO history(object_kind, object_id, action, before, after, actor, reason, ts)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (kind, oid, action, json.dumps(before, ensure_ascii=False) if before is not None else None,
             json.dumps(after, ensure_ascii=False) if after is not None else None, actor, reason, _now()),
        )

    # -------------------------------------------------------------- entities
    def upsert_entity(self, id: str, type: str, label: str, *, label_ko: str | None = None,
                      aliases: Iterable[str] = (), description: str = "", props: dict | None = None,
                      start_year: int | None = None, end_year: int | None = None,
                      origin: str = "human", status: str = "accepted", actor: str = "system") -> dict:
        if type not in O.ENTITY_TYPES:
            raise ValueError(f"unknown entity type: {type}")
        existing = self.get_entity(id)
        now = _now()
        data = dict(type=type, label=label, label_ko=label_ko, aliases=json.dumps(list(aliases), ensure_ascii=False),
                    description=description, props=json.dumps(props or {}, ensure_ascii=False),
                    start_year=start_year, end_year=end_year, origin=origin, status=status)
        with self.tx() as c:
            if existing:
                c.execute(
                    "UPDATE entities SET type=:type, label=:label, label_ko=:label_ko, aliases=:aliases,"
                    " description=:description, props=:props, start_year=:start_year, end_year=:end_year,"
                    " origin=:origin, status=:status, version=version+1, updated_at=:now WHERE id=:id",
                    {**data, "now": now, "id": id})
                self._log(c, "entity", id, "update", existing, data, actor)
            else:
                c.execute(
                    "INSERT INTO entities(id, type, label, label_ko, aliases, description, props, start_year,"
                    " end_year, origin, status, created_at, updated_at) VALUES (:id, :type, :label, :label_ko,"
                    " :aliases, :description, :props, :start_year, :end_year, :origin, :status, :now, :now)",
                    {**data, "now": now, "id": id})
                self._log(c, "entity", id, "create", None, data, actor)
        return self.get_entity(id)  # type: ignore[return-value]

    def _entity_row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["aliases"] = _loads(d["aliases"], [])
        d["props"] = _loads(d["props"], {})
        return d

    def get_entity(self, id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM entities WHERE id=?", (id,)).fetchone()
        return self._entity_row(row) if row else None

    def list_entities(self, type: str | None = None, q: str | None = None, limit: int = 10000) -> list[dict]:
        sql, args = "SELECT * FROM entities WHERE 1=1", []
        if type:
            sql += " AND type=?"
            args.append(type)
        if q:
            sql += " AND (label LIKE ? OR label_ko LIKE ? OR aliases LIKE ? OR id LIKE ?)"
            args += [f"%{q}%"] * 4
        sql += " ORDER BY COALESCE(start_year, 99999), label LIMIT ?"
        args.append(limit)
        return [self._entity_row(r) for r in self._conn.execute(sql, args)]

    def delete_entity(self, id: str, actor: str = "system") -> None:
        before = self.get_entity(id)
        with self.tx() as c:
            c.execute("DELETE FROM evidence WHERE edge_id IN (SELECT id FROM edges WHERE source=? OR target=?)", (id, id))
            c.execute("DELETE FROM edges WHERE source=? OR target=?", (id, id))
            c.execute("DELETE FROM entities WHERE id=?", (id,))
            self._log(c, "entity", id, "delete", before, None, actor)

    # ----------------------------------------------------------------- edges
    def find_edge(self, source: str, predicate: str, target: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM edges WHERE source=? AND predicate=? AND target=?",
                                 (source, predicate, target)).fetchone()
        return self._edge_row(row) if row else None

    def add_edge(self, source: str, predicate: str, target: str, *, evidence_status: str = "direct",
                 epistemic_status: str = "proposed", origin: str = "human", note: str = "",
                 props: dict | None = None, confidence_override: float | None = None,
                 valid_from: int | None = None, valid_to: int | None = None,
                 actor: str = "system") -> dict:
        O.relation(predicate)
        if evidence_status not in O.EVIDENCE_STATUS:
            raise ValueError(f"unknown evidence_status: {evidence_status}")
        if epistemic_status not in O.EPISTEMIC_STATUS:
            raise ValueError(f"unknown epistemic_status: {epistemic_status}")
        for eid in (source, target):
            if not self.get_entity(eid):
                raise KeyError(f"entity not found: {eid}")
        existing = self.find_edge(source, predicate, target)
        if existing:
            return existing
        eid = self._next_id("edge", "E")
        now = _now()
        with self.tx() as c:
            c.execute(
                "INSERT INTO edges(id, source, predicate, target, props, evidence_status, epistemic_status,"
                " confidence, confidence_override, origin, note, valid_from, valid_to, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, source, predicate, target, json.dumps(props or {}, ensure_ascii=False), evidence_status,
                 epistemic_status, 0.0, confidence_override, origin, note, valid_from, valid_to, now, now))
            self._log(c, "edge", eid, "create", None,
                      {"source": source, "predicate": predicate, "target": target,
                       "epistemic_status": epistemic_status, "origin": origin}, actor)
        self.recompute_confidence(eid, actor=actor, log=False)
        return self.get_edge(eid)  # type: ignore[return-value]

    def _edge_row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["props"] = _loads(d["props"], {})
        return d

    def get_edge(self, id: str, with_evidence: bool = False) -> dict | None:
        row = self._conn.execute("SELECT * FROM edges WHERE id=?", (id,)).fetchone()
        if not row:
            return None
        d = self._edge_row(row)
        if with_evidence:
            d["evidence"] = self.list_evidence(id)
        return d

    def list_edges(self, *, source: str | None = None, target: str | None = None,
                   predicate: str | None = None, statuses: Iterable[str] | None = None,
                   node: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM edges WHERE 1=1", []
        if source:
            sql += " AND source=?"
            args.append(source)
        if target:
            sql += " AND target=?"
            args.append(target)
        if node:
            sql += " AND (source=? OR target=?)"
            args += [node, node]
        if predicate:
            sql += " AND predicate=?"
            args.append(predicate)
        if statuses:
            st = list(statuses)
            sql += f" AND epistemic_status IN ({','.join('?' * len(st))})"
            args += st
        sql += " ORDER BY id"
        return [self._edge_row(r) for r in self._conn.execute(sql, args)]

    def update_edge(self, id: str, *, actor: str = "system", reason: str = "", **fields) -> dict:
        allowed = {"evidence_status", "epistemic_status", "note", "props", "confidence_override",
                   "valid_from", "valid_to", "predicate"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"cannot update fields: {bad}")
        before = self.get_edge(id)
        if not before:
            raise KeyError(f"edge not found: {id}")
        if "props" in fields:
            fields["props"] = json.dumps(fields["props"], ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE edges SET {sets}, version=version+1, updated_at=? WHERE id=?",
                      [*fields.values(), _now(), id])
            self._log(c, "edge", id, "update", {k: before.get(k) for k in fields},
                      {k: v for k, v in fields.items()}, actor, reason)
        self.recompute_confidence(id, actor=actor, reason=reason)
        return self.get_edge(id)  # type: ignore[return-value]

    def delete_edge(self, id: str, actor: str = "system", reason: str = "") -> None:
        before = self.get_edge(id, with_evidence=True)
        with self.tx() as c:
            c.execute("DELETE FROM evidence WHERE edge_id=?", (id,))
            c.execute("DELETE FROM edges WHERE id=?", (id,))
            self._log(c, "edge", id, "delete", before, None, actor, reason)

    # -------------------------------------------------------------- evidence
    def add_evidence(self, edge_id: str, *, tier: int, source_id: str | None = None, citation: str = "",
                     stance: str = "supports", locator: str = "", quotation: str = "",
                     interpretation: str = "", added_by: str = "seed", recompute: bool = True) -> dict:
        if tier not in O.EVIDENCE_TIERS:
            raise ValueError(f"invalid tier: {tier}")
        if stance not in ("supports", "contradicts"):
            raise ValueError("stance must be supports|contradicts")
        if source_id and not self.get_entity(source_id):
            raise KeyError(f"source entity not found: {source_id}")
        if not self.get_edge(edge_id):
            raise KeyError(f"edge not found: {edge_id}")
        evid = self._next_id("evidence", "EV")
        row = dict(id=evid, edge_id=edge_id, source_id=source_id, citation=citation, tier=tier, stance=stance,
                   locator=locator, quotation=quotation, interpretation=interpretation, added_by=added_by)
        with self.tx() as c:
            c.execute(
                "INSERT INTO evidence(id, edge_id, source_id, citation, tier, stance, locator, quotation,"
                " interpretation, added_by, created_at) VALUES (:id,:edge_id,:source_id,:citation,:tier,:stance,"
                ":locator,:quotation,:interpretation,:added_by,:now)", {**row, "now": _now()})
            self._log(c, "evidence", evid, "create", None, row, added_by)
        if recompute:
            self.recompute_confidence(edge_id, actor=added_by, reason=f"evidence {evid} added")
        return row

    def list_evidence(self, edge_id: str) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM evidence WHERE edge_id=? ORDER BY tier, id", (edge_id,))
        out = []
        for r in rows:
            d = dict(r)
            if d["source_id"]:
                src = self.get_entity(d["source_id"])
                d["source_label"] = (src or {}).get("label_ko") or (src or {}).get("label")
            out.append(d)
        return out

    def recompute_confidence(self, edge_id: str, actor: str = "system", reason: str = "",
                             log: bool = True) -> float:
        edge = self.get_edge(edge_id)
        if not edge:
            raise KeyError(edge_id)
        ev = self.list_evidence(edge_id)
        value = compute_confidence(ev, edge["evidence_status"], edge["confidence_override"],
                                   O.relation(edge["predicate"]).requires_evidence)
        if abs(value - (edge["confidence"] or 0)) > 1e-9:
            with self.tx() as c:
                c.execute("UPDATE edges SET confidence=? WHERE id=?", (value, edge_id))
                if log:
                    self._log(c, "edge", edge_id, "confidence", {"confidence": edge["confidence"]},
                              {"confidence": value}, actor, reason)
        return value

    # --------------------------------------------------------------- history
    def history(self, object_id: str | None = None, limit: int = 200) -> list[dict]:
        if object_id:
            rows = self._conn.execute("SELECT * FROM history WHERE object_id=? ORDER BY id DESC LIMIT ?",
                                      (object_id, limit))
        else:
            rows = self._conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["before"] = _loads(d["before"], None)
            d["after"] = _loads(d["after"], None)
            out.append(d)
        return out

    # ------------------------------------------------------------- documents
    def add_document(self, title: str, text: str, author_id: str | None = None,
                     work_id: str | None = None) -> dict:
        did = self._next_id("document", "D")
        with self.tx() as c:
            c.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                      (did, title, author_id, work_id, text, _now()))
        return {"id": did, "title": title, "author_id": author_id, "work_id": work_id}

    def list_documents(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute(
            "SELECT id, title, author_id, work_id, length(text) AS length, created_at FROM documents ORDER BY id")]

    # ------------------------------------------------------------ candidates
    def add_candidate(self, kind: str, payload: dict, *, origin: str = "extraction",
                      document_id: str | None = None, score: float = 0.0) -> dict:
        cid = self._next_id("candidate", "C")
        with self.tx() as c:
            c.execute("INSERT INTO candidates(id, kind, payload, origin, document_id, score, created_at)"
                      " VALUES (?,?,?,?,?,?,?)",
                      (cid, kind, json.dumps(payload, ensure_ascii=False), origin, document_id, score, _now()))
        return self.get_candidate(cid)  # type: ignore[return-value]

    def get_candidate(self, id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM candidates WHERE id=?", (id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = _loads(d["payload"], {})
        return d

    def list_candidates(self, status: str | None = "pending") -> list[dict]:
        if status:
            rows = self._conn.execute("SELECT id FROM candidates WHERE status=? ORDER BY score DESC, id", (status,))
        else:
            rows = self._conn.execute("SELECT id FROM candidates ORDER BY id")
        return [self.get_candidate(r["id"]) for r in rows]  # type: ignore[misc]

    def set_candidate_status(self, id: str, status: str, actor: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE candidates SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                      (status, actor, _now(), id))
            self._log(c, "candidate", id, status, None, None, actor)

    # -------------------------------------------------------------- versions
    def stats(self) -> dict:
        ent = {r["type"]: r["n"] for r in self._conn.execute(
            "SELECT type, COUNT(*) n FROM entities GROUP BY type")}
        pred = {r["predicate"]: r["n"] for r in self._conn.execute(
            "SELECT predicate, COUNT(*) n FROM edges GROUP BY predicate ORDER BY n DESC")}
        status = {r["epistemic_status"]: r["n"] for r in self._conn.execute(
            "SELECT epistemic_status, COUNT(*) n FROM edges GROUP BY epistemic_status")}
        one = lambda q: self._conn.execute(q).fetchone()[0]  # noqa: E731
        return {
            "schema_version": self.get_meta("schema_version"),
            "ontology_version": self.get_meta("ontology_version") or "unversioned",
            "entities": sum(ent.values()), "entities_by_type": ent,
            "edges": sum(pred.values()), "edges_by_predicate": pred, "edges_by_status": status,
            "evidence": one("SELECT COUNT(*) FROM evidence"),
            "documents": one("SELECT COUNT(*) FROM documents"),
            "pending_candidates": one("SELECT COUNT(*) FROM candidates WHERE status='pending'"),
        }

    def snapshot_version(self, version: str, note: str = "") -> dict:
        counts = self.stats()
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO ontology_versions VALUES (?,?,?,?)",
                      (version, note, json.dumps(counts, ensure_ascii=False), _now()))
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('ontology_version', ?)", (version,))
        return {"version": version, "note": note, "counts": counts}

    def list_versions(self) -> list[dict]:
        out = []
        for r in self._conn.execute("SELECT * FROM ontology_versions ORDER BY created_at"):
            d = dict(r)
            d["counts"] = _loads(d["counts"], {})
            out.append(d)
        return out

    def close(self) -> None:
        self._conn.close()
