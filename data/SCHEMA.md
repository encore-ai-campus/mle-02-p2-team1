# CONNECT 데이터 수집·전처리 파일 기준

이 파일 구조와 필드명은 [CONNECT 개발 설계 문서의 수집 파일 목록](https://connect-architecture-docs.dkssk136136.chatgpt.site/#collection-files), [공통 기업 목록](https://connect-architecture-docs.dkssk136136.chatgpt.site/#common-companies), [파일별 스키마](https://connect-architecture-docs.dkssk136136.chatgpt.site/#jsonl-field-tables), [데이터 구조도](https://connect-architecture-docs.dkssk136136.chatgpt.site/#data-structure), [공시 데이터 수집 링크](https://connect-architecture-docs.dkssk136136.chatgpt.site/#disclosure-links)을 따릅니다.

## 폴더 구조

```text
data/
├── shared/
│   ├── companies.jsonl           팀 공통 7개 기업 목록
│   └── company_relations.jsonl   팀 공통 기업집단·기업 관계
├── raw/                          허용된 원문·API 응답·공시 ZIP
└── collected/
    ├── suyeon/                   documents + 이니스프리·에스쁘아 조사 파일 6개
    ├── anna/                     안나 담당 문서·조사 파일 6개
    └── seonghyeon/               성현 담당 문서·조사 파일 6개
```

모든 파일은 UTF-8 JSON Lines입니다. 한 줄에 JSON 객체 하나를 씁니다. 문서 ID는 담당자 접두어를 넣어 팀 내에서 고유하게 하고, 영역별 조사 기록과 공통 관계는 `company_id`와 `document_id`로 공통 기업 목록 및 담당자별 문서 목록을 참조합니다.

날짜는 확인된 경우 `YYYY-MM-DD`, 시각은 ISO 8601 시간대 포함 형식으로 씁니다. 스키마에서 `확인 시`인 필드도 키는 유지하고 확인되지 않으면 JSON `null`을 넣습니다. 발췌문이나 본문은 저장·이용이 허용된 경우에만 넣습니다. 기사·공시 전체를 영역별 조사 파일에 복사하지 않습니다.

## `shared/companies.jsonl`

팀 공통 기업 한 곳당 한 레코드. 현재 CONNECT 설계표에 있는 일곱 기업을 사용합니다. 주요 필드는 `company_id`, `input_name`, `legal_name`, `corp_code`, `assignee`, `source_name`, `source_url`, `verified_at`입니다. 내부 `company_id`는 DART 고유번호와 별개이며 아래 값을 그대로 씁니다.

- `COMPANY-INNISFREE`, `COMPANY-ESPOIR`
- `COMPANY-AMOREPACIFIC`, `COMPANY-ETUDE`
- `COMPANY-PACIFICTECH`, `COMPANY-AMOSPROFESSIONAL`, `COMPANY-COSRX`

## `documents.jsonl`

자료 한 건당 한 레코드. 필수 필드: `document_id`, `source_type`, `source_name`, `collected_at`, `company_ids`, `processing_status`. 추가 필드: `title`, `original_url`, `published_at`, `raw_path`, `clean_text`.

- `source_type`: `news` | `disclosure` | `company_material` | `public_data`
- `company_ids`: 공통 기업 목록의 내부 ID 배열. 불확실하면 `[]`
- `processing_status`: `수집 완료` | `정제 완료` | `확인 필요` | `실패`
- `raw_path`: 허용된 원문/API 응답의 프로젝트 상대 경로. 없으면 `null`
- `clean_text`: 이용이 허용된 정제 본문만 저장. 저장할 수 없거나 미수집이면 `null`
- Open DART 키를 포함한 요청 URL이나 인증정보는 저장하지 않습니다.

## 6개 담당자별 조사 파일의 공통 필드

`company_info.jsonl`, `social_issues.jsonl`, `politics.jsonl`, `market.jsonl`, `strategies.jsonl`, `owners.jsonl`은 아래 공통 필드를 모두 포함합니다.

`record_id`, `company_id`, `document_id`, `domain`, `content`, `evidence_text`, `evidence_location`, `as_of_date`, `verification_status`

- `domain`: 파일에 따라 `company_info`, `social_issue`, `politics`, `market`, `strategy`, `owner`
- `evidence_text`, `evidence_location`, `as_of_date`: 근거를 확인할 때 입력하고 없으면 `null`
- `verification_status`: `확인 필요` | `확인됨` | `상충`
- `content`에는 문서에서 확인한 핵심 사실만 씁니다. 의혹·보도·회사 입장·확정된 사실을 구분합니다.

### `company_info.jsonl` 추가 필드

`industry`, `main_business`, `revenue_krw`, `operating_profit_krw`, `listing_status`, `employee_count`, `established_date`, `fiscal_year`, `period`, `statement_scope`.

매출액·영업이익은 원 단위 정수이며 영업손실은 음수입니다. 한 줄은 기업 한 곳·근거 문서 한 건·같은 재무 기간입니다. `period`: `연간` | `1분기` | `2분기` | `반기` | `3분기`; 분기 실적 발표의 독립 분기값은 해당 분기(예: `2분기`)로, 누적 반기값은 `반기`로 구분합니다. `statement_scope`: `연결` | `별도` | `개별`. 확인되지 않은 숫자·분류는 `null`로 둡니다.

### `social_issues.jsonl` 추가 필드

`issue_type`, `event_date`, `relation_scope`, `company_role`, `event_status`.

- `issue_type`: `제품` | `노동` | `환경` | `소송` | `소비자` | `사회공헌` | `기타`
- `relation_scope`: `직접` | `간접` | `확인 필요`

### `politics.jsonl` 추가 필드

`activity_type`, `actor_name`, `organization_name`, `activity_date`, `relation_scope`.

- `activity_type`: `공식 발언` | `정책 참여` | `공공 협력` | `기부·후원` | `기타`
- `relation_scope`: `직접` | `간접` | `확인 필요`

확인된 공개 활동 한 건씩 기록합니다. 확인되지 않은 활동을 만들거나, 검색 범위 안에서 결과가 없었다는 사실을 활동 레코드로 넣지 않습니다.

### `market.jsonl` 추가 필드

`market_type`, `industry`, `market_scope`, `geography`, `period`, `metric`, `value`, `unit`, `relevance_type`.

- `market_type`: `시장 규모` | `시장 성장률` | `소비자 수요` | `경쟁 환경` | `산업 동향` | `규제 환경` | `기타`
- `relevance_type`: `시장 일반` | `기업 직접` | `확인 필요`
- `value`는 수치일 때 숫자형, 확인되지 않으면 `null`. 산업 전체 지표를 개별 기업 실적으로 표시하지 않습니다.

### `strategies.jsonl` 추가 필드

`strategy_type`, `announced_at`, `target_period`, `stage`.

- `strategy_type`: `사업 확장` | `해외 진출` | `제품 개발` | `디지털 전환` | `지속가능경영` | `인수·투자` | `기타` 또는 `null`
- `stage`: `계획` | `진행` | `완료` | `확인 필요`

### `owners.jsonl` 추가 필드

`person_name`, `role_type`, `position`, `ownership_percent`, `start_date`, `end_date`.

- `role_type`: `대표` | `임원` | `주주` | `오너` | `기타`
- `ownership_percent`: 0~100 숫자, 지분이 아닌 인물 관계는 `null`

## `shared/company_relations.jsonl`

공통 조사 필드와 `related_company_id`, `group_name`, `relation_type`, `ownership_percent`를 포함합니다. `relation_type`: `집단 소속` | `지분 보유` | `종속회사` | `기타`. 대상이 조사 기업이면 `related_company_id`, 기업집단이면 확인된 `group_name`을 씁니다. 집단 소속만으로 직접 지분·종속 관계를 추정하지 않습니다.

## 연결·수집 기준

1. 공식 법인명과 Open DART 고유번호를 확인합니다. 내부 `company_id`는 `shared/companies.jsonl` 값을 사용합니다.
2. 수집한 문서를 `documents.jsonl`에 먼저 등록하고 고유 `document_id`를 부여합니다.
3. 그 문서에서 확인한 주제별 사실을 해당 영역 JSONL에 기록하고 동일한 `document_id`를 연결합니다.
4. 공통 관계도 담당자 문서 목록을 먼저 참조한 후 `shared/company_relations.jsonl`에 기록합니다.
5. 본문 정제, 중복 점검, 실제 원문과의 표본 대조를 완료 상태에 반영합니다.

공식 수집 안내: [DART 전자공시](https://dart.fss.or.kr/), [Open DART API](https://opendart.fss.or.kr/), [Open DART API 가이드](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001), [금융위원회 기업기본정보 API](https://www.data.go.kr/data/15043184/openapi.do), [공정거래위원회 기업집단 소속회사 API](https://www.data.go.kr/data/15091891/openapi.do). 인증키는 `.env`에서만 관리합니다.
