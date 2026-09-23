"""Phase 1 seed 로더 — 철학 30인 + 교차 분야 인물, 원전, 개념, 명제, 증거 관계."""
from __future__ import annotations

from ..store import Store
from . import concepts, people, propositions, relations, taxonomy

SEED_VERSION = "0.1.0-phase1"


def _ev_args(store: Store, item: tuple) -> dict:
    src, tier, locator, interp, stance = item
    if src.startswith(("work:", "source:")) and store.get_entity(src):
        return dict(source_id=src, tier=tier, locator=locator, interpretation=interp, stance=stance)
    return dict(citation=src, tier=tier, locator=locator, interpretation=interp, stance=stance)


def _add_rel(store: Store, r: dict) -> dict:
    edge = store.add_edge(r["source"], r["predicate"], r["target"], evidence_status=r["status"],
                          epistemic_status=r["epistemic"], origin=r["origin"], note=r.get("note", ""),
                          actor="seed")
    if not store.list_evidence(edge["id"]):
        for item in r["evidence"]:
            store.add_evidence(edge["id"], added_by="seed" if r["origin"] != "ai" else "ai:discovery",
                               recompute=False, **_ev_args(store, item))
        store.recompute_confidence(edge["id"], log=False)
    return edge


def _era_for(year: int | None) -> str | None:
    if year is None:
        return None
    for eid, _, _, s, e in taxonomy.ERAS:
        if s <= year < e:
            return eid
    return None


def load_seed(store: Store, force: bool = False) -> dict:
    if store.get_meta("seed_version") and not force:
        return {"skipped": True, **store.stats()}
    up = store.upsert_entity
    for did, label, ko, parent in taxonomy.DOMAINS:
        up(did, "Domain", label, label_ko=ko, origin="seed", actor="seed")
    for did, _, _, parent in taxonomy.DOMAINS:
        if parent:
            store.add_edge(did, "subclass_of", parent, epistemic_status="accepted", origin="seed", actor="seed")
    for eid, label, ko, s, e in taxonomy.ERAS:
        up(eid, "Era", label, label_ko=ko, start_year=s, end_year=e, origin="seed", actor="seed")
    for sid, typ, label, ko, s, e, desc in taxonomy.SCHOOLS:
        up(sid, typ, label, label_ko=ko, start_year=s, end_year=e, description=desc, origin="seed", actor="seed")
    for iid, label, ko, founded, desc in taxonomy.INSTITUTIONS:
        up(iid, "Institution", label, label_ko=ko, start_year=founded, description=desc, origin="seed", actor="seed")
    for eid, label, ko, s, e, desc in taxonomy.EVENTS:
        up(eid, "Event", label, label_ko=ko, start_year=s, end_year=e, description=desc, origin="seed", actor="seed")
    for sid, label, ko, tier, desc in taxonomy.SOURCES:
        up(sid, "Source", label, label_ko=ko, description=desc, props={"tier": tier}, origin="seed", actor="seed")

    acc = dict(epistemic_status="accepted", origin="seed", actor="seed")
    for pid, label, ko, born, died, doms, schools, insts, desc in people.PERSONS:
        aliases = {n.split()[-1] for n in (label, ko) if " " in n} - {label, ko}
        up(pid, "Person", label, label_ko=ko, aliases=sorted(aliases), start_year=born, end_year=died,
           description=desc, props={"born": born, "died": died}, origin="seed", actor="seed")
        for d in doms:
            store.add_edge(pid, "belongs_to_domain", f"domain:{d}", **acc)
        for s in schools:
            store.add_edge(pid, "member_of", f"school:{s}", **acc)
        for i in insts:
            store.add_edge(pid, "affiliated_with", f"inst:{i}", **acc)
        era = _era_for(born + min(40, max(0, died - born) // 2) if born is not None else None)
        if era:
            store.add_edge(pid, "active_in", era, **acc)
    for wid, label, ko, authors, year, doms, desc in people.WORKS:
        up(wid, "Work", label, label_ko=ko, start_year=year, description=desc, props={"year": year},
           origin="seed", actor="seed")
        for a in authors:
            store.add_edge(f"person:{a}", "authored", wid, **acc)
        for d in doms:
            store.add_edge(wid, "belongs_to_domain", f"domain:{d}", **acc)
        era = _era_for(year)
        if era:
            store.add_edge(wid, "active_in", era, **acc)

    for key, label, ko, doms, parent, aliases, definition in concepts.CONCEPTS:
        cid = f"concept:{key}"
        up(cid, "Concept", label, label_ko=ko, aliases=aliases, description=definition,
           props={"definition": definition}, origin="seed", actor="seed")
        for d in doms:
            store.add_edge(cid, "belongs_to_domain", f"domain:{d}", **acc)
    for key, *_rest in concepts.CONCEPTS:
        parent = _rest[3]
        if parent:
            store.add_edge(f"concept:{key}", "subclass_of", f"concept:{parent}", **acc)
    for a, pred, b in concepts.CONCEPT_RELATIONS:
        store.add_edge(f"concept:{a}", pred, f"concept:{b}", **acc)

    for key, author, work, year, loc, ko, en, cs in propositions.PROPOSITIONS:
        pid = f"prop:{key}"
        up(pid, "Proposition", ko if len(ko) <= 80 else ko[:78] + "…", label_ko=None,
           props={"statement": ko, "statement_en": en, "locator": loc, "year": year, "certainty": "paraphrase"},
           start_year=year, origin="seed", actor="seed")
        e1 = store.add_edge(f"person:{author}", "proposes", pid, **acc)
        e2 = store.add_edge(f"work:{work}", "contains", pid, **acc)
        for c in cs:
            store.add_edge(pid, "about", f"concept:{c}", **acc)
        # 명제 귀속 자체에도 원전 증거를 붙인다
        for e in (e1, e2):
            if not store.list_evidence(e["id"]):
                store.add_evidence(e["id"], tier=1, source_id=f"work:{work}", locator=loc, added_by="seed",
                                   recompute=False)
    for key, label_ko, premises, conclusion, form in propositions.ARGUMENTS:
        aid = f"arg:{key}"
        up(aid, "Argument", label_ko, props={"form": form}, origin="seed", actor="seed")
        for p in premises:
            store.add_edge(f"prop:{p}", "premise_of", aid, **acc)
        store.add_edge(aid, "concludes", f"prop:{conclusion}", **acc)
        author = store.list_edges(target=f"prop:{conclusion}", predicate="proposes")
        if author:
            store.add_edge(author[0]["source"], "proposes", aid, **acc)

    for r in relations.RELATIONS + relations.EXTRA_HYPOTHESES:
        _add_rel(store, r)
    for a, pred, b, epi, evs, note in relations.PROPOSITION_RELATIONS:
        _add_rel(store, relations.rel(f"prop:{a}", pred, f"prop:{b}", status="direct" if evs else "inferred",
                                      evidence=evs, epistemic=epi, note=note))
    for iid, label_ko, held_by, target, about, desc in relations.INTERPRETATIONS:
        up(iid, "Interpretation", label_ko, description=desc, origin="seed", actor="seed")
        store.add_edge(iid, "held_by", held_by, **acc)
        store.add_edge(iid, "interprets", target, **acc)
        for c in about:
            store.add_edge(iid, "about", f"concept:{c}", **acc)

    store.set_meta("seed_version", SEED_VERSION)
    store.snapshot_version("0.1.0", "HIGO Ontology v0.1 — Phase 1 seed (철학 30인 + 교차 분야)")
    return store.stats()
