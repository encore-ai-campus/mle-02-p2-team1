# 수연 담당 그래프 매핑 및 적재 현황

기준일: 2026-11-04
범위: 이니스프리(`COMPANY-INNISFREE`)·에스쁘아(`COMPANY-ESPOIR`)의 문서 및 담당자별 조사 파일 6종
목적: 기존 JSONL 필드와 출처 연결을 보존하는 그래프 매핑·적재 상태를 기록한다.

## 현재 상태

Neo4j Python 드라이버와 LangGraph 의존성을 추가하고, 수연 범위만 적재하는 `src/neo4j_suyeon.py`를 준비했다. 로컬 Neo4j 2026.06.0 인증 연결과 실제 적재를 확인했으며 현재 이니스프리·에스쁘아 `Company` 2개, `Document` 232개, `Fact` 95개가 있다. 회사·문서·사실 ID 제약조건과 전문 검색 인덱스를 사용한다. OpenAI 추출 결과는 1,033개 청크 처리와 후보 정규화를 마쳤지만, 기존 자료와 Neo4j에는 합치지 않았다. CONNECT 설계 사이트의 구조도 페이지를 현재 조회할 수 없어 노드·관계 라벨은 제안으로 표시한다. 팀의 확정 스키마와 대조하기 전에는 이 라벨을 최종 스키마로 취급하지 않는다.

## 기본 원칙

- 기존 `company_id`, `document_id`, `record_id`를 그래프의 안정된 키로 그대로 쓴다. 표시명으로 식별자를 다시 만들지 않는다.
- 팀 공통 `Company` 노드를 사용하고, 담당 자료에서 같은 회사를 중복 생성하지 않는다.
- 조사 파일의 한 레코드를 하나의 사실 노드로 보존한다. 사실 노드에는 `content`, `evidence_text`, `evidence_location`, `as_of_date`, `verification_status`와 영역별 필드를 유지한다.
- 모든 사실은 해당 회사 노드와 출처 문서 노드에 연결한다. `clean_text`는 문서 검색용이고, 사실 검증은 각 레코드의 근거 필드로 추적한다.
- API 키, 개인 연락처, 요청 인증정보는 그래프 속성으로 넣지 않는다. 원문 파일 경로는 팀 저장 위치에서 접근 가능한지 확인한 뒤 필요할 때만 저장한다.
- `null`은 미확인으로 유지한다. 그룹 합산값을 개별 회사 값으로 나누지 않는다.

## JSONL → 그래프 초안 매핑

| 입력 | 노드(제안) | 고유 키 | 연결(제안) | 중요 속성 |
| --- | --- | --- | --- | --- |
| `data/shared/companies.jsonl` | `Company` | `company_id` | — | `input_name`, `legal_name`, `corp_code`, `assignee` |
| `data/collected/suyeon/documents.jsonl` | `Document` | `document_id` | `Company` ← `ABOUT` → `Document` | `source_type`, `source_name`, `title`, `original_url`, `published_at`, `clean_text`, `processing_status` |
| `company_info.jsonl` | `Fact` | `record_id` | `Company` → `HAS_FACT` → `Fact` → `SUPPORTED_BY` → `Document` | `domain`, `revenue_krw`, `operating_profit_krw`, `fiscal_year`, `period`, `statement_scope`, 근거·검증 필드 |
| `social_issues.jsonl` | `Fact` | `record_id` | `Company` → `HAS_FACT` → `Fact` → `SUPPORTED_BY` → `Document` | `issue_type`, `event_date`, `relation_scope`, `company_role`, `event_status` |
| `politics.jsonl` | `Fact` | `record_id` | 동일한 사실·문서 연결 | 현재 수연 담당 파일은 0건이므로 생성 노드 없음 |
| `market.jsonl` | `Fact` | `record_id` | `Company` → `HAS_FACT` → `Fact` → `SUPPORTED_BY` → `Document` | `market_type`, `market_scope`, `geography`, `period`, `metric`, `value`, `unit`, `relevance_type` |
| `strategies.jsonl` | `Fact` | `record_id` | `Company` → `HAS_FACT` → `Fact` → `SUPPORTED_BY` → `Document` | `strategy_type`, `announced_at`, `target_period`, `stage` |
| `owners.jsonl` | `Fact` + 주주 주체(제안) | `record_id` / 확인된 주체명 | `Company` → `HAS_FACT` → `Fact`; 필요 시 주주 주체 → `SHAREHOLDER_OF` → `Company` | `person_name`, `role_type`, `position`, `ownership_percent`, `as_of_date` |
| `data/shared/company_relations.jsonl` | 팀 공통 관계 또는 관계 노드(팀 설계 확인 필요) | `record_id` | 회사·기업집단 관계 | `related_company_id`, `group_name`, `relation_type`, `ownership_percent` |

`ABOUT`, `HAS_FACT`, `SUPPORTED_BY`, `SHAREHOLDER_OF`는 읽기 쉬운 제안 라벨일 뿐 CONNECT에서 확정한 이름이 아니다. `company_relations.jsonl`의 그룹명을 별도 노드로 만들지, 관계 속성으로 보관할지도 공통 설계에 맞춰 결정한다.

## 적재 순서

1. `shared/companies.jsonl`에서 팀 공통 회사 노드를 확인한다.
2. 수연 `documents.jsonl`을 `document_id` 기준으로 등록하고 문서 메타데이터·정제 본문을 연결한다.
3. 6개 조사 파일을 `record_id` 기준으로 사실 노드로 넣고 `company_id` 및 `document_id` 연결을 건다.
4. 공통 `company_relations.jsonl`은 팀 관계 스키마를 확인한 뒤 한 번만 적재한다.
5. 같은 `record_id` 재적재 시 중복 생성하지 않도록 `MERGE` 또는 동등한 멱등 처리를 사용한다.
6. 대표 사실의 조회 결과에서 회사 → 사실 → 출처 문서와 근거 문구까지 왕복 확인한다.

## 수연 범위의 현재 규모

| 파일 | 이니스프리 참조 | 에스쁘아 참조 | 비고 |
| --- | ---: | ---: | --- |
| 문서 | 124 | 125 | 일부 문서는 두 회사 모두에 연결되므로 더하면 고유 문서 수 232를 초과한다 |
| 기업정보 | 20 | 16 | 재무 기간·회사별 사실 노드 |
| 사회 이슈 | 7 | 2 | 점주 주장·언론 분석은 확정 사실과 분리 |
| 정치·정책 | 0 | 0 | 확인된 직접 활동 레코드 없음 |
| 시장 | 11 | 8 | 산업 일반 지표와 기업 직접 지표 구분 |
| 전략 | 9 | 7 | 발표 자료의 개별 브랜드 활동만 연결 |
| 오너 | 9 | 6 | 2025-12-31 지분율 스냅샷 포함 |

## 대표 출처 추적 예

- 이니스프리 2025년 연간 매출·영업이익: `COMPANY_INFO-SY-026` → `DOC-SY-DART-20260401003769` → 감사보고서 손익계산서 행.
- 에스쁘아 2025년 연간 매출·영업손실: `COMPANY_INFO-SY-011` → `DOC-SY-DART-20260326001214` → 감사보고서 손익계산서 행.
- 이니스프리 지분 90.4%: `OWNER-SY-014` → `DOC-SY-KRX-APH-2025-ANNUAL`.
- 에스쁘아 지분 100.0%: `OWNER-SY-015` → `DOC-SY-KRX-APH-2025-ANNUAL`.
- 2026년 1분기 제품 활동: `STRATEGY-SY-015`(이니스프리), `STRATEGY-SY-016`(에스쁘아) → `DOC-SY-APG-2026-Q1-IR`.

## 운영 전 남은 스키마 확인

- CONNECT 설계의 실제 그래프 노드·관계 라벨과 이 매핑의 일치 여부 확인.
- 팀 공용으로 사용할 Neo4j 인스턴스 주소·인증 방식이 로컬 설정과 같은지 확인. 비밀값은 JSONL이나 문서에 저장하지 않는다.
- 회사 공통 노드의 키·제약조건, 재실행 시 중복 방지 방식, 출처 문서의 허용 저장 범위를 팀 기준과 맞춘다.
- OpenAI 추출 후보는 팀의 관계 스키마와 사람 검토를 마친 뒤 필요한 것만 반영한다. 현재 후보 관계는 별도 파일에 보존하고 Neo4j에는 적재하지 않았다.
