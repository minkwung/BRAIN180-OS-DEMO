"""자동 갱신 주기 — 데이터 적재 → 품질 측정 → 변경 묶음 적용 → 원문 대조 → 검증 → 품질 재측정 →
데이터 파일 저장 → 주기 기록과 보고서(PR 본문) 작성.

    python -m higo cycle --changeset proposals.json

보고서는 data/runs/<run_id>.md 에, 기계용 기록은 data/runs/<run_id>.json 에 남는다.
품질 점수가 떨어지거나 스키마 오류가 생기면 종료 코드 2 를 돌려 PR 을 만들지 않게 한다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import datafiles, gaps
from .bench import load_benchmark, run_benchmark
from .changeset import ChangesetApplier, new_run_id
from .core import HIGO
from .policy import HIGH, LOW, MEDIUM, REJECTED, RISK_KO, STRUCTURAL
from .verify import STATUS_KO, QuoteVerifier

OUTCOME_KO = {"applied_accepted": "자동 반영", "applied_proposed": "반영(승인 대기)",
              "applied_hypothesis": "가설로 기록", "pending": "사람 판단 대기", "rejected": "기각",
              "skipped": "중복·생략"}


def run_cycle(data_dir: str | Path = datafiles.DEFAULT_DATA_DIR, changeset: dict | None = None,
              verifier: QuoteVerifier | None = None, reverify_existing: bool = True,
              benchmark_path: str | Path | None = None, write: bool = True) -> dict:
    data_dir = Path(data_dir)
    runs_dir = data_dir / "runs"
    run_id = new_run_id(runs_dir)
    h = HIGO(":memory:", data_dir=data_dir)
    h.seed()
    verifier = verifier or QuoteVerifier()
    questions = load_benchmark(benchmark_path or data_dir / "benchmark.json")
    before_stats = h.store.stats()
    bench_before = run_benchmark(h, questions) if questions else None

    applied = None
    if changeset:
        applied = ChangesetApplier(h.store, verifier, run_id).apply(changeset)
    reverify = verifier.verify_store(h.store, actor=f"verifier:{run_id}") if reverify_existing else None

    validation = h.validate()
    bench_after = run_benchmark(h, questions) if questions else None
    gap = gaps.analyze(h.store, gaps.load_roadmap(data_dir))
    after_stats = h.store.stats()

    regression = bool(bench_before and bench_after and bench_after["score"] < bench_before["score"] - 1e-9)
    ok = validation["ok"] and not regression
    record = {"run_id": run_id, "started": time.time(), "ok": ok, "regression": regression,
              "stats_before": _brief(before_stats), "stats_after": _brief(after_stats),
              "benchmark_before": bench_before, "benchmark_after": bench_after,
              "validation": {"ok": validation["ok"],
                             "errors": [i for i in validation["issues"] if i["level"] == "error"][:50]},
              "changeset": applied, "reverify": reverify,
              "gaps": {"total": gap["total"], "summary": gap["summary"], "top": gap["tasks"][:20]}}
    report = render_report(record, gap)
    if write:
        if ok:
            datafiles.export_data(h.store, data_dir)
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / f"{run_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str) + "\n",
                                                 encoding="utf-8")
        (runs_dir / f"{run_id}.md").write_text(report, encoding="utf-8")
    record["report"] = report
    return record


def _brief(stats: dict) -> dict:
    return {k: stats[k] for k in ("entities", "edges", "evidence")} | {"edges_by_status": stats["edges_by_status"]}


def _delta(a: int, b: int) -> str:
    d = b - a
    return f"{b} ({'+' if d >= 0 else ''}{d})"


def render_report(rec: dict, gap: dict) -> str:
    L: list[str] = []
    rid = rec["run_id"]
    status = "✅ 병합 가능" if rec["ok"] else "⛔ 병합 보류 — 아래 문제 해결 필요"
    L += [f"# HIGO 자동 갱신 보고서 {rid}", "", f"**상태:** {status}", ""]
    b, a = rec["stats_before"], rec["stats_after"]
    L += ["## 요약", "", "| 항목 | 이번 주기 후 (변화) |", "|---|---|",
          f"| 엔티티 | {_delta(b['entities'], a['entities'])} |",
          f"| 관계 | {_delta(b['edges'], a['edges'])} |",
          f"| 증거 | {_delta(b['evidence'], a['evidence'])} |"]
    if rec["benchmark_before"]:
        sb, sa = rec["benchmark_before"]["score"], rec["benchmark_after"]["score"]
        mark = "⚠️ 하락" if rec["regression"] else ("상승" if sa > sb else "유지")
        L.append(f"| 품질 기준 점수 | {sa:.1%} (이전 {sb:.1%}, {mark}) |")
    L.append(f"| 스키마 검사 | {'통과' if rec['validation']['ok'] else '오류 ' + str(len(rec['validation']['errors'])) + '건'} |")
    L.append("")

    cs = rec.get("changeset")
    if cs:
        results = cs["results"]
        audit = set(cs.get("audit_sample", []))
        agent = cs.get("agent") or {}
        if agent:
            L += [f"제안 작성: {agent.get('model', '?')} · 지시문 {agent.get('prompt_version', '?')}", ""]
            cost = agent.get("cost")
            if cost:
                L += ["### 조사 비용", "", "| 항목 | 값 |", "|---|---|",
                      f"| API 비용 | ${cost['spent_usd']:.2f} / 상한 ${cost['budget_usd']:.2f} |",
                      f"| API 호출 | {cost['calls']}회 |",
                      f"| 웹 검색 | {cost['web_searches']}회 |",
                      f"| 토큰 (입력 / 캐시 읽기 / 출력) | {cost['input_tokens']:,} / {cost['cache_read_tokens']:,} / "
                      f"{cost['output_tokens']:,} |", ""]
            tasks = agent.get("tasks") or []
            if tasks:
                stop_ko = {"end_turn": "완료", "budget": "예산 소진", "max_requests": "호출 한도", "refusal": "거절",
                           "max_tokens": "출력 한도"}
                L += ["### 조사한 작업", "", "| 작업 | 대상 | 제안 | 검토(유지/강등/삭제) | 비용 | 종료 | 요약 |",
                      "|---|---|---|---|---|---|---|"]
                for t in tasks:
                    L.append(f"| {t['label_ko']} | {t.get('target') or '—'} | {t['proposed']} | "
                             f"{t['kept']}/{t['downgraded']}/{t['dropped']} | ${t['cost_usd']:.2f} | "
                             f"{stop_ko.get(t['stop'], t['stop'])} | {(t.get('summary') or '').replace('|', '/')[:160]} |")
                L.append("")
        groups = [(LOW, "## 1. 자동 반영 (위험도 낮음)", "원문 대조를 통과한 사실 확인형 항목입니다. "
                   "🔍 표시는 무작위 표본 감사 대상이니 확인해 주세요."),
                  (MEDIUM, "## 2. 묶음 승인 대기 (위험도 중간)", f"확인 후 `python -m higo approve --run {rid} --actor 이름` "
                   "으로 한 번에 승인합니다. 문제가 있는 항목은 웹 UI 검증 탭에서 개별 기각하세요."),
                  (HIGH, "## 3. 개별 판단 필요 (위험도 높음)", "영향·비판·대립 같은 해석 판단이나 기존 지식의 수정입니다. "
                   "관계는 '가설'로만 기록되었고, 수정·상태 변경은 반영되지 않았습니다."),
                  (STRUCTURAL, "## 4. 구조 변경 제안", "스키마 변경은 반영되지 않았습니다. 채택하면 온톨로지 버전을 올립니다."),
                  (REJECTED, "## 5. 자동 기각", "형식 오류이거나, 인용문이 출처에 없어(출처 날조 의심) 반영하지 않았습니다.")]
        for risk, title, desc in groups:
            rows = [r for r in results if r["risk"] == risk]
            if not rows:
                continue
            L += [title, "", desc, "", "| # | 내용 | 결과 | 근거 판정 | 사유 |", "|---|---|---|---|---|"]
            for r in rows:
                verd = ", ".join(STATUS_KO.get(v["status"], v["status"]) for v in r["verification"]) or "—"
                reason = "; ".join(r["reasons"])[:220].replace("|", "/")
                mark = " 🔍" if r["index"] in audit else ""
                refs = " ".join(f"`{x}`" for x in r["refs"][:3])
                L.append(f"| {r['index']}{mark} | {r['summary'].replace('|', '/')} {refs} | "
                         f"{OUTCOME_KO.get(r['outcome'], r['outcome'])} | {verd} | {reason} |")
            L.append("")
    else:
        L += ["이번 주기에는 새 변경 제안이 없었습니다 (기존 증거 재확인과 공백 분석만 수행).", ""]

    rv = rec.get("reverify")
    if rv and rv["counts"]:
        L += ["## 기존 증거 원문 재확인", "", "| 판정 | 건수 |", "|---|---|"]
        for k, n in sorted(rv["counts"].items()):
            L.append(f"| {STATUS_KO.get(k, k)} | {n} |")
        L.append("")
    if not rec["validation"]["ok"]:
        L += ["## 스키마 오류", ""] + [f"- {e['message']} ({e.get('ref')})" for e in rec["validation"]["errors"][:20]] + [""]
    if rec["benchmark_after"]:
        failed = [i for i in rec["benchmark_after"]["items"] if i["failed"]]
        if failed:
            L += ["## 품질 기준 미달 질문", ""]
            L += [f"- {i['question']} — {'; '.join(i['failed'])}" for i in failed] + [""]
    L += ["## 다음 주기 작업 (공백 분석)", "", gaps.to_markdown(gap, top=12), ""]
    L += ["---", "_이 보고서는 HIGO 자동 갱신 주기가 생성했습니다. 위험도 정책: "
          + ", ".join(f"{k}={v}" for k, v in RISK_KO.items()) + "_"]
    return "\n".join(L) + "\n"
