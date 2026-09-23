"""Export — JSON 스냅샷, Neo4j Cypher, RDF/Turtle(OWL 스키마 포함).

HIGO 의 SQLite 저장소는 참조 구현이다. 규모가 커지면 여기서 내보낸 Cypher 를
Neo4j/Memgraph 에, Turtle 을 트리플스토어에 적재해 같은 온톨로지를 운용할 수 있다.
"""
from __future__ import annotations

import json

from . import ontology as O
from .store import Store

NS = "https://higo.example.org/ontology#"
RES = "https://higo.example.org/resource/"


def to_json(store: Store) -> dict:
    edges = []
    for e in store.list_edges():
        e = dict(e)
        e["evidence"] = store.list_evidence(e["id"])
        edges.append(e)
    return {"schema": O.schema_as_dict(), "stats": store.stats(), "entities": store.list_entities(),
            "edges": edges, "versions": store.list_versions()}


def import_json(store: Store, data: dict, actor: str = "import") -> dict:
    n_e = n_r = n_ev = 0
    for ent in data.get("entities", []):
        store.upsert_entity(ent["id"], ent["type"], ent["label"], label_ko=ent.get("label_ko"),
                            aliases=ent.get("aliases") or [], description=ent.get("description") or "",
                            props=ent.get("props") or {}, start_year=ent.get("start_year"),
                            end_year=ent.get("end_year"), origin=ent.get("origin") or "import",
                            status=ent.get("status") or "accepted", actor=actor)
        n_e += 1
    for e in data.get("edges", []):
        new = store.add_edge(e["source"], e["predicate"], e["target"], evidence_status=e["evidence_status"],
                             epistemic_status=e["epistemic_status"], origin=e.get("origin") or "import",
                             note=e.get("note") or "", props=e.get("props") or {},
                             confidence_override=e.get("confidence_override"), actor=actor)
        n_r += 1
        if not store.list_evidence(new["id"]):
            for ev in e.get("evidence", []):
                store.add_evidence(new["id"], tier=ev["tier"], source_id=ev.get("source_id"),
                                   citation=ev.get("citation") or "", stance=ev.get("stance") or "supports",
                                   locator=ev.get("locator") or "", quotation=ev.get("quotation") or "",
                                   interpretation=ev.get("interpretation") or "", added_by=actor)
                n_ev += 1
    return {"entities": n_e, "edges": n_r, "evidence": n_ev}


def _cy(s) -> str:
    return json.dumps(s, ensure_ascii=False)


def to_cypher(store: Store) -> str:
    lines = ["// HIGO → Neo4j import script", "// schema " + O.SCHEMA_VERSION]
    for t in O.ENTITY_TYPES:
        lines.append(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{t}) REQUIRE n.id IS UNIQUE;")
    for ent in store.list_entities():
        props = {"id": ent["id"], "label": ent["label"], "label_ko": ent.get("label_ko") or "",
                 "description": ent.get("description") or "", "start_year": ent.get("start_year"),
                 "end_year": ent.get("end_year"), "status": ent.get("status")}
        for k, v in (ent.get("props") or {}).items():
            if isinstance(v, (str, int, float, bool)):
                props[k] = v
        body = ", ".join(f"{k}: {_cy(v)}" for k, v in props.items() if v is not None)
        lines.append(f"MERGE (n:{ent['type']} {{id: {_cy(ent['id'])}}}) SET n += {{{body}}};")
    for e in store.list_edges():
        rel = e["predicate"].upper()
        ev = store.list_evidence(e["id"])
        props = {"id": e["id"], "confidence": e["confidence"], "evidence_status": e["evidence_status"],
                 "epistemic_status": e["epistemic_status"], "origin": e["origin"],
                 "category": O.RELATION_TYPES[e["predicate"]].category,
                 "evidence_tiers": [x["tier"] for x in ev],
                 "evidence_citations": [x.get("source_label") or x["citation"] for x in ev]}
        body = ", ".join(f"{k}: {_cy(v)}" for k, v in props.items())
        lines.append(f"MATCH (a {{id: {_cy(e['source'])}}}), (b {{id: {_cy(e['target'])}}}) "
                     f"MERGE (a)-[r:{rel} {{id: {_cy(e['id'])}}}]->(b) SET r += {{{body}}};")
    return "\n".join(lines) + "\n"


def _lit(s) -> str:
    if isinstance(s, bool):
        return "true" if s else "false"
    if isinstance(s, (int, float)):
        return str(s)
    return json.dumps(str(s), ensure_ascii=False)


def _iri(eid: str) -> str:
    return "<" + RES + eid.replace(":", "/") + ">"


def to_turtle(store: Store, include_schema: bool = True) -> str:
    out = [f"@prefix higo: <{NS}> .", "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
           "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
           "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
           "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .", ""]
    if include_schema:
        out.append(f"<{NS}> a owl:Ontology ; owl:versionInfo {_lit(O.SCHEMA_VERSION)} .")
        for t in O.ENTITY_TYPES.values():
            out.append(f"higo:{t.name} a owl:Class ; rdfs:label {_lit(t.label_ko)}@ko ; rdfs:comment {_lit(t.description)}@ko .")
        for r in O.RELATION_TYPES.values():
            parts = [f"higo:{r.name} a owl:ObjectProperty", f"rdfs:label {_lit(r.label_ko)}@ko",
                     f"rdfs:comment {_lit(r.description)}@ko", f"higo:category {_lit(r.category)}"]
            if r.symmetric:
                parts.append("a owl:SymmetricProperty")
            if O.ANY not in r.domain and len(r.domain) == 1:
                parts.append(f"rdfs:domain higo:{r.domain[0]}")
            if O.ANY not in r.range and len(r.range) == 1:
                parts.append(f"rdfs:range higo:{r.range[0]}")
            out.append(" ;\n    ".join(parts) + " .")
        out.append("")
    for ent in store.list_entities():
        parts = [f"{_iri(ent['id'])} a higo:{ent['type']}", f"rdfs:label {_lit(ent['label'])}"]
        if ent.get("label_ko"):
            parts.append(f"rdfs:label {_lit(ent['label_ko'])}@ko")
        if ent.get("description"):
            parts.append(f"rdfs:comment {_lit(ent['description'])}")
        for k in ("start_year", "end_year"):
            if ent.get(k) is not None:
                parts.append(f"higo:{k} {ent[k]}")
        st = (ent.get("props") or {}).get("statement")
        if st:
            parts.append(f"higo:statement {_lit(st)}@ko")
        out.append(" ;\n    ".join(parts) + " .")
    # 관계는 트리플 + RDF-star 스타일 대신 reification(Statement) 으로 증거·확신도를 붙인다
    for e in store.list_edges():
        s, o = _iri(e["source"]), _iri(e["target"])
        out.append(f"{s} higo:{e['predicate']} {o} .")
        stmt = f"<{RES}edge/{e['id']}>"
        parts = [f"{stmt} a rdf:Statement", f"rdf:subject {s}", f"rdf:predicate higo:{e['predicate']}",
                 f"rdf:object {o}", f"higo:confidence {e['confidence']}",
                 f"higo:evidenceStatus {_lit(e['evidence_status'])}",
                 f"higo:epistemicStatus {_lit(e['epistemic_status'])}", f"higo:origin {_lit(e['origin'])}"]
        for ev in store.list_evidence(e["id"]):
            cit = ev.get("source_label") or ev["citation"]
            parts.append(f"higo:evidence [ higo:tier {ev['tier']} ; higo:stance {_lit(ev['stance'])} ; "
                         f"higo:citation {_lit(cit)} ; higo:locator {_lit(ev['locator'])} ]")
        out.append(" ;\n    ".join(parts) + " .")
    return "\n".join(out) + "\n"
