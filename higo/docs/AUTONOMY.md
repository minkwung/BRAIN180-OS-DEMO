# HIGO 자동 갱신 — 1단계(검증 기반) · 2단계(조사 에이전트)

Claude 가 주기적으로 온톨로지를 넓히고 정확하게 만들되, 사람은 **주기별 보고서(PR)를 확인하고 승인하는 일만** 하도록
만드는 기반입니다. 1단계에는 "믿을 수 있는 자동화"에 필요한 장치가 들어 있고, 실제로 웹을 조사하는 에이전트는 2단계에서 붙입니다.

## 한 주기의 흐름

```
data/ 적재 → 품질 기준 측정 → 변경 묶음 적용(원문 대조 → 위험도 분류 → 등급별 반영)
   → 기존 증거 원문 재확인 → 스키마 검사 → 품질 기준 재측정 → 공백 분석
   → data/ 저장 + data/runs/<주기>.md 보고서  →  PR  →  사람이 확인·병합
```

```bash
python -m higo cycle --changeset proposals.json   # 보고서를 출력하고 data/ 와 data/runs/ 에 기록
python -m higo cycle --dry-run                     # 파일을 쓰지 않고 보고서만 확인
```

품질 기준 점수가 떨어지거나 스키마 오류가 생기면 데이터 파일을 쓰지 않고 종료 코드 2 를 돌려줍니다.
자동화에서는 이 경우 PR 을 만들지 않습니다.

## 구성 요소

| 파일 | 역할 |
|---|---|
| `higo/datafiles.py` | **Ontology as Code.** 온톨로지를 `data/entities/*.jsonl`, `data/edges/*.jsonl` 로 저장·적재. 한 줄에 레코드 하나, id 순 정렬이라 PR diff 에 바뀐 사실만 보인다. SQLite 는 언제든 다시 만들 수 있는 캐시 |
| `higo/verify.py` | **인용문 원문 대조.** 증거의 URL 을 다시 열어 인용문이 실제로 있는지 문자열로 확인 (원문 일치 / 부분 일치 / 원문에 없음 / 문서 열기 실패). 내용 해시와 수집 시각을 기록 |
| `higo/policy.py` | **위험도 정책.** 작업 유형과 원문 대조 결과로 위험도를 정한다 |
| `higo/changeset.py` | **변경 묶음 적용기.** 조사 에이전트의 제안(JSON)을 검사하고 등급별로 반영. 표본 감사 대상 선정, 주기 단위 묶음 승인 |
| `higo/gaps.py` | **공백 분석.** 다음에 보강할 곳을 우선순위로 정렬 (에이전트의 작업 목록) |
| `higo/bench.py` + `data/benchmark.json` | **품질 기준 질문 세트.** 주기 전후 채점, 하락 시 병합 보류 |
| `higo/cycle.py` | 위 단계를 묶은 주기 실행과 한국어 보고서 생성 |

웹 UI 의 **자동 갱신** 탭에서 주기 보고서를 읽고, 버튼 하나로 묶음 승인하고, 다음 작업 목록을 볼 수 있습니다.
UI 에서 한 승인·기각은 `data/` 파일에 바로 저장되므로 그대로 커밋하면 됩니다.

## 위험도 정책

| 위험도 | 대상 | 처리 |
|---|---|---|
| 낮음 | 인물·저작·사건·기관의 기본 정보, 저술·분야·소속·시대 관계, 기존 관계에 대한 지지 증거 | **원문 대조를 통과한 경우에만** 자동 반영 (1·2등급 원문 일치 1건 또는 서로 다른 출처 2곳 일치). 보고서에 기록, 5% 표본 감사 |
| 중간 | 개념·학파·명제, 개념 간 관계, 원문 대조를 완전히 통과하지 못한 낮은 위험 항목 | 반영하되 `제안` 상태 → 주기 단위 **묶음 승인** |
| 높음 | 영향·계승·비판(인과), 대립·모순 판단, 반대 증거, 기존 사실의 수정·상태 변경 | 관계는 `가설`로만 기록, 수정·상태 변경은 반영하지 않음 → **개별 판단** |
| 구조 변경 | 새 관계 유형·엔티티 유형 등 스키마 변경 | 반영하지 않음 → 개별 판단 후 온톨로지 버전 올림 |
| 자동 기각 | 인용문이 출처에 없음(출처 날조 의심), 형식·스키마 오류 | 반영하지 않고 보고서에 사유 기록 |

추가 안전장치:
- 인과 관계가 자동 반영되면 스키마 검사가 오류로 잡습니다 (`auto_accepted_causal`).
- 사람 승인·자동 반영 기록은 관계의 `props.review` / `props.auto_accepted` 로 데이터 파일에 남습니다.
- 묶음 승인은 사람 이름이 있어야 하며 `ai:`·`system`·`policy:` 행위자는 거부됩니다.
- 이미 있는 엔티티·관계는 중복 추가하지 않고 증거만 보탭니다. 기존 사실을 바꾸려면 `update_entity` 제안(높음)을 거쳐야 합니다.

## 변경 묶음(changeset) 형식

`examples/changeset.example.json` 참고. 지원 작업: `add_entity`, `add_edge`, `add_proposition`, `add_evidence`,
`update_entity`, `set_status`, `schema_change`. 모든 증거는 `tier`, `url`, `quotation`(해당 URL 페이지의 문장을 그대로)을
가져야 자동 반영 대상이 될 수 있습니다.

## 명령 요약

```bash
python -m higo data export            # 현재 상태를 data/ 로 저장
python -m higo data reseed            # Phase 1 seed 로 data/ 를 다시 생성 (주의: 덮어씀)
python -m higo gaps                   # 공백 분석 표
python -m higo verify                 # 기존 증거 전체 원문 재확인
python -m higo bench                  # 품질 기준 점수
python -m higo approve --run R20260926-01 --actor 홍길동
```

## 운영에 필요한 환경 조건

- **네트워크:** 원문 대조는 출처 사이트에 접속해야 합니다. 실행 환경의 네트워크 허용 목록에 최소한 다음을 넣어야 합니다:
  `plato.stanford.edu`, `iep.utm.edu`, `en.wikisource.org`, `www.wikidata.org`, `www.gutenberg.org`, `www.perseus.tufts.edu`,
  `archive.org`, `philpapers.org`. 접속이 막히면 증거는 "문서 열기 실패"로 판정되어 자동 반영되지 않고 사람 확인으로 넘어갑니다.
- **저작권:** 원문은 저장하지 않고 짧은 인용문과 내용 해시만 저장합니다.

## 2단계: 조사 에이전트 (매주 자동 실행)

```
공백 분석 상위 작업 (유형이 한쪽에 몰리지 않게 섞어서 최대 8개)
  → 작업마다 조사 에이전트 (Claude Opus 5, 사고 모드 adaptive, effort medium)
       도구: 웹 검색·문서 열람(허용 사이트만) + HIGO 조회(search_ontology, get_entity, get_edge)
       결과: propose_changes 로 변경 제안 (그래프를 직접 고치지 못함, 형식 오류는 즉시 돌려받아 수정)
  → 독립 검토자 (별도 호출, 반대 입장): 유지 / 강등 / 삭제
       강등된 제안은 인과 관계면 증거 성격을 '추론'으로 낮추고, 사실 항목이라도 자동 반영하지 않음
  → 1단계 관문: 원문 대조 → 위험도 정책 → 품질 기준 → 보고서 → PR
```

```bash
export ANTHROPIC_API_KEY=...        # pip install anthropic
python -m higo research --budget 5 --max-tasks 8            # data/ 에 반영하고 보고서 출력
python -m higo research --budget 1 --max-tasks 2 --dry-run  # 시험 실행 (반영하지 않음)
```

| 파일 | 역할 |
|---|---|
| `higo/agent.py` | 조사 에이전트, 독립 검토자, 비용 계량기, 작업 선택 |
| `data/sources.json` | 에이전트가 검색·열람할 수 있는 사이트 목록 (편집 가능) |
| `.github/workflows/higo-weekly.yml` | 매주 월요일 03:00(한국 시간) 실행 → PR 생성 |
| `data/runs/<주기>.changeset.json` | 에이전트가 낸 제안 원본 (감사용) |

### 비용 상한

- 모든 호출의 실제 사용량(입력·출력·캐시 읽기/쓰기 토큰, 웹 검색 횟수)으로 비용을 누적합니다.
  Claude Opus 5 기준 입력 $5, 출력 $25 (100만 토큰당), 캐시 읽기는 입력의 0.1배, 웹 검색은 1회 $0.01.
- **다음 호출의 예상 비용(직전 호출의 1.5배, 최소 $0.25)을 더했을 때 상한을 넘으면 호출하기 전에 멈춥니다.**
  그래서 실제 지출은 상한을 넘지 않습니다. 남은 작업은 다음 주기로 넘어갑니다.
- 폴백 등으로 가격표에 없는 모델이 응답하면 보수적으로 비싸게 계산합니다.
- 작업 하나(요청 5~10회, 문서 열람 포함)는 대략 $0.5~1.0 로 예상합니다. 즉 **주기당 5달러면 매주 5~8개 작업**을 처리합니다.
  더 많은 작업을 원하면 `--budget` 을 올리거나, `agent.py` 의 문서 열람 한도(`max_fetches`, `max_content_tokens`)를 줄이면 됩니다.

### 설정 절차 (한 번만)

1. 이 PR 을 기본 브랜치에 병합합니다 (예약 실행은 기본 브랜치의 워크플로만 동작).
2. 저장소 **Settings → Secrets and variables → Actions** 에 `ANTHROPIC_API_KEY` 를 추가합니다.
3. **Settings → Actions → General → Workflow permissions** 에서
   "Allow GitHub Actions to create and approve pull requests" 를 켭니다.
4. (선택) **Actions → HIGO 주간 자동 갱신 → Run workflow** 로 바로 한 번 실행해 봅니다. 비용 상한을 1달러로 낮춰 시험할 수 있습니다.

GitHub Actions 실행 환경은 외부 인터넷이 열려 있어 원문 대조가 실제로 동작합니다.
품질 기준 점수가 떨어지거나 스키마 오류가 생기면 PR 을 만들지 않고 워크플로가 실패로 표시되며, 보고서는 아티팩트로 남습니다.

### 사람이 하는 일

1. 매주 올라오는 PR 의 보고서를 읽습니다 (자동 반영 · 묶음 승인 대기 · 개별 판단 · 구조 변경 · 자동 기각).
2. 🔍 표시된 표본 감사 항목을 확인합니다.
3. 괜찮으면 `python -m higo approve --run <주기> --actor 이름` (또는 웹 UI 자동 갱신 탭의 버튼)으로 묶음 승인 → 커밋 → PR 병합.
4. 가설로 올라온 영향 관계는 시간이 날 때 검증 탭에서 개별 승인·기각합니다. 병합을 미뤄도 다음 주기는 기본 브랜치 기준으로 계속 돕니다.

## 다음 단계

- **3단계:** 품질 기준 질문 확대, 표본 감사 결과에 따른 자율 범위 자동 조정, 스키마 변경 제안.
