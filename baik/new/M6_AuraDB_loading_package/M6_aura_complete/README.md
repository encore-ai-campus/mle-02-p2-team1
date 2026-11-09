# M6 스키마 매핑·AuraDB 적재 안내

> M5에서 선택한 결과를 직접 관계로 매핑하고, 사용자가 자신의 PC에서 Neo4j AuraDB에 적재·확인하기 위한 코드다. **이 패키지를 만들면서 실제 AuraDB에 접속하거나 적재하지 않았다.**

## 1. 무엇을 적재하나?

| 입력 | M5 기록 | 매핑 결과 |
| --- | ---: | --- |
| 뉴스 관계 | 17,698건 | 같은 주어·서술어·목적어와 모든 관계 속성이 같은 기록은 하나의 관계로 묶음 |
| 재무·공시 관계 | 28건 | 뉴스와 함께 같은 규칙으로 처리. 공시 주석 원문 보존 |
| **전체 관계 근거 기록** | **17,726건** | 관계 속성에 출처별 원본 기록으로 모두 보존 |
| **노드 후보** | **12,247개** | M2의 개체 유형과 방향을 검사한 뒤 매핑 |
| **직접 관계 후보** | **13,322개** | 위 관계 기록들을 묶은 결과. 실제 DB 적재 전 예상치 |

전체 뉴스 관계 중 제외한 2,572건은 이 입력에 포함되어 있지 않다. M4에서 대기·실패한 뉴스 청크도 포함하지 않는다. 개체의 잠정 연결 상태와 검토가 필요한 출처는 그대로 보존되므로, 결과를 확정 사실로 해석하지 않는다.

두 기사에서 같은 관계를 말하더라도 기준일·상태·수치 등 **관계 속성 전체가 일치할 때만** 하나로 묶는다. 일치하지 않는 관계는 별도로 만든다. 관계의 `sources_json`에는 각 원본 관계 기록이 JSON 문자열로 남고, `source_count`는 그 기록의 수다. URL의 고유 개수가 아니다. 별도의 주장 노드는 만들지 않는다.

```
아모레퍼시픽 ── 참여한다 ──▶ 행사
                   ├─ 출처 기록 A와 근거
                   └─ 출처 기록 B와 근거
```

공시 지분 관계는 기준일과 지분율을 관계에 보존하고, 참조된 공시 주석은 `disclosure_notes_json`에도 보존한다. 일부 지표는 수치·단위가 누락되었거나 여러 대상에 연결되어 있어 원문 검토가 필요하다.

## 2. 다른 팀원 데이터와 어떻게 구분하나?

이 코드는 레이블과 관계 유형에 **`B_`**를 사용한다.

- 개체 레이블 예: `B_Company`, `B_Person`, `B_Product`, `B_MetricObservation`
- 공통 레이블: `B_M6Entity`
- 관계 유형 예: `B_OWNS_STAKE`, `B_HOLDS_POSITION`, `B_PARTICIPATES_IN`
- 기본 데이터셋 식별자: `brian_m6_20261108_v1`

같은 이름의 다른 팀원 노드를 찾아 합치거나 삭제하지 않는다. 노드는 `dataset_id`와 개체 ID를 결합한 `uid`로 구분한다. 이 실행과 별도로 다른 작업에서 같은 `B_M6Entity`와 같은 dataset-id·uid를 사용하고 있다면 충돌할 수 있으니 다른 `--dataset-id`를 지정한다. **같은 데이터셋을 여러 프로세스에서 동시에 실행하지 않는다.**

## 3. 파일 구성

| 파일 | 역할 |
| --- | --- |
| `load_m6.py` | 입력 검증, AuraDB 연결, 노드·관계 적재, 결과 확인 |
| `mapper.py` | M5 자료를 M2의 노드·관계 형식으로 변환 |
| `M5_remaining_quick_result.zip` | 이번에 사용할 최종 M5 데이터. 별도로 풀지 않아도 됨 |
| `test_mapper.py`, `test_loader.py` | 데이터 변환과 재실행 로직의 자동 검사 |
| `README.md` | 현재 안내 문서 |

M5 입력 ZIP에는 기사 인용과 URL이 들어 있다. 저장소 공개 범위와 원문 공유 가능 범위에 맞춰 관리한다. `.env`와 인증정보는 이 패키지에 포함하지 않는다.

## 4. 시작 전 준비

1. 이 패키지를 압축 해제한다.
2. 기존 프로젝트의 `.env`에 다음 값을 설정한다. 실제 비밀번호는 아래 예시의 값을 대체한다.

```dotenv
NEO4J_URI=neo4j+s://여기에-Aura-연결-주소
NEO4J_USERNAME=여기에-사용자명
NEO4J_PASSWORD=여기에-비밀번호
# NEO4J_DATABASE=별도로 지정한 데이터베이스 이름
```

`NEO4J_DATABASE`를 비워 두면 드라이버가 해당 사용자의 기본 데이터베이스를 사용한다. 프로젝트 상위 폴더의 `.env`를 사용한다면 프로그램이 해당 파일을 찾을 수 있는 위치에서 실행한다. `.env`는 GitHub에 올리지 않는다.

3. 프로젝트 환경에 Python의 `neo4j`, `python-dotenv`가 설치되어 있어야 한다. 이미 설치되어 있으면 다시 설치할 필요가 없다. 프로젝트에 아직 없다면 다음을 한 번 실행한다.

```powershell
uv add neo4j python-dotenv
```

기존에 `SSL_CERT_FILE` 설정으로 인증서 오류를 해결했다면, **새 PowerShell 창에서는 필요할 경우 다시 설정**한다. 이미 해당 창에서 설정했고 인증서 파일이 존재한다면 반복할 필요가 없다. 연결이 바로 되는 환경에서는 설정하지 않아도 된다.

```powershell
$env:SSL_CERT_FILE = (uv run --with certifi python -c "import certifi; print(certifi.where())")
```

## 5. 실행 순서

압축 해제한 폴더에서 PowerShell을 연다. 먼저 DB에 접속하지 않고 매핑과 입력을 확인한다.

```powershell
uv run .\load_m6.py --dry-run
```

정상이라면 노드 **12,247개**, 직접 관계 **13,322개**, 관계 근거 기록 **17,726건**이 출력된다. 이는 **예상 결과**이고, AuraDB에 저장된 결과가 아니다.

`.env`를 준비하고 적재할 DB와 데이터셋을 확인한 뒤 실행한다.

```powershell
uv run .\load_m6.py
```

1. AuraDB 연결과 기존 데이터셋의 입력 지문을 확인한다.
2. `B_M6Entity.uid`에 대한 유일성 제약을 준비한다.
3. 노드와 관계를 기본 **500건씩 나누어** 적재한다.
4. DB에서 노드·관계를 다시 읽고 ID, 유형, 방향, 속성과 출처 기록을 입력과 비교한다.
5. 모든 검증이 통과하면 `적재 결과 검증 성공`을 출력한다.

DB에 변경을 하지 않고 나중에 적재 상태만 다시 확인하려면:

```powershell
uv run .\load_m6.py --verify-only
```

### 중단과 재실행

각 묶음은 별도 트랜잭션으로 저장되므로 중간에 오류가 나거나 `Ctrl+C`로 멈추면 **이미 끝난 묶음은 DB에 남을 수 있다.** 같은 입력·코드 결과와 같은 `dataset_id`로 다시 실행하면 `MERGE`와 결정적인 ID를 이용해 같은 노드·관계를 다시 만든다. 성공한 묶음을 지울 필요는 없다. 노드 유일성 제약도 남을 수 있다.

같은 `dataset_id`의 기존 데이터가 다른 입력 지문을 가지면 혼합을 막기 위해 중단한다. **동일 입력 재실행의 실제 중복 여부와 출처 유지는 AuraDB에서 재실행 후 확인해야 한다.** 가상 저장소 테스트 통과는 실제 AuraDB 재적재 시험을 대체하지 않는다.

다른 데이터셋으로 구분하려면 예시처럼 지정한다. 이 옵션은 다른 이름의 별도 데이터를 새로 적재하므로, 이미 적재된 기존 데이터셋을 업데이트하는 뜻은 아니다.

```powershell
uv run .\load_m6.py --dataset-id brian_m6_other_v1
```

묶음 크기를 조절할 때:

```powershell
uv run .\load_m6.py --batch-size 200
```

## 6. AuraDB에서 확인할 Cypher

아래 쿼리는 기본 `dataset_id` 기준이다. `--dataset-id`를 바꿨다면 같은 값으로 바꾼다. 다른 팀원의 데이터는 조회 대상에서 제외한다.

**노드 수**

```cypher
MATCH (n:B_M6Entity {dataset_id: 'brian_m6_20261108_v1'})
RETURN count(n) AS node_count;
```

**관계와 근거 기록 수**

```cypher
MATCH (:B_M6Entity {dataset_id: 'brian_m6_20261108_v1'})-[r]->
      (:B_M6Entity {dataset_id: 'brian_m6_20261108_v1'})
WHERE r.dataset_id = 'brian_m6_20261108_v1'
RETURN count(r) AS relationship_count,
       sum(r.source_count) AS source_record_count;
```

**예시 지분 관계와 근거**

```cypher
MATCH (holder:B_Company {dataset_id: 'brian_m6_20261108_v1'})
      -[r:B_OWNS_STAKE]->
      (company:B_Company {dataset_id: 'brian_m6_20261108_v1'})
WHERE r.dataset_id = 'brian_m6_20261108_v1'
RETURN holder.name AS 투자회사, company.name AS 대상회사,
       r.as_of_date AS 기준일, r.value_number AS 지분율,
       r.source_count AS 근거기록수, r.sources_json AS 근거,
       r.disclosure_notes_json AS 공시주석
LIMIT 20;
```

상위 20건은 확인용 예시다. 날짜나 지분율이 없는 항목은 빈 값일 수 있으며, 모든 지분 관계가 공시에서 온 것은 아니다.

**관계 유형별 건수**

```cypher
MATCH (:B_M6Entity {dataset_id: 'brian_m6_20261108_v1'})-[r]->
      (:B_M6Entity {dataset_id: 'brian_m6_20261108_v1'})
WHERE r.dataset_id = 'brian_m6_20261108_v1'
RETURN type(r) AS relation_type, count(*) AS count
ORDER BY count DESC;
```

## 7. 확인한 것과 아직 확인하지 못한 것

- [x] 실제 M5 입력으로 DB 접속 없이 전체 매핑: 12,247개 노드, 13,322개 직접 관계, 17,726건 근거 기록.
- [x] 유형·방향, 출처 및 공시 주석 보존, 날짜별 관계 분리 등을 파이썬 테스트로 확인.
- [x] DB를 흉내 낸 가상 저장소에서 같은 전체 결과를 두 번 넣고 수와 출처가 유지되는지 확인.
- [ ] 실제 AuraDB 연결과 전체 적재.
- [ ] 실제 AuraDB에서 같은 입력 재적재 후 중복 여부 및 출처 유지 확인.
- [ ] Cypher 조회와 원문 대조, 핵심 질문별 답변 검증.

따라서 현재 상태는 **M6 코드·매핑 준비 및 로컬 검증 완료, 실제 적재와 재적재 확인 대기**다. 가상 저장소는 실제 Neo4j 엔진이 아니므로 Cypher 실행과 AuraDB 권한·용량·네트워크 조건을 검증하지 못한다.
