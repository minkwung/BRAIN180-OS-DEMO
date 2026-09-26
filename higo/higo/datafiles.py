"""Ontology as Code — 온톨로지를 저장소 안의 텍스트 파일로 관리한다.

    data/
      meta.json                 스키마·온톨로지 버전, ID 카운터, 버전 이력
      entities/<type>.jsonl     엔티티 (유형별, id 순 정렬, 한 줄에 하나)
      edges/<category>.jsonl    관계 + 증거 번들 (범주별, id 순 정렬, 한 줄에 하나)
      runs/<run_id>.json        자동 갱신 주기별 기록

한 줄에 레코드 하나, 키 순서 고정, id 순 정렬이므로 git diff 와 PR 리뷰에서 변경된
사실만 정확히 드러난다. SQLite DB 는 이 파일들로부터 언제든 다시 만들 수 있는 캐시다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import ontology as O
from .store import Store

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

ENTITY_KEYS = ("id", "type", "label", "label_ko", "aliases", "description", "start_year", "end_year",
               "origin", "status", "props")
EDGE_KEYS = ("id", "source", "predicate", "target", "evidence_status", "epistemic_status", "confidence",
             "confidence_override", "origin", "note", "valid_from", "valid_to", "props", "evidence")
EVIDENCE_KEYS = ("id", "tier", "stance", "source_id", "citation", "locator", "url", "quotation",
                 "interpretation", "added_by", "verification", "verified_at", "retrieved_at", "content_hash")


def _clean(d: dict, keys: tuple[str, ...]) -> dict:
    out = {}
    for k in keys:
        v = d.get(k)
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = v
    return out


def _dump_line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def entity_record(e: dict) -> dict:
    return _clean(e, ENTITY_KEYS)


def edge_record(store: Store, e: dict) -> dict:
    rec = dict(e)
    rec["confidence"] = round(e["confidence"], 4)
    rec["evidence"] = [_clean(ev, EVIDENCE_KEYS) for ev in store.list_evidence(e["id"])]
    return _clean(rec, EDGE_KEYS)


def export_data(store: Store, data_dir: str | Path = DEFAULT_DATA_DIR) -> dict:
    root = Path(data_dir)
    (root / "entities").mkdir(parents=True, exist_ok=True)
    (root / "edges").mkdir(parents=True, exist_ok=True)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for e in store.list_entities(limit=10**9):
        by_type[e["type"]].append(entity_record(e))
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for e in store.list_edges():
        by_cat[O.RELATION_TYPES[e["predicate"]].category].append(edge_record(store, e))
    written = []
    for folder, groups in (("entities", by_type), ("edges", by_cat)):
        expected = set()
        for name, rows in groups.items():
            rows.sort(key=lambda r: r["id"])
            fname = f"{name.lower()}.jsonl"
            expected.add(fname)
            (root / folder / fname).write_text("".join(_dump_line(r) + "\n" for r in rows), encoding="utf-8")
            written.append(f"{folder}/{fname}")
        for stale in (root / folder).glob("*.jsonl"):  # 비어 버린 범주 파일 정리
            if stale.name not in expected:
                stale.unlink()
    meta = {
        "schema_version": store.get_meta("schema_version"),
        "ontology_version": store.get_meta("ontology_version"),
        "seed_version": store.get_meta("seed_version"),
        "counters": {k: int(store.get_meta(f"counter:{k}") or 0) for k in ("edge", "evidence", "candidate", "document")},
        "versions": [{k: v for k, v in ver.items() if k != "counts"} for ver in store.list_versions()],
    }
    (root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"files": sorted(written), "entities": sum(len(v) for v in by_type.values()),
            "edges": sum(len(v) for v in by_cat.values())}


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{i}: {exc}") from exc
    return rows


def has_data(data_dir: str | Path = DEFAULT_DATA_DIR) -> bool:
    return (Path(data_dir) / "meta.json").is_file()


def load_data(store: Store, data_dir: str | Path = DEFAULT_DATA_DIR) -> dict:
    """데이터 파일로부터 저장소를 채운다 (빈 저장소 기준)."""
    root = Path(data_dir)
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    n_ent = n_edge = n_ev = 0
    for path in sorted((root / "entities").glob("*.jsonl")):
        for r in _read_jsonl(path):
            store.upsert_entity(r["id"], r["type"], r["label"], label_ko=r.get("label_ko"),
                                aliases=r.get("aliases", []), description=r.get("description", ""),
                                props=r.get("props", {}), start_year=r.get("start_year"),
                                end_year=r.get("end_year"), origin=r.get("origin", "import"),
                                status=r.get("status", "accepted"), actor="data")
            n_ent += 1
    edges = []
    for path in sorted((root / "edges").glob("*.jsonl")):
        edges += _read_jsonl(path)
    edges.sort(key=lambda r: r["id"])
    for r in edges:
        store.add_edge(r["source"], r["predicate"], r["target"], evidence_status=r.get("evidence_status", "direct"),
                       epistemic_status=r.get("epistemic_status", "proposed"), origin=r.get("origin", "import"),
                       note=r.get("note", ""), props=r.get("props", {}),
                       confidence_override=r.get("confidence_override"), valid_from=r.get("valid_from"),
                       valid_to=r.get("valid_to"), actor="data", edge_id=r["id"])
        n_edge += 1
        for ev in r.get("evidence", []):
            store.add_evidence(r["id"], tier=ev["tier"], source_id=ev.get("source_id"), citation=ev.get("citation", ""),
                               stance=ev.get("stance", "supports"), locator=ev.get("locator", ""),
                               quotation=ev.get("quotation", ""), interpretation=ev.get("interpretation", ""),
                               added_by=ev.get("added_by", "data"), url=ev.get("url", ""),
                               retrieved_at=ev.get("retrieved_at"), content_hash=ev.get("content_hash", ""),
                               verification=ev.get("verification", ""), verified_at=ev.get("verified_at"),
                               evidence_id=ev.get("id"), recompute=False, log=False)
            n_ev += 1
        store.recompute_confidence(r["id"], log=False)
    for key in ("schema_version", "ontology_version", "seed_version"):
        if meta.get(key):
            store.set_meta(key, meta[key])
    for name, value in (meta.get("counters") or {}).items():
        cur = int(store.get_meta(f"counter:{name}") or 0)
        if value > cur:
            store.set_meta(f"counter:{name}", str(value))
    with store.tx() as c:
        for ver in meta.get("versions", []):
            c.execute("INSERT OR REPLACE INTO ontology_versions VALUES (?,?,?,?)",
                      (ver["version"], ver.get("note", ""), "{}", ver.get("created_at")))
    return {"entities": n_ent, "edges": n_edge, "evidence": n_ev}
