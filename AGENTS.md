# AGENTS.md

이 저장소에서 작업하는 코딩 에이전트와 팀원의 공통 기준입니다. 협업 절차는 `CONTRIBUTING.md`, 단계별 작업은 `docs/guides/`를 따릅니다.

## 프로젝트

기업 뉴스와 공시를 수집해 기업·인물·브랜드·행사의 관계를 지식그래프로 연결하고, 근거 문서와 함께 질문에 답하는 GraphRAG 프로젝트입니다.

- 대상: 아모레퍼시픽, 이니스프리, 에스쁘아, 에뛰드, 퍼시픽테크, 아모스프로페셔널, 코스알엑스
- 스택: Python 3.12+, uv, Neo4j Aura, OpenAI API, LangGraph, Jupyter
- 패키지: `bulsae` (`src/bulsae/`)
- 현재 단계: 파일럿. 온톨로지와 대표 질문은 최종 확정 전입니다.

## 폴더 구조

```text
AGENTS.md                  에이전트 공통 기준 (이 파일)
README.md                  프로젝트 소개와 현재 상태
CONTRIBUTING.md            브랜치, PR, 공개 금지 규칙
docs/guides/               담당별 가이드
  01_프로젝트_이해_가이드.md
  02_데이터_검증_작업_가이드.md
  03_개발_단계별_가이드.md   스프린트와 완료 내역
  04_LangGraph_설계_가이드.md 처리 흐름 설계와 확장 방법
src/bulsae/
  dart_companies.py        DART 기업 정보
  graphrag/
    prepare.py             뉴스 청크 생성 (외부 호출 없음)
    pipeline.py            추출, 근거 검사, 적재, 질의
    graphs.py              LangGraph 문서 기반 질의 흐름
    company_nodes.py       기업 노드 후보 생성
    README.md              파일럿 실행 안내
data_code/                 수집과 실험 노트북
  new.ipynb                뉴스 수집
  company_info.ipynb       기업 정보
  financials.ipynb         재무 자료
  graph.ipynb              그래프 개념, 청크 분할
  AuraDB.ipynb             Aura 적재, 임베딩
  GraphRAG_질문_답변_테스트.ipynb 질문·답변과 출처 확인
data/
  collected/               공통 수집 데이터
  processed/               청크 등 가공 결과
  raw/                     원문 (Git 제외)
  review/                  사람 검토 결과 (본문 없는 CSV)
tests/                     unittest
private_data/              로컬 전용 파일 (Git 제외, 노트북은 S0-2 전까지 예외)
```

정리 예정인 경로입니다. 새 작업을 추가하지 않습니다.

| 경로 | 내용 | 예정 |
|---|---|---|
| `src/docs/`, `dashboard/` | 이전 주제인 과수 서비스 기록 | `docs/archive/orchard/`로 이동 |
| `.codex/agents/` | 과수 아이디어 회의용 에이전트 | 현재 개발과 무관 |
| `data_code/<기업>/` | 뉴스 수집 체크포인트 | Git 제외 |

## 아키텍처

```text
네이버 뉴스 API ─ new.ipynb ──────────────┐
DART ─ company_info / financials.ipynb ──┤
                                         ▼
                             data/collected/*.jsonl
                                         │ 청크 분할
                                         ▼
                             data/processed/news_chunks_*.jsonl
                                         │
                ┌────────────────────────┴──────────────────┐
                ▼ 임베딩                                     ▼ 관계 추출 (OpenAI)
          Chunk.embedding                          claims / rejected
          text-embedding-3-small (1,536)                     │ 인용 존재 검사
                │                                            │ 사람 검토
                └───────────────► Neo4j Aura ◄───────────────┘
                                      │
                                      ▼
              질문 → 벡터 검색 + 연결 관계 확장 → 출처가 붙은 답변
```

### 그래프 모델

`src/bulsae/graphrag/pipeline.py`가 기준입니다.

아래 Claim/Chunk 구조는 기존 파일럿입니다. 사용자의 최신 설계에서는
`BulsaeDocument.content` 전체에서 관계 후보를 추출하고 문서·청크 노드에
지식그래프 관계선을 만들지 않습니다. `pipeline extract-documents`가 이 경로이며,
후보 노드는 `BulsaeKGCandidate`와 공통 `Bulsae{유형}` 라벨을 사용하고 조사 대상
기업은 기존 `BulsaeCompany.company_id`를 재사용합니다. 이름만으로 서로 다른
문서의 후보를 물리적으로 병합하지 않습니다. 일부 후보는 근거를 확인해
`NORMALIZED_AS`로 대표 노드에 연결하며 연결은 검토 전입니다. 검색은 해당 관계를
따라 근거를 함께 읽되 대표 노드가 다른 동명이인을 섞지 않습니다. 팀원 `B_` 라벨
데이터는 정규화 대상에서 제외합니다. 관계는 설계된 19개 유형 중 허용된 방향만
사용하고 `kg_observation_id`, `source_document_id`, 문서 해시, 근거 줄·위치 및
`verification_status='검토 전'`을 기록합니다. 기존 재무는 기업 ID로 연결한
`HAS_FINANCIAL` 관계를 사용합니다. 자동 후보를 검증된 사실로 취급하지 않습니다.
`private_data/` 체크포인트는 원문 근거가 포함될 수 있으므로 공유하지 않습니다.

```text
(Document)-[:HAS_CHUNK]->(Chunk)
(Claim)-[:SUBJECT]->(Entity)
(Claim)-[:OBJECT]->(Entity)
(Claim)-[:SUPPORTED_BY]->(Chunk)
(Entity)-[:HAS_FINANCIAL_RECORD]->(FinancialRecord)
```

- `Claim`은 관계 하나를 나타내며 기본 `review_status`는 `unreviewed`입니다.
- 관계 종류: `OWNS`, `OPERATES`, `PARTNERS_WITH`, `ACQUIRED`, `INVESTED_IN`, `LEADS`, `LAUNCHED`, `PARTICIPATED_IN`, `ANNOUNCED`, `RELATED_TO`
- 벡터 인덱스: `bulsae_chunk_embedding`
- 노트북이 적재한 기존 노드는 `BulsaeDocument`, `BulsaeChunk` 라벨을 씁니다. 연결 방법은 `docs/guides/03_개발_단계별_가이드.md` S2-1을 따릅니다.

### 데이터 규격

| 파일 | 필수 필드 | 기준 |
|---|---|---|
| `companies.jsonl` | `company_id`, `input_name`, `legal_name`, `dart_corp_code` | 기업 ID의 기준 |
| `company_info.jsonl` | `company_id`, `industry`, `listing_status`, `employee_count`, `established_date`, `field_sources` | 기업당 1행 |
| `financials.jsonl` | `financial_id`, `company_id`, `fiscal_year`, `period`, `statement_scope`, `revenue_krw`, `operating_profit_krw`, `source` | 금액 단위는 원 |
| `news.jsonl` | `document_id`, `title`, `original_url`, `published_at`, `content`, `company_ids` | 본문 포함, Git 제외 대상 |
| 청크 (`pipeline.py` 입력) | `chunk_id`, `document_id`, `text`, `start_char`, `end_char`, `content_sha256` | 본문 포함, Git 제외 대상 |

`news_chunks_v1.jsonl`에는 `start_char`, `end_char`, `content_sha256`이 없습니다. `pipeline.py`에는 v2를 사용합니다. 기존 ID 형식을 바꾸지 않습니다.

수집과 가공 데이터는 UTF-8 JSONL입니다. 파일을 읽고 쓸 때 `encoding="utf-8"`을 명시합니다.

## 명령

저장소 최상위 폴더에서 실행합니다.

```bash
uv sync                                                # 환경 설치
uv run python -m unittest discover -s tests            # 테스트
uv run python -m bulsae.graphrag.prepare <입력> <출력>  # 청크 생성
```

- Windows에서 인코딩 오류가 나면 `PYTHONUTF8=1`을 설정합니다.
- 노트북은 `data_code/`에서 실행되므로 상대 경로는 `../data/...`입니다.
- 환경변수는 `.env`에 둡니다: `OPENAI_API_KEY`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`, `DART_API_KEY`, `DATA_GO_KR_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- `neo4j` 패키지가 `pyproject.toml`에 추가되기 전에는 적재와 질의 명령을 실행할 수 없습니다.

## 반드시 지킬 규칙

### 공개 금지

이 저장소는 공개 상태일 수 있습니다. 아래를 커밋하거나 PR에 넣지 않습니다.

- `.env`, API 키, DB 접속 정보
- 기사나 공시 본문, 본문이 든 청크, 추출 결과, 체크포인트
- 실행 출력이 남은 노트북
- 개인 PC의 절대 경로

커밋 전에 확인합니다.

- `git add .`을 쓰지 않고 파일을 지정합니다.
- `git diff --cached --stat`으로 올라갈 파일을 확인합니다.
- 큰 `.jsonl`, 기사 문장이 포함된 파일이 있으면 멈추고 사용자에게 알립니다.
- 노트북을 수정했다면 출력을 지웁니다.

본문이 든 새 결과는 `private_data/`에 저장합니다. 예외는 `.gitignore`에 등록된 `data/collected/news.jsonl`, `data/processed/*.jsonl`입니다. 커밋 전에 `git check-ignore`로 제외 여부를 확인합니다.

### 사용자에게 먼저 확인

아래 작업은 사용자가 명시적으로 요청한 경우에만 실행합니다.

- 비용이 드는 호출: `pipeline extract`, `load`, `ask`, 임베딩. 실행 전 대상 건수를 알립니다.
- Neo4j Aura의 데이터 변경이나 삭제
- `main`에 직접 커밋 또는 push, force push, 이력 재작성
- 데이터 파일 삭제나 덮어쓰기
- 다른 사람의 브랜치 수정, PR 머지

### 구조 유지

- 새 파이프라인을 만들지 않습니다. `src/bulsae/graphrag/`를 확장합니다.
- 사람 이름이 들어간 데이터 폴더나 스크립트를 만들지 않습니다.
- 같은 기능의 파일을 새로 만들기 전에 기존 코드를 먼저 찾습니다.
- 그래프 라벨, 관계 종류, ID 형식, 데이터 필드를 바꿀 때는 먼저 사용자에게 알리고 이 파일도 함께 고칩니다.
- `companies.jsonl`의 `company_id`를 그대로 사용합니다.
- 추출 결과를 사람 검토 없이 사실로 표시하지 않습니다.

### LangGraph

- 구축과 질의 흐름은 `graphs.py`에 둡니다. 설계 변경은 `docs/guides/04_LangGraph_설계_가이드.md`의 절차를 따르고 그림과 결정 기록을 함께 고칩니다.
- 노드에서 외부 API나 DB를 직접 호출하지 않고 `deps`로 받습니다.
- `interrupt`를 호출하는 노드에는 파일 저장이나 API 호출을 넣지 않습니다.
- 되돌아가는 분기에는 횟수 제한을 둡니다.
- State에 DB 연결, 비밀값, 임베딩 벡터를 넣지 않습니다.
- 체크포인트 파일은 `private_data/`에 저장합니다.

### 결과 보고

작업이 끝나면 아래를 사용자가 이해할 수 있게 설명합니다. PR 본문도 같은 기준으로 씁니다.

- 무엇을 왜 바꿨는지
- 무엇을 실행해 확인했는지, 건수와 실패 내역
- 확인하지 못한 것

실행하지 않은 검증을 했다고 쓰지 않습니다. 건수는 파일이나 명령 결과에서 확인한 값만 씁니다. 건수는 작업 완료의 증거가 아니며, 코드 작성, 실행, 사람 검증, `main` 반영을 구분해서 적습니다.

인용이 원문에 있다는 검사는 내용이 사실이라는 뜻이 아닙니다. 기사는 "보도된 내용"으로 표현합니다.

사용자 요청에 따라 질의 화면에서는 원문 대조와 자동 답변 검사를 통과한 내용을
사람의 추가 승인 없이 표시합니다. 내부 `검토 전` 상태를 매 답변에 안내하지 않습니다.
설명은 쉬운 한국어로 작성하고 원문 인용·출처는 별도로 제공합니다. 이 표시 정책은
DB 상태를 사람 검증 완료로 바꾸거나 실제 근거 부족·불일치 검사를 생략하는 뜻이 아닙니다.

## 코드 스타일

- 표준 라이브러리와 이미 설치된 패키지를 먼저 사용합니다.
- 작고 읽기 쉬운 변경을 우선합니다. 요청하지 않은 리팩터링을 함께 하지 않습니다.
- 외부 API를 호출하지 않는 함수에 테스트를 추가합니다. 테스트에서는 실제 API나 DB를 호출하지 않습니다.
- 기존 출력 파일을 덮어쓰지 않습니다. `pipeline.py`처럼 새 파일 생성(`x` 모드)을 사용합니다.

## 참고 문서

| 문서 | 내용 |
|---|---|
| `docs/guides/01_프로젝트_이해_가이드.md` | 프로젝트 개념과 흐름 |
| `docs/guides/02_데이터_검증_작업_가이드.md` | 원문 대조 작업 |
| `docs/guides/03_개발_단계별_가이드.md` | 스프린트, 완료 내역, 알려진 제약 |
| `docs/guides/04_LangGraph_설계_가이드.md` | 처리 흐름 설계, 개선 접근 방법 |
| `src/bulsae/graphrag/README.md` | 파이프라인 실행 |
| `CONTRIBUTING.md` | 브랜치, PR 양식 |

### 질의 근거 구분 (2026-11-09)

질의 결과의 `source_kind=document`는 독립 원문 검색 결과이며 Neo4j 관계가 아니다.
기존 그래프 결과와 함께 조회하되 품질 패널에 가상 관계를 만들지 않는다.
질의 상태의 `document_search_count`, `financial_context_kind`, 경로의 `event_year`는
런타임 메타데이터다. DB 노드·관계 필드를 추가하거나 사람 검토 상태를 변경하지 않는다.
기업명 내부 공백은 허용하지만 법인·그룹·재단 이름의 경계는 유지한다.
답변 생성 모델은 원문 구간의 번호(`quote_ids`)를 선택한다. 실제 `exact_quote`는
코드가 복원하며, 잘못된 번호를 유사한 구간으로 추정해서 대신 연결하지 않는다.

답변 뒤 공통 `enrich` 단계는 원래 `question`을 유지하며 관련 자료를 읽기 전용으로
검색한다. `related_points`, `related_evidence`, `related_search_query`, `related_status`는
`basic_answer`와 함께 런타임 필드다. 추가 문단은 보도 사실·회사 원인 설명·자료 종합 해석으로 구분하고
인용과 의미 검사를 통과한 항목만 표시한다. 회사 원인 설명에는 회사의 직접 귀속,
종합 해석에는 서로 다른 문서 둘 이상의 근거가 필요하다. 추가 분석 실패 시 기본
답변은 유지하며 답변 이후 추천·후속 질문을 표시하지 않는다. DB 스키마는 바꾸지 않는다.

골든셋 회귀 검사에서는 기존 질문과 기대답변을 바꾸지 않고 실제 응답을 따로 저장합니다.
`joint_query`, 문단 `kind`/`section_type`, `trace.review_model`은 질의 결과 필드이며 DB 스키마가 아닙니다.
기업 간 공동 관계 조회는 `resolved_multi`로 분기하며 정형 재무와 그룹 뉴스의 주체를 분리합니다.
웹 검증 모델은 `BULSAE_REVIEW_MODEL`로 설정합니다. 회사의 계획 발표는 원인 설명으로 분류하지 않습니다.

추가 분석의 의미 검사는 원래 질문에 대한 관련성을 별도로 확인합니다. 종합 해석에는
서로 다른 전제가 필요하며 같은 URL·복제 인용만으로는 통과하지 않습니다.
`related_errors`는 단계와 예외 유형만 보관하는 런타임 기록입니다. DB 필드가 아니며
추가 분석 오류가 기본 답변·출처를 지우지 않도록 유지합니다.
`related_diagnostics`도 런타임 기록으로, 분석 후보 수·인용 검사 통과 수·의미 검사 결과를 보관합니다.
인용 원문에는 상대 날짜 표현이 있을 수 있습니다. 원문 일치 검사와 생성 답변의 날짜 검사를 구분합니다.

재무 추가 분석은 `business_paths` 의존성으로 기존 불새 소유 사업 관계를 1~2홉 탐색한 뒤,
관계별 `source_document_id`로 원문을 읽습니다. 부족한 기업·분석 관점만 원문 검색으로 보완합니다.
`related_graph_paths`, `trace.graph_paths`, `trace.answer_graph_paths`, `trace.retrieved_graph_hops`는
실행 기록입니다. 문서 ID 조회와 정규화 보조 링크를 사업 관계 홉으로 세지 않습니다.
조회 경로와 최종 답변에 사용한 경로를 구분하고 팀원 `B_` 노드를 통과하지 않습니다.

최종 `finalize` 단계는 채택된 답변의 사실·정형 수치로 요약과 LLM 분석을 작성합니다.
이 단계의 해석에는 문서 2건 조건을 적용하지 않으며, 근거 있는 전제와 범위 보존을 검사합니다.
이전 해석을 사실 전제로 재사용하지 않고, 분석의 불확실성 문구는 화면과 저장 답변에 한 번만 넣습니다.
`final_output`과 `trace.final_composition`은 런타임 필드이며 DB 변경이 아닙니다.

행사 참여 답변의 `event_cards`, `event_dashboard`는 런타임 출력입니다. 채택된 사실로
행사별 소개와 발표·활동을 작성하고 실제 참석·주체·연도 검사를 통과한 카드만 표시합니다.
행사 건수는 같은 행사·연도를 통합한 카드 수이며 근거 기사 수와 구분합니다.
없는 행사 설명이나 발표 내용은 채우지 않습니다. DB 스키마·상태는 변경하지 않습니다.
