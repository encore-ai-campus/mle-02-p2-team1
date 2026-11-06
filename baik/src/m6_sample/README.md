# M6 AuraDB 적재: 직접 관계에 출처 저장

M5 소량 사례(뉴스 5청크 및 구조화 기업·재무 후보)를 입력으로 한다. 기존 주장 노드나 SUBJECT/OBJECT 관계를 만들지 않는다. 회사 등 개체 24개와 직접 관계 17개를 생성하며, 19개 출처별 기록을 각 관계의 `sources_json` JSON 문자열에 보관한다. 이 파일은 전체 뉴스 4,580건을 적재하지 않는다.

## 준비
압축을 풀고 기존 uv 프로젝트 환경에서 PowerShell을 연다. `neo4j`, `python-dotenv`가 없을 때만 프로젝트에서 `uv add neo4j python-dotenv`를 실행한다. `.env`의 `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`를 설정한다. `NEO4J_DATABASE`가 없으면 `neo4j`를 사용한다. 비밀번호는 Git이나 대화에 공유하지 않는다.

```powershell
uv run .\load_m6.py --dry-run
```

DB에 연결하지 않으며 `개체 24, 관계 17, 출처별 근거 19`라고 출력되면 입력 검사가 통과한 것이다.

이전에 같은 PC에서 발생한 인증서 문제가 다시 발생한다면, 해당 PowerShell 창에서 아래를 먼저 실행한다.

```powershell
$env:SSL_CERT_FILE = (uv run --with certifi python -c "import certifi; print(certifi.where())")
```

## 실제 적재

AuraDB 주소·계정·DB가 본인의 팀 DB인지 확인한 뒤 실행한다. 실행 즉시 DB가 변경된다.

```powershell
uv run .\load_m6.py
```

예상 결과: `entities: 24`, `relations: 17`, `relations_with_sources: 17`. 노드 레이블은 `B_M6Entity` 및 `B_Company` 등이며 관계는 `B_REPORTS_METRIC`, `B_PARTICIPATES_IN` 등 `B_`를 사용한다. dataset_id는 `brian_m6_direct_20261106_v1`이다. 다른 팀원의 데이터와 식별하는 값이므로 같은 값을 다른 데이터에 사용하지 않는다.

유일성 제약 `b_m6_entity_uid_unique`를 생성하고, 입력의 고정 ID 및 MERGE를 사용해 같은 데이터를 다시 실행해도 중복이 생기지 않도록 설계했다. 동시 실행하지 않는다. 바뀐 입력은 이 동일 데이터셋에 재적재하지 않는다. 변경된 입력을 사용하면 프로그램이 기존 데이터와의 지문 불일치로 중지한다. DB에 기존 데이터가 없는 경우에는 변경된 입력도 적재될 수 있으므로 이 샘플만 사용한다. 제약 생성은 별도의 트랜잭션이므로 적재에 실패해도 남을 수 있다. DB 실제 실행 및 재적재는 아직 테스트하지 않았다.

```powershell
uv run .\load_m6.py --verify-only
```

위 명령은 읽기 전용으로 현재 개체·관계와 출처가 있는 관계 수를 출력한다. 실제 재적재 검증은 적재 명령을 다시 실행한 후 동일 수치가 유지되는지 확인해야 한다.

## 그래프 확인

```cypher
MATCH (n:B_M6Entity {dataset_id:'brian_m6_direct_20261106_v1'})
OPTIONAL MATCH (n)-[r]->(m:B_M6Entity {dataset_id:'brian_m6_direct_20261106_v1'})
WHERE r.dataset_id='brian_m6_direct_20261106_v1'
RETURN n,r,m
```

```cypher
MATCH (s:B_M6Entity)-[r]->(o:B_M6Entity)
WHERE r.dataset_id='brian_m6_direct_20261106_v1'
RETURN s.name AS 주어, type(r) AS 관계, o.name AS 목적어,
       r.source_count AS 출처수, r.sources_json AS 출처와근거
```

`sources_json`은 JSON 문자열이므로 기사별 URL, 문서 ID, 청크 ID, 인용문·속성·검토 상태를 원본 객체로 보존한다. 재무 관계에는 원본 financial_id와 source_field 및 공시 출처가 포함된다. 두 기사가 뒷받침하는 관계는 `source_count=2`이고 관계는 1개다. 기존 키의 수치·상태·시점이 다른 경우는 무조건 같은 관계로 합치지 않고 별도 관계로 둔다. 조건이 달라진 주장을 동일 관계로 강제 병합하지 않기 위해서다.

## 한계
입력 출처는 자동으로 진위를 판정하지 않았다. 개체와 재무자료는 원문·단위·기준일 검토 필요, 직원수는 국민연금 가입자수일 수 있다. 문서·청크 원문 전체는 별도 노드로 저장하지 않으며 근거 문구와 출처 정보를 관계 속성에 저장한다. 이후 새 M4 추출 데이터는 M5 검토와 매핑을 거쳐야 하며 이 샘플 코드가 전체 자료에 안전하게 적용된다고 보장하지 않는다.
