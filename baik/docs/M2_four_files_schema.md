# M2 온톨로지 스키마 설계: 7개 기업 자료

상태: 팀 검토용 초안 v0.1 · 2026-11-06  
범위: `companies.jsonl`(7건), `company_info.jsonl`(7건), `financials.jsonl`(7건), `news(1).jsonl`(4,580건). 기사 전체의 사실·관련성이나 자동 추출 결과를 검증한 최종 스키마가 아니다.

## 1. 목적과 적용 원칙

7개 기업의 기본정보, 재무 실적, 사업·제품·협업·사회 이슈 등을 출처와 시점을 유지하며 연결한다. 먼저 “어떤 기업의 어떤 활동·관계가 어떤 근거에 나타나는가?”와 “특정 기업의 연도별 재무 지표는 무엇인가?”를 물을 수 있도록 설계한다. 질문과 세부 범위는 팀 합의가 필요하다.

기업·재무 파일은 이미 구조화된 조사 기록이므로 필드별 검증 후 매핑한다. 뉴스는 중복 확인·가치 선별·청크화 후 M4에서 추출한다. 원본 및 제외 사유는 보존한다. 기사 내용은 **출처가 보고한 주장**이며, 기사에 적혀 있다는 것만으로 객관적 사실로 확정하지 않는다.

기존 M2의 10개 추출 유형과 9개 관계를 출발점으로 하되, 아래 확장은 이번 수동 사례를 반영한 제안이다. M3 프롬프트와 M4 검증기에는 아직 자동 반영되지 않았다. **아래 전체 표를 현재 M4가 그대로 허용한다고 보면 안 된다.**

## 2. 개체 유형과 속성

| 유형 | 의미 | 주요 속성 후보 | 식별·관리 기준 |
|---|---|---|---|
| `Company` | 독립 법인 | `id`, `name`, `legal_name`, `dart_corp_code`, `established_date`, `industry`, `listing_status` | 프로젝트 `company_id`를 후보로 보존; DART 코드와 실제 법인 확인 |
| `CorporateGroup` | 기업집단 | `id`, `name` | 지주회사·법인과 구별 |
| `Brand` | 상품·서비스 브랜드 | `id`, `name`, `aliases` | 같은 이름의 법인과 분리. 이니스프리·에스쁘아는 문맥에 따라 법인 또는 브랜드 |
| `Product` | 특정 상품 | `id`, `name`, `market`, `variant` | 국가별 제품, 표시 SPF가 다른 제품 등은 동일 제품으로 섣불리 통합하지 않음 |
| `Person` | 인물 | `id`, `name` | 동명이인 확인, 이름만으로 병합 금지 |
| `Organization` | 기업 외 기관·단체 | `id`, `name`, `organization_type` | 기관·언론·정부 등, 법인과 혼동 방지 |
| `Event` | 협업·시험·투자·출시·행사 등 사건 | `id`, `name`, `event_type`, `start_date`, `end_date`, `status` | 보고일과 발생일 구분; 행사별 ID 별도 관리 |
| `Market` | 범위가 정해진 시장 | `id`, `name`, `industry`, `scope` | 국가·상품·기간 맥락 유지 |
| `Place` | 국가·지역·장소 | `id`, `name`, `place_type` | 주소·지역이 같은 대상을 가리키는지 확인 |
| `MetricObservation` | 특정 대상·기간·시험 조건에 대한 관측 | `id`, `metric_name`, `value_number`, `unit`, `period_start`, `period_end`, `statement_scope`, `is_forecast` | 지표의 대상·단위·기간·기준·시험 조건을 함께 보존 |
| `Regulation` | 정책·규제·법령 | `id`, `name`, `jurisdiction`, `effective_date` | 일반적 규제 언급과 실제 법령을 구분. 신규 제안 |
| `Character` | 캐릭터 | `id`, `name` | 사람·기업으로 자동 분류하지 않음. 신규 제안 |
| `Document` | 기사·공시·구조화 기록 등 출처 | `id`, `title`, `url`, `source_type`, `published_at`, `collected_at`, `content_status` | 기사 ID와 수집 출처 보존; 동일 기사 다른 수집본은 별도 기록 |
| `Chunk` | 문서 안의 추출 구간 | `id`, `document_id`, `text`, `source_location`, `version` | 전처리 이후 생성. 원문 위치·텍스트 버전 보존 |
| `Assertion` | 출처에 근거한 한 주장 | `id`, `predicate`, `status`, `event_date`, `as_of_date`, `valid_from`, `valid_to`, `review_status` | 동일 사실이라도 출처별로 별도 관리. 근거와 상태 필수 |

속성은 존재할 때만 기록하고 모르면 `null` 또는 속성 미설정으로 둔다. `employee_count`는 현재 출처가 불충분하고 국민연금 사업장 가입자 수일 가능성이 있어 확인 전 기업 전체 직원 수로 확정하지 않는다. 텍스트 요약의 출처 목록은 개별 문장의 증거가 되는지 따로 확인한다.

## 3. 관계 유형·방향·연결 규칙

화살표의 왼쪽이 주어(S), 오른쪽이 목적어(O)다. `→` 방향을 지켜야 하며 표에 없는 연결은 자동 생성하지 않는다.

| 관계 | 출발 유형 | 도착 유형 | 의미·조건 | 상태 |
|---|---|---|---|---|
| `HOLDS_POSITION` | Person | Company, Organization | 인물→소속 기관. `position`·시점 기록 | 기존 |
| `OWNS_STAKE` | Company, Person | Company | 소유자→대상. 지분율·기준일·예정 여부 보존 | 기존 |
| `PART_OF_GROUP` | Company | CorporateGroup | 법인→기업집단, 소속 근거와 시점 필요 | 기존 |
| `OPERATES_BRAND` | Company | Brand | 기업→브랜드 운영 주체. 동일 이름만으로 생성 금지 | 기존 |
| `PRODUCT_UNDER_BRAND` | Product | Brand | 제품→브랜드 | 기존 |
| `PARTICIPATES_IN` | Company, CorporateGroup, Brand, Person, Organization | Event | 참여자→사건. `role`로 시험 수행·행사 운영 등 구분 | 기존 |
| `REPORTS_METRIC` | Company, CorporateGroup, Brand, Market, Product | MetricObservation | 측정 대상→지표. 이름은 대상이 직접 공시했다는 뜻이 아님 | 기존 |
| `MARKET_IN_PLACE` | Market | Place | 시장→지역 | 기존 |
| `EVENT_IN_PLACE` | Event | Place | 사건→장소 | 기존 |
| `PRODUCT_FEATURED_IN` | Product | Event | 제품→출시·판매·팝업 행사. 기사에서 명시된 역할만 | 신규 제안 |
| `EVENT_FEATURES` | Event | Character | 협업 사건→등장 캐릭터. 권리자·계약 관계를 추정하지 않음 | 신규 제안 |
| `REGULATES` | Regulation | Product, Market | 규제→대상. 일반 국가 규제를 특정 제품 위반으로 해석 금지 | 신규 제안 |

### 출처와 주장을 위한 연결

| 관계 | 출발 → 도착 | 규칙 |
|---|---|---|
| `HAS_CHUNK` | Document → Chunk | M1에서 생성한 문서·청크 참조 |
| `SUBJECT` | Assertion → 위 표의 출발 개체 | 주장마다 주어 1개 |
| `OBJECT` | Assertion → 위 표의 도착 개체 | 주장마다 목적어 1개 |
| `EVIDENCED_BY` | Assertion → Chunk | 근거 문구 `quote`와 문서·청크 ID 기록. 여러 근거 가능 |
| `SUPPORTED_BY_RECORD` | Assertion → Document | 구조화 레코드 근거. 레코드를 기사 원문으로 위장하지 않음 |

S-P-O 직접 관계는 검토된 Assertion으로부터 조회용으로 만들 수 있다. 직접 관계만 남기면 서로 다른 출처·시점의 주장과 상충 관계가 사라질 수 있으므로 Assertion과 연결 근거를 보존한다. 실제 Cypher 구현과 중복 키 정책은 M6에서 검증한다.

## 4. 파일별 매핑 및 제약

| 파일 | 입력 | 스키마 후보 | 추가 확인 |
|---|---|---|---|
| `companies.jsonl` | `company_id`, `legal_name`, `dart_corp_code` | Company ID·법인명·코드 | 기업 코드 실제 대상, 동일 법인과 브랜드 구분 |
| `company_info.jsonl` | 업종·사업 설명·상장·직원·설립일·`field_sources` | Company 속성 또는 출처가 있는 Assertion | 업종·직원 필드별 출처 미기재; 가입자 수와 직원 수 혼동 금지. 시간 따라 바뀌는 값은 근거·기준일 보존 |
| `financials.jsonl` | `financial_id`, `company_id`, `fiscal_year`, `period`, `statement_scope`, `revenue_krw`, `operating_profit_krw`, `source` | 회사 1개→매출 관측 1개 및 영업이익 관측 1개. 단위 KRW, 연도와 개별 범위 보존 | 7개 재무 레코드→14개 지표 후보. 원문 수치·단위·기간 검증 후 매핑 |
| `news(1).jsonl` | `document_id`, `title`, `original_url`, `published_at`, `content`, `company_ids` | Document→Chunk→Assertion, 각 Assertion→S/O | `content`를 M4의 `text`로 변환하고 chunk_id·위치·검토 상태 추가. company_ids는 관련 후보이지 관계의 증거가 아님 |

`financial_id`와 지표 종류를 조합해 두 관측의 안정적인 ID를 정하는 것을 제안한다. 자료를 업데이트할 때 같은 ID의 값이 바뀌면 무조건 덮어쓰지 않고 버전과 출처를 구분한다. 구체적인 ID와 중복 정책은 팀 합의 필요.

## 5. 수동 사례 적용과 보완

다음은 실제 API 추출이 아닌 기사·구조화 입력에 대한 수동 설계 사례다. 수집된 본문과 실제 웹 원문의 일치·사실성은 별도 검토한다.

### 사례 A: 2025년 재무정보

`financials.jsonl`의 아모레퍼시픽 레코드는 `revenue_krw=2653725793231`, `operating_profit_krw=212514854678`, 사업연도 2025, `period=연간`, `statement_scope=개별`을 포함한다.

- `아모레퍼시픽:Company → REPORTS_METRIC → 2025 연간 개별 매출:MetricObservation`
- `아모레퍼시픽:Company → REPORTS_METRIC → 2025 연간 개별 영업이익:MetricObservation`

각 관측에 KRW·기간·범위·재무 레코드 및 공시 출처를 연결한다. 숫자 자체는 원문 대조 전 후보로 취급한다.

### 사례 B: 기사에 근거한 제품·브랜드

기존 수동 시험에서는 기사 문장 “에이피 뷰티(AP BEAUTY)가 … 신제품 ‘듀얼 리페어 리프트 M.D. 크림 미스트’를 출시”를 근거로 삼았다.

`듀얼 리페어 리프트 M.D. 크림 미스트:Product → PRODUCT_UNDER_BRAND → 에이피 뷰티(AP BEAUTY):Brand`

`NEWS-0fdd2f5d8f821b9a`의 해당 청크와 근거 문구를 Assertion에 연결한다. 웹 원문 전체 대조 및 팀 검토는 남아 있다. 브랜드와 법인의 운영 관계는 이 문장만으로 새로 확정하지 않는다.

### 사례 C: 11번가 판매 행사 관련 긴 기사

사용자가 제공한 기사에는 “이니스프리 ‘그린티 판테놀 카밍 토너 패드’, ‘그린티 세라마이드 클렌징 밤’, 에스쁘아 ‘매쉬드 블러 밤스틱’ 등 신제품도 할인 판매한다”는 구간이 있다.

- 각 제품 → `PRODUCT_UNDER_BRAND` → 해당 브랜드.
- 제품 → `PRODUCT_FEATURED_IN` → 월간 십일절 행사:Event (신규 제안).
- 이니스프리와 에스쁘아가 함께 등장한다는 이유로 두 법인 사이 협업을 생성하지 않는다.

긴 기사 전체가 아니라 이 구간과 앞뒤 행사 문맥을 보존해야 한다. 날짜 연도·상품별 할인율은 원문에 없으면 채우지 않는다.

### 사례 D: 선크림 비교 기사에 대한 보완 필요

사용자가 별도로 제공한 기사 본문에는 이니스프리 한국용·미국용 제품의 실측 SPF 48·16과 소비자단체 시험이 기술돼 있다. 그러나 이번 뉴스 JSONL에서 해당 ID `NEWS-22bf68611041445f`의 본문은 **다른 기사 링크 53자**뿐이다. 따라서 현재 JSONL 청크를 근거로 이 수치를 추출하면 안 된다. 원문 복구·출처 연결 후에만 제품별 `REPORTS_METRIC` 후보로 검토한다. SPF 표시값과 실측값, 시험기관·방법·시장·시점을 구분해야 하며 이 사례는 현 M2에 시험 방법·측정 출처를 표현할 추가 설계가 필요함을 보여준다.

## 6. 검증·보완 계획

1. 뉴스 중복과 본문 문제를 검사하고 관련성·가치 선별을 진행한다. 중복·후순위 원본은 삭제하지 않는다.
2. 기업 코드, 구조화 수치와 필드별 출처·기준일을 검증한다.
3. 뉴스 소수 표본으로 M4 실제 추출을 실시해 유형·연결의 누락과 오분류를 원문과 비교한다. 이번 수동 예시는 API 실행 결과가 아니다.
4. 새 관계와 신규 유형이 필요하면 M2·M3 프롬프트·M4 검증기·M5 정규화·M6 매핑을 같은 버전으로 함께 갱신한다.
5. 서로 다른 수집본, 상충 주장, 시점·출처, 동일명 법인과 브랜드, 분류 미결을 별도로 검토한다.

## 7. 이번 단계의 확인 결과와 미결 사항

본 문서에는 유형 정의, 속성 후보, 관계 방향과 허용 유형 조합이 있다. 기업·재무 직접 매핑과 뉴스 추출 경로를 구분했다. 그러나 유형명·관계명과 조회 질문의 팀 합의, M4 실제 모델 실행에 따른 스키마 보완, 신규 관계의 코드 구현, 출처 원문 대조 및 M6 적재 검증은 남아 있다. 사용자가 기존 AuraDB 데이터를 삭제했으며 이 문서 작성에서 데이터베이스를 변경하지 않았다.
