"""Graph RAG — 그래프에 존재하는 근거를 따라가며 답한다.

    Question → Entity linking(가제티어 + 벡터) → Intent → 그래프 확장
             → 관련 인물/저작/명제 → Evidence → 합성(LLM 또는 템플릿)

답변의 모든 문장은 그래프의 노드(P…)/관계(E…)/증거(EV…) ID 를 인용한다. LLM 을 쓰는
경우에도 컨텍스트로 제공된 근거만 사용하도록 지시하며, 인용 ID 가 컨텍스트에 없으면
답변에서 제거 대상으로 표시한다.
"""
from __future__ import annotations

import json
import re

from . import ontology as O
from .graph import DEFAULT_STATUSES, GraphIndex
from .llm import LLMClient, LLMUnavailable
from .reasoning import Reasoner
from .vector import VectorIndex

INTENTS = [
    ("genealogy", re.compile(r"변화|변천|계보|어떻게 (변|발전|이어)|역사|genealog|evolv|chang|develop|history of|시작되어")),
    ("compare", re.compile(r"비교|논쟁|대립|차이|갈라지|공통|vs\.?|versus|debate|compare|differ|disagree")),
    ("connection", re.compile(r"영향|연결|관계|이어지|연속성|단절|influence|connect|relat|lineage")),
    ("contradiction", re.compile(r"대립 구조|핵심 논쟁|모순|contradict")),
    ("cross_domain", re.compile(r"분야|학제|경계|cross.?domain|interdisciplin")),
]


class GraphRAG:
    def __init__(self, graph: GraphIndex, vectors: VectorIndex, reasoner: Reasoner, extractor,
                 llm: LLMClient | None = None):
        self.g = graph
        self.v = vectors
        self.r = reasoner
        self.x = extractor
        self.llm = llm

    # -------------------------------------------------------------- linking
    def link(self, question: str) -> list[dict]:
        mentions = self.x.link_entities(question)
        self._domains = [m.entity_id for m in mentions if m.type == "Domain"]
        # 긴 이름으로 매칭된 개념을 우선한다 ('근대적 합리주의' → 합리론)
        mentions.sort(key=lambda m: (m.type != "Person", -len(m.text)) if m.type == "Concept" else (0, m.start))
        found = [{"id": m.entity_id, "type": m.type, "label": self.g.label(m.entity_id), "via": "name",
                  "score": 1.0} for m in mentions if m.type not in ("Domain",)]
        if len([f for f in found if f["type"] in ("Person", "Concept")]) < 1:
            for eid, s in self.v.search(question, 4, types=["Concept", "Person"], min_score=0.12):
                if not any(f["id"] == eid for f in found):
                    found.append({"id": eid, "type": self.g.nodes[eid]["type"], "label": self.g.label(eid),
                                  "via": "vector", "score": round(s, 3)})
        return found

    def intent(self, question: str, linked: list[dict]) -> str:
        persons = [x for x in linked if x["type"] == "Person"]
        concepts = [x for x in linked if x["type"] == "Concept"]
        if len(getattr(self, "_domains", [])) >= 2 and len(persons) < 2:
            return "cross_domain"
        for name, pat in INTENTS:
            if pat.search(question.lower()):
                if name == "compare" and len(persons) >= 2:
                    return "compare"
                if name == "connection" and len(persons) >= 2:
                    return "connection" if len(persons) == 2 else "chain"
                if name == "genealogy" and concepts:
                    return "genealogy"
                if name in ("contradiction", "cross_domain"):
                    return name
        if len(persons) > 2:
            return "chain"
        if len(persons) == 2:
            return "compare"
        if concepts:
            return "genealogy"
        if persons:
            return "profile"
        return "search"

    # ------------------------------------------------------------ retrieval
    def retrieve(self, question: str, include_hypotheses: bool = False) -> dict:
        g = self.g.refresh()
        trace = [{"step": "question", "detail": question}]
        linked = self.link(question)
        trace.append({"step": "ontology_search", "detail": [f"{x['label']} ({x['type']}, {x['via']})" for x in linked]})
        intent = self.intent(question, linked)
        trace.append({"step": "intent", "detail": intent})
        persons = [x["id"] for x in linked if x["type"] == "Person"]
        concepts = [x["id"] for x in linked if x["type"] == "Concept"]
        analysis: dict = {}
        node_ids: set[str] = set()
        if intent == "genealogy" and concepts:
            analysis = self.r.concept_genealogy(concepts[0])
            trace.append({"step": "temporal_expansion",
                          "detail": f"개념 계열 {len(analysis['family'])}개, 타임라인 항목 {len(analysis['timeline'])}개"})
            node_ids = {n["id"] for n in analysis["graph"]["nodes"]}
        elif intent == "compare" and len(persons) >= 2:
            topic = ", ".join(self.g.label(c) for c in concepts) or None
            analysis = self.r.compare(persons[0], persons[1], topic=topic, vector_index=self.v)
            trace.append({"step": "proposition_alignment", "detail": f"쟁점 {len(analysis['issues'])}개"})
            node_ids = set(persons[:2]) | {p["id"] for i in analysis["issues"]
                                           for p in i["a_positions"] + i["b_positions"]}
        elif intent in ("connection",) and len(persons) >= 2:
            analysis = self.r.explain_connection(persons[0], persons[1], include_hypotheses=include_hypotheses)
            trace.append({"step": "path_classification", "detail": [s["kind"] for s in analysis["summary"]]})
            node_ids = {n["id"] for n in analysis["graph"]["nodes"]}
        elif intent == "chain" and len(persons) >= 2:
            ordered = sorted(persons, key=lambda p: g.year(p) if g.year(p) is not None else 99999)
            links = []
            for a, b in zip(ordered, ordered[1:]):
                links.append(self.r.explain_connection(a, b, include_hypotheses=include_hypotheses))
            analysis = {"chain": ordered, "links": links}
            trace.append({"step": "chain_analysis", "detail": [f"{l['from_label']}→{l['to_label']}: "
                                                               f"{l['summary'][0]['kind'] if l['summary'] else '없음'}"
                                                               for l in links]})
            for l in links:
                node_ids |= {n["id"] for n in l["graph"]["nodes"]}
        elif intent == "contradiction":
            analysis = self.r.contradiction_graph()
            node_ids = {n["id"] for n in analysis["graph"]["nodes"]}
        elif intent == "cross_domain":
            analysis = self.r.cross_domain()
            node_ids = {b["id"] for b in analysis["bridge_thinkers"][:15]}
        elif intent == "profile" and persons:
            analysis = {"detail": self.r.entity_detail(persons[0]), "dna": self.r.thinker_dna(persons[0])}
            node_ids = {persons[0]} | set(g.targets(persons[0], "proposes"))
        # 공통: 질문과 의미적으로 가까운 명제를 근거 후보로 추가
        near = self.v.search(question, 8, types=["Proposition"], min_score=0.05)
        trace.append({"step": "semantic_retrieval", "detail": [f"{g.label(i)} ({s:.2f})" for i, s in near[:5]]})
        props = [p for p in node_ids if g.nodes.get(p, {}).get("type") == "Proposition"]
        props += [i for i, _ in near if i not in props]
        evidence = self._evidence_for(node_ids | set(props))
        trace.append({"step": "evidence", "detail": f"증거 {len(evidence)}건"})
        return {"question": question, "intent": intent, "linked": linked, "analysis": analysis,
                "propositions": [self._prop_card(p) for p in props[:14]], "evidence": evidence[:30],
                "trace": trace, "graph": g.subgraph(list(node_ids | set(props[:14])), depth=0)}

    def _prop_card(self, pid: str) -> dict:
        g = self.g
        props = g.nodes[pid].get("props") or {}
        return {"id": pid, "statement": props.get("statement") or g.nodes[pid]["label"],
                "author": [g.label(a) for a in g.sources(pid, "proposes")],
                "work": [g.label(w) for w in g.sources(pid, "contains")], "locator": props.get("locator"),
                "year": props.get("year"), "concepts": [g.label(c) for c in g.targets(pid, "about")]}

    def _evidence_for(self, node_ids: set[str]) -> list[dict]:
        g = self.g
        out = []
        for nid in node_ids:
            for e in g.edges_of(nid, statuses=DEFAULT_STATUSES):
                if e["predicate"] in ("about", "belongs_to_domain", "active_in", "member_of"):
                    continue
                if e["source"] in node_ids and e["target"] in node_ids:
                    for ev in g.store.list_evidence(e["id"]):
                        out.append({"evidence_id": ev["id"], "edge_id": e["id"],
                                    "claim": f"{g.label(e['source'])} —{O.RELATION_TYPES[e['predicate']].label_ko}→ "
                                             f"{g.label(e['target'])}",
                                    "tier": ev["tier"], "citation": ev.get("source_label") or ev["citation"],
                                    "locator": ev["locator"], "stance": ev["stance"],
                                    "confidence": e["confidence"], "status": e["epistemic_status"]})
        uniq = {o["evidence_id"]: o for o in out}
        return sorted(uniq.values(), key=lambda o: (o["tier"], -o["confidence"]))

    # ------------------------------------------------------------ synthesis
    def answer(self, question: str, use_llm: bool = True, include_hypotheses: bool = False) -> dict:
        ctx = self.retrieve(question, include_hypotheses=include_hypotheses)
        text, mode = None, "template"
        if use_llm and self.llm and self.llm.available:
            try:
                text = self._llm_answer(ctx)
                mode = f"llm:{self.llm.model}"
            except LLMUnavailable as exc:
                ctx["trace"].append({"step": "llm_error", "detail": str(exc)})
        if text is None:
            text = self._template_answer(ctx)
        cited = set(re.findall(r"\b(?:E\d{5}|EV\d{5}|prop:[\w\-]+)", text))
        known = {e["edge_id"] for e in ctx["evidence"]} | {e["evidence_id"] for e in ctx["evidence"]} | \
            {p["id"] for p in ctx["propositions"]} | {e["id"] for e in ctx["graph"]["edges"]} | \
            set(re.findall(r"\b(?:E\d{5}|prop:[\w\-]+)", json.dumps(ctx["analysis"], ensure_ascii=False)))
        ctx["trace"].append({"step": "synthesis", "detail": mode})
        return {**ctx, "answer": text, "mode": mode,
                "citations": sorted(cited), "unsupported_citations": sorted(c for c in cited if c not in known)}

    def _context_block(self, ctx: dict) -> str:
        lines = [f"INTENT: {ctx['intent']}"]
        a = ctx["analysis"]
        if ctx["intent"] == "genealogy" and a:
            lines.append(f"CONCEPT FAMILY: {', '.join(f['label'] + '(' + f['relation'] + ')' for f in a['family'])}")
            for t in a["timeline"][:40]:
                lines.append(f"- [{t['year']}] {t.get('person_label') or ''} / {t.get('work_label') or ''}: "
                             f"{t.get('statement') or t.get('relation_ko', '')} ({t.get('proposition') or t.get('edge_id')})")
            for l in a["lineage"][:30]:
                lines.append(f"LINEAGE {l['edge_id']}: {l['from_label']} → {l['to_label']} ({l['predicate']}, conf {l['confidence']:.2f})")
            for t in a["transformations"][:20]:
                lines.append(f"CONCEPT RELATION {t['edge_id']}: {t['from_label']} {t['predicate']} {t['to_label']}")
        elif ctx["intent"] == "compare" and a:
            lines.append(f"A={a['a_label']} B={a['b_label']} similarity={a['similarity']} verdict={a['verdict']}")
            for i in a["issues"]:
                lines.append(f"ISSUE {i['label']} — {i['stance_ko']} ({i['basis']})")
                for p in i["a_positions"]:
                    lines.append(f"  A {p['id']}: {p['statement']} [{p['work']} {p['locator'] or ''}]")
                for p in i["b_positions"]:
                    lines.append(f"  B {p['id']}: {p['statement']} [{p['work']} {p['locator'] or ''}]")
            for c in a["cleavages"]:
                lines.append(f"CLEAVAGE {c['edge_id']}: A:{c['a_concept']} vs B:{c['b_concept']}")
        elif ctx["intent"] in ("connection",) and a:
            lines += self._conn_lines(a)
        elif ctx["intent"] == "chain" and a:
            for l in a["links"]:
                lines += self._conn_lines(l)
        elif ctx["intent"] == "contradiction" and a:
            for ax in a["axes"][:10]:
                lines.append(f"AXIS {ax['edge_id']}: {ax['sides'][0]['label']} vs {ax['sides'][1]['label']} — "
                             f"{', '.join(t['label'] for t in ax['sides'][0]['thinkers'][:5])} / "
                             f"{', '.join(t['label'] for t in ax['sides'][1]['thinkers'][:5])}")
        elif ctx["intent"] == "cross_domain" and a:
            for p in a["domain_pairs"][:10]:
                lines.append(f"DOMAINS {p['a_label']}↔{p['b_label']}: {p['count']} "
                             f"e.g. {'; '.join(x['source_label'] + ' ' + x['predicate'] + ' ' + x['target_label'] + ' ' + x['edge_id'] for x in p['examples'][:3])}")
        lines.append("PROPOSITIONS:")
        for p in ctx["propositions"]:
            lines.append(f"- {p['id']}: {p['statement']} — {', '.join(p['author'])}, {', '.join(p['work'])} {p['locator'] or ''}")
        lines.append("EVIDENCE:")
        for e in ctx["evidence"]:
            lines.append(f"- {e['evidence_id']} for {e['edge_id']} ({e['claim']}): Tier {e['tier']} {e['citation']} "
                         f"{e['locator']} [{e['stance']}, conf {e['confidence']:.2f}, {e['status']}]")
        return "\n".join(lines)

    @staticmethod
    def _conn_lines(a: dict) -> list[str]:
        lines = [f"CONNECTION {a['from_label']} → {a['to_label']}: {a['verdict']}"]
        for kind, items in a["connections"].items():
            for c in items[:3]:
                if c.get("steps"):
                    path = " ; ".join(f"{s['from_label']} -{s['predicate']}({s['edge_id']})-> {s['to_label']}"
                                      for s in c["steps"])
                    lines.append(f"  {kind} (strength {c['strength']}): {path}")
                elif c.get("facts"):
                    lines.append(f"  {kind}: " + "; ".join(f["reason"] + (f" {f.get('label', '')}") for f in c["facts"]))
        return lines

    SYSTEM = (
        "You are the synthesis layer of HIGO, an intellectual-history ontology. Answer in the language of the "
        "question (Korean if the question is Korean). Use ONLY the graph context provided. Cite node, edge and "
        "evidence ids inline in parentheses, e.g. (E00012, EV00031, prop:plato-justice). Keep strictly separate: "
        "direct influence, indirect influence, conceptual continuity, critical engagement, shared problems, and "
        "structural similarity — never present similarity or co-occurrence as influence. State the confidence and "
        "evidence tier for influence claims, and flag hypotheses or contested edges as such. If the context is "
        "insufficient, say what is missing rather than filling gaps from general knowledge."
    )

    def _llm_answer(self, ctx: dict) -> str:
        return self.llm.complete(self.SYSTEM, f"QUESTION: {ctx['question']}\n\nGRAPH CONTEXT:\n{self._context_block(ctx)}",
                                 max_tokens=8000)

    def _template_answer(self, ctx: dict) -> str:
        a, intent = ctx["analysis"], ctx["intent"]
        out: list[str] = []
        if intent == "genealogy" and a:
            out.append(f"## '{a['label']}' 개념의 계보")
            fam = [f["label"] for f in a["family"] if f["relation"] != "root"]
            if fam:
                out.append(f"관련 개념 계열: {', '.join(fam)}")
            for era in a["by_era"]:
                out.append(f"\n### {era['era']}")
                for t in era["entries"][:8]:
                    who = t.get("person_label") or ""
                    where = f"『{t['work_label']}』" if t.get("work_label") else ""
                    if t["kind"] == "proposition":
                        out.append(f"- {t['year'] or '?'} {who} {where} {t.get('locator') or ''}: "
                                   f"{t['statement']} ({t['proposition']})")
                    else:
                        out.append(f"- {t['year'] or '?'} {who} {where} — {t.get('concept_label')} "
                                   f"{t.get('relation_ko')} ({t.get('edge_id')}, 확신도 {t.get('confidence', 0):.2f})")
            if a["lineage"]:
                out.append("\n### 인물 간 전승 경로 (증거가 있는 인과 관계)")
                for l in a["lineage"][:12]:
                    out.append(f"- {l['from_label']} → {l['to_label']}: {l['predicate_ko']} ({l['edge_id']}, 확신도 {l['confidence']:.2f})")
            if a["transformations"]:
                out.append("\n### 개념의 분화·변형")
                for t in a["transformations"][:12]:
                    out.append(f"- {t['from_label']} —{t['predicate_ko']}→ {t['to_label']} ({t['edge_id']})")
        elif intent == "compare" and a:
            out.append(f"## {a['a_label']} vs {a['b_label']}")
            out.append(f"사상 분포 유사도: {a['similarity']:.2f}. 관계 판정: {a['verdict']}")
            for n, i in enumerate(a["issues"], 1):
                out.append(f"\n### 쟁점 {n}: {i['label']} — {i['stance_ko']}")
                out.append(f"근거: {i['basis']}")
                for p in i["a_positions"][:3]:
                    out.append(f"- **{a['a_label']}**: {p['statement']} (『{p['work']}』 {p['locator'] or ''}, {p['id']})")
                for p in i["b_positions"][:3]:
                    out.append(f"- **{a['b_label']}**: {p['statement']} (『{p['work']}』 {p['locator'] or ''}, {p['id']})")
            if a["cleavages"]:
                out.append("\n### 개념적 분기선")
                for c in a["cleavages"]:
                    out.append(f"- {a['a_label']}: {c['a_concept']} ↔ {a['b_label']}: {c['b_concept']} ({c['edge_id']})")
            if a["only_a"] or a["only_b"]:
                out.append(f"\n{a['a_label']}에게만 있는 개념: {', '.join(a['only_a']) or '—'}")
                out.append(f"{a['b_label']}에게만 있는 개념: {', '.join(a['only_b']) or '—'}")
        elif intent == "connection" and a:
            out += self._template_connection(a)
        elif intent == "chain" and a:
            out.append("## 연속성과 단절")
            for l in a["links"]:
                out += self._template_connection(l, level="###")
        elif intent == "contradiction" and a:
            out.append("## 핵심 대립 구조")
            for ax in a["axes"][:8]:
                l, r = ax["sides"]
                out.append(f"- **{l['label']} ↔ {r['label']}**: "
                           f"{', '.join(t['label'] for t in l['thinkers'][:5]) or '—'} / "
                           f"{', '.join(t['label'] for t in r['thinkers'][:5]) or '—'}"
                           + (f" — 직접 비판 {len(ax['clashes'])}건" if ax["clashes"] else ""))
        elif intent == "cross_domain" and a:
            out.append("## 분야 간 연결")
            for p in a["domain_pairs"][:8]:
                ex = "; ".join(f"{x['source_label']} {x['predicate_ko']} {x['target_label']} ({x['edge_id']})"
                               for x in p["examples"][:3])
                out.append(f"- {p['a_label']} ↔ {p['b_label']} ({p['count']}): {ex}")
            out.append("\n경계를 넘나든 사상가: " + ", ".join(b["label"] for b in a["bridge_thinkers"][:10]))
        elif intent == "profile" and a:
            d = a["dna"]
            out.append(f"## {d['label']}")
            out.append("주요 분야: " + ", ".join(f"{x['label']}({x['normalized']:.2f})" for x in d["domains"][:5]))
            out.append("핵심 개념: " + ", ".join(x["label"] for x in d["concepts"][:8]))
            if d["similar"]:
                out.append("가까운 사상가: " + ", ".join(f"{s['label']}({', '.join(s['why'][:3])})" for s in d["similar"][:4]))
        else:
            out.append("그래프에서 질문과 직접 연결되는 인물·개념을 찾지 못해, 의미적으로 가까운 명제를 제시합니다.")
        if ctx["propositions"] and intent not in ("genealogy", "compare"):
            out.append("\n### 관련 명제")
            for p in ctx["propositions"][:6]:
                out.append(f"- {', '.join(p['author'])}: {p['statement']} ({', '.join(p['work'])} {p['locator'] or ''}; {p['id']})")
        if ctx["evidence"]:
            out.append("\n### 근거")
            for e in ctx["evidence"][:8]:
                out.append(f"- {e['claim']} — Tier {e['tier']} {e['citation']} {e['locator']} ({e['evidence_id']}, 확신도 {e['confidence']:.2f})")
        out.append("\n_이 답변은 LLM 없이 그래프 경로와 증거만으로 구성되었습니다._")
        return "\n".join(out)

    @staticmethod
    def _template_connection(a: dict, level: str = "##") -> list[str]:
        out = [f"{level} {a['from_label']} → {a['to_label']}", f"**판정:** {a['verdict']}"]
        for s in a["summary"]:
            out.append(f"- {s['label_ko']}: {s['count']}개 경로 (최고 강도 {s['best_strength']:.2f})")
        for kind, items in a["connections"].items():
            for c in items[:2]:
                if c.get("steps"):
                    path = " → ".join([c["steps"][0]["from_label"]] +
                                      [f"[{s['predicate_ko']} {s['edge_id']}] {s['to_label']}" for s in c["steps"]])
                    out.append(f"  - {kind}: {path}")
        return out
