# M4 진행·중단 보고서

> **특정 산업 분야의 기업 조사 업무를 지원하는 지식그래프 구축**  
> 시범 사례: 아모레퍼시픽 관련 7개 기업

| 항목 | 내용 |
| --- | --- |
| 단계 | M4 · 자동 추출 파이프라인 |
| 상태 | **뉴스 추출 진행 중 중단 · 공시 표 기반 추출 결과 확보** |
| 작성일 | 2026-11-07 |
| 뉴스 실행 기록 | 2026-11-06 제공 결과 스냅샷 기준 |
| 다음 단계 | 재사용할 뉴스·공시 결과를 M5에서 정규화하고 적재 후보로 정리 |

## 1. 단계 결과 한눈에 보기

- **뉴스 추출:** 4,580개 기사를 6,878개 청크로 나눠 LLM으로 추출. 마지막으로 확인한 상태는 성공 4,757개, 실패 13개, 대기 2,108개.
- **중단 사유:** 실행 중 `RateLimitError`가 기록됐고, API 오류 화면에서 `429 - Project spend limit reached`를 확인.
- **뉴스 성공 결과:** 개체 언급 29,245건과 관계 추출 20,270건. 중복 정규화와 사실 검증 전의 추출 건수.
- **공시 추출:** 기존에 확보한 공시 보고서 2건에서 규칙 기반 코드로 지분 관계를 추출. 7개 관계를 두 기준일로 관측한 총 14건의 결과 확보.
- **현재 판단:** 뉴스 전체를 추출하지 못했으므로 M4를 전체 완료로 표시하지 않음. 성공한 뉴스 결과와 공시 결과는 M5 작업에 활용 가능.

> 수치와 상태는 제공받은 결과 스냅샷 기준이다. 사용자의 컴퓨터에서 이후에 진행한 작업은 실시간으로 반영되지 않는다.

## 2. M4의 목적과 처리 자료

M4는 문서에서 개체와 관계를 추출하고, 결과가 지정된 형식과 원문 근거 규칙에 맞는지 검사하여 저장하는 단계다. 이번 기록에는 서로 다른 두 작업이 있다.

| 작업 | 입력 | 처리 방식 | 출처 |
| --- | --- | --- | --- |
| **뉴스 추출** | 4개 JSONL 중 뉴스 본문. 기업 식별·기본정보·재무정보 파일도 구조화 입력으로 사용 | 뉴스 청크를 LLM API에 전달하고 JSON 결과 검사·저장 | 2026-11-06 진행한 병렬 M4 실행 |
| **공시 표 추출** | 기존에 확보한 홀딩스 보고서 2건의 지분 표와 주석 | 별도 파이썬 코드로 HTML 표를 읽어 규칙 기반 추출 | 이후 별도로 처리한 공시 작업 결과 |

공시 보고서는 새로 수집해 아직 처리하지 않은 자료가 아니다. **기존에 확보한 보고서 원문을 별도 코드로 처리한 결과**다. 보고서의 지분 기준일은 2025-12-31과 2026-03-31이며, 보고서 처리일과 다르다.

## 3. 뉴스 M4 자동 추출 작업

### 3.1 입력과 실행 흐름

| 입력 파일 | 내용 | 건수 |
| --- | --- | ---: |
| `companies.jsonl` | 기업 ID와 법인명 등 식별 정보 | 7건 |
| `company_info.jsonl` | 기업 기본정보와 출처 | 7건 |
| `financials.jsonl` | 2025년 재무정보와 출처 | 7건 |
| `news.jsonl` | 기사 본문과 기사별 문서 정보 | 4,580건 |

`news.jsonl`에는 **기사 4,580건이 한 행에 한 건씩** 들어 있다. 각 행의 기사 본문이 길면 여러 청크로 나누고, 짧으면 한 청크로 처리했다. 그 결과 4,580건이 총 **6,878개 청크**가 됐다.

각 청크에 문서 ID·청크 ID·기사 제목·발행일·출처 URL·본문 위치를 연결했다. 코드의 기본 청크 크기는 **최대 2,500자**이며, 가능한 경우 문단 경계를 이용한다.

이후 청크 본문을 LLM에 전달하고, 반환한 JSON에서 **개체·서술어·원문 근거**를 검사해 저장했다. 구조화된 회사와 재무 레코드는 별도로 변환해 저장했다. 구조화 입력의 수치도 원출처 검토 전의 후보로 취급한다.

> 입력 문서 → 청크 분할 → LLM 호출 → JSON 파싱·형식 검증 → 성공·실패 상태 저장

### 3.1.1 현재 뉴스 자료에서 2,500자는 어떤 크기인가?

2,500자는 LLM에 보내는 본문 청크의 **최대 문자 수**다. 토큰 수가 아니며, 가능한 경우 빈 줄에서 나누기 때문에 실제 청크는 2,500자보다 짧을 수 있다. 분할된 청크 사이에 겹치는 부분은 없다.

현재 뉴스 4,580건에 어제 M4 코드의 분할 방식을 적용해, 최대 크기만 바꿨을 때 생기는 청크 수를 비교했다.

| 최대 청크 크기 | 전체 청크 수 | 한 청크에 들어가는 기사 수 | 전체 기사 중 비율 |
| ---: | ---: | ---: | ---: |
| 1,600자 | 9,390개 | 2,345건 | 51.2% |
| 2,000자 | 7,971개 | 2,934건 | 64.1% |
| 2,400자 | 7,062개 | 3,360건 | 73.4% |
| **2,500자** | **6,878개** | **3,451건** | **75.3%** |
| 3,000자 | 6,222개 | 3,794건 | 82.8% |
| 4,000자 | 5,572개 | 4,054건 | 88.5% |

**2,500자에서는 전체 기사의 약 75%를 나누지 않고 한 청크로 처리할 수 있다.** 기사 안에 함께 나온 기업과 활동을 한 번에 전달할 수 있고, 이 자료에서는 2,000자보다 청크 수가 1,093개 적다. 이런 점을 고려하면 2,500자는 이번 작업에서 사용하기에 실용적인 출발점으로 볼 수 있다.

다만 이 표는 **청크 분할 결과만 비교한 것**이다. 각 크기로 LLM에 다시 추출해 누락·정확성·실제 비용·처리 시간을 비교한 실험은 아니므로, 2,500자가 가장 좋은 크기라고 확정할 수는 없다.

#### 설정 이유에 관한 확인과 추정

이전에 처리한 뉴스 전처리 작업에서 **2,400자를 목표로 사용한 기록**은 확인했다. 다만 이전 작업은 긴 문단을 나누지 않아 2,400자를 넘길 수 있었고, 이번 M4는 최대 2,500자를 적용하므로 두 분할 방식은 같지 않다. 이전 2,400자 설정을 참고해 2,500자를 정했다는 직접적인 기록은 찾지 못했다.

**추정:** 가능한 많은 기사를 한 청크에 담고 긴 기사만 나누려는 의도로, 이전 뉴스 전처리와 비슷한 수준인 2,500자를 선택했을 가능성이 있다. 실제 자료에서 약 75%의 기사를 한 청크로 처리할 수 있다는 결과는 이 추정과 부합한다. 하지만 **당시 선택한 이유로 확인된 사실은 아니다.**

### 3.2 사용한 코드

어제 작업한 병렬 실행 코드와 당시 프롬프트는 아래 파일에서 확인할 수 있다.

[어제 사용한 M4 코드와 프롬프트 ZIP](https://chatgpt.com/library?file_id=libfile_87a4d3d5d76c8191b0684860b98848b8&account_id=572db941-93e9-4f5f-a926-7a495084b755)

| 파일 | 역할 |
| --- | --- |
| `run_m4.py` | 4개 입력 파일을 읽고 뉴스 청크 분할·LLM 호출·결과 검증·저장 수행 |
| `system_prompt.txt` | 어제 뉴스 추출 때 사용한 프롬프트 |
| `README.md` | 설치와 소량 실행, 재실행 방법 설명 |

핵심적인 LLM 호출 부분은 다음과 같다. 이는 실제 코드의 **일부분**이다.

```python
# 입력 청크와 추출 지침을 모델에 전달하고 JSON 형식의 응답을 요청한다.
response = client.chat.completions.create(
    model=args.model,
    reasoning_effort=args.reasoning_effort,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ],
)

# 모델이 반환한 문자열을 JSON으로 바꾸고 형식과 원문 근거를 검사한다.
content = response.choices[0].message.content
result = validate(json.loads(content), did, cid, payload["primary_text"])
```

검증기는 허용된 개체 유형·서술어와 연결 방향, 필수 속성, `evidence.quote`의 원문 포함 여부 등을 검사한다. 이 검사를 통과했다고 해서 **관계의 해석과 사실성까지 모두 검증된 것은 아니다.**

### 3.3 중단 직전 확인된 결과

| 청크 상태 | 수 | 의미 |
| --- | ---: | --- |
| 성공 | **4,757** | JSON 추출 결과를 저장한 청크 |
| 실패 | **13** | 요청이나 결과 처리 과정에서 실패한 청크 |
| 대기 | **2,108** | 아직 추출하지 않은 청크 |
| 빈 입력 | **0** | 빈 입력으로 분류된 청크 없음 |
| **합계** | **6,878** | 전체 뉴스 청크 |

청크 수를 기준으로 하면 **전체 6,878개 중 4,757개, 약 69.2%**의 추출이 성공했다. 기사별로는 다음과 같다.

| 기사 상태 | 기사 수 | 의미 |
| --- | ---: | --- |
| 모든 청크의 추출 성공 | 3,221건 | 해당 기사의 모든 청크에서 결과 저장 |
| 일부 청크만 성공 | 3건 | 같은 기사의 나머지 청크는 아직 성공하지 않음 |
| 성공한 청크 없음 | 1,356건 | 해당 기사의 청크 중 성공 결과가 없음 |
| **합계** | **4,580건** | 전체 기사 |

따라서 최소 한 청크가 성공한 기사는 **3,224건**이며, 그중 모든 청크가 성공한 기사는 **3,221건(전체 기사의 약 70.3%)**이다. 긴 기사는 한 행이 여러 청크가 되기 때문에 기사 수와 청크 수를 구분해야 한다.

청크는 길이가 서로 달라 **청크 69.2%가 본문 글자 수의 정확히 69.2%를 뜻하지는 않는다.** 확인된 입력 본문은 총 11,217,056자이고, 성공 청크의 본문은 7,648,131자로 **글자 수 기준 약 68.2%**다. 성공 청크의 본문과 입력 기사에서 해당 위치의 내용이 일치하는지도 확인했다.

성공 결과를 합산하면 다음과 같다.

| 항목 | 추출 건수 | 해석 |
| --- | ---: | --- |
| 개체 언급 | 29,245건 | 기사별로 추출된 개체 건수. 같은 대상이 여러 번 포함될 수 있음 |
| 관계 | 20,270건 | 기사별로 추출된 관계 건수. 같은 관계가 여러 번 포함될 수 있음 |

위 건수는 **정규화가 끝난 고유 노드·관계 수가 아니며, 원문과 사실성을 전부 확인한 수치도 아니다.**

### 3.4 뉴스 추출 결과 예시

다음은 저장된 `NEWS-23178d84642bd6c9-C00001` 청크에서 추출한 내용이다.

| 주어 | 서술어 | 목적어 |
| --- | --- | --- |
| 아모레퍼시픽 | 행사에 참여한다 (`PARTICIPATES_IN`) | 2026 국회 입법박람회 |
| 2026 국회 입법박람회 | 장소에서 열렸다 (`EVENT_IN_PLACE`) | 국회 중앙잔디광장 |

두 관계의 근거로 저장된 원문은 다음과 같다.

> “5일 국회 중앙잔디광장에서 열린 2026 국회 입법박람회 경제존 안 아모레퍼시픽 부스에서 피부색 측정을 위해 시민들이 대기하고 있다.”

이 예시는 저장된 청크와 추출 결과를 보여준다. 전체 데이터의 정확도까지 대표하는 표본은 아니다.

## 4. 뉴스 추출 중단 내용

### 4.1 확인된 오류

마지막에 제공된 API 오류 화면에는 다음 메시지가 나타났다.

```text
429 - Project spend limit reached
```

해당 메시지는 **API 프로젝트에 설정된 지출 한도에 도달했다는 뜻**이다. 기존 실행 기록에서 특정 중단 청크의 오류 유형은 `RateLimitError`였다. 화면에서 확인된 한도 문제와 개별 오류 유형을 구분해서 기록한다.

실패한 13개 청크의 저장된 오류 유형은 다음과 같다.

| 오류 유형 | 건수 | 기록에서 확인되는 내용 |
| --- | ---: | --- |
| `RateLimitError` | 5 | API가 요청을 제한한 오류 유형. 한도 화면과 관련 여부를 개별 오류별로 모두 확인한 것은 아님 |
| `APITimeoutError` | 1 | API 요청이 제한 시간 안에 완료되지 않은 오류 유형 |
| `ValueError` | 7 | 형식·값 처리와 관련된 오류 유형. 저장 기록만으로 각 청크의 상세 원인은 확정할 수 없음 |

모든 `RateLimitError`를 지출 한도로, 모든 `ValueError`를 같은 형식 오류로 단정하지 않는다.

### 4.2 중단과 저장

코드는 성공·실패 결과를 SQLite 진행 기록에 저장하고 결과 JSONL을 내보내도록 작성되어 있다. 오류로 신규 요청을 멈출 때 이미 실행 중인 요청도 종료·저장하도록 처리한다.

다만 이번에 확인한 `m4_output(1).zip`에는 `extractions.jsonl`, `status.jsonl`, 구조화 결과, `summary.json`이 있으며 **`progress.sqlite3`는 포함되어 있지 않다.** 사용자의 컴퓨터에 남은 원래 진행 폴더가 있다면 그 폴더를 유지해야 이전 설정으로 이어 실행할 수 있다. 제공된 ZIP만으로 동일한 이어 실행이 가능하다고 가정하지 않는다.

## 5. 공시 지분 관계 추출 작업

### 5.1 입력과 방식

아래 두 공시의 **연결재무제표 주석 1.2 종속기업의 현황**에서 지분 표와 관련 주석을 처리했다.

| 보고서 | 보고서 제출일 | 지분 관측 기준일 |
| --- | --- | --- |
| [홀딩스 2025년 사업보고서](https://kind.krx.co.kr/external/2026/03/18/001082/20260318005107/11011.htm) | 2026-03-18 | 2025-12-31 |
| [홀딩스 2026년 1분기 보고서](https://kind.krx.co.kr/external/2026/05/15/001430/20260515003119/11013.htm) | 2026-05-15 | 2026-03-31 |

공시 처리는 HTML에서 표의 행을 읽는 **규칙 기반 방식**이며 LLM API를 호출하지 않았다. 전체 보고서에서 모든 정보를 추출한 것이 아니라, 이번 지분 관계에 필요한 표와 주석을 선택해 처리했다.

### 5.2 코드와 결과 파일

[공시 원문·추출 코드·결과 ZIP](https://chatgpt.com/library?file_id=libfile_647b2155d8ac819189e30c31022710cf&account_id=572db941-93e9-4f5f-a926-7a495084b755)

| 파일 | 역할 |
| --- | --- |
| `build.py` | HTML 표와 주석을 읽고 청크·기업·지분 관계 후보 생성 |
| `sources/` | 기존에 확보한 공시 원문 HTML |
| `results/documents.jsonl` | 보고서 출처·기준일·원문 표 위치 |
| `results/chunks.jsonl` | 표 행 14개와 주석 4개 |
| `results/entities.jsonl` | 7개 대상 기업과 홀딩스의 회사 ID 후보 |
| `results/relations.jsonl` | 지분 관계 14건의 시점별 관측값 |
| `results/relations.csv` | 지분 관계를 표로 확인할 수 있는 결과 |
| `results/identity_crosswalk_review.jsonl` | 기사 회사 ID와 대표 회사 ID를 비교할 검토 후보 |

`build.py` 전체 코드는 **8절**에 수록했다. 별도의 [공시 전처리 보충 보고서](https://chatgpt.com/library?file_id=libfile_af1fa8ab19408191b8e80bb0b694d025&account_id=572db941-93e9-4f5f-a926-7a495084b755)에서는 전처리 전후 예시와 코드 읽는 방법을 확인할 수 있다.

### 5.3 공시 추출 결과

두 보고서의 표에서 다음 7개 기업 관계를 각각 추출했다. **두 기준일의 표에 기재된 값이 같아 한 표에 함께 표시**했다.

| 투자회사 | 피투자회사 | 보고서 기재 지분율 |
| --- | --- | ---: |
| 아모레퍼시픽홀딩스 | 아모레퍼시픽 | 38.1% |
| 아모레퍼시픽홀딩스 | 이니스프리 | 90.4% |
| 아모레퍼시픽홀딩스 | 에스쁘아 | 100.0% |
| 아모레퍼시픽홀딩스 | 에뛰드 | 100.0% |
| 아모레퍼시픽홀딩스 | 퍼시픽테크 | 100.0% |
| 아모레퍼시픽홀딩스 | 아모스프로페셔널 | 100.0% |
| 아모레퍼시픽 | 코스알엑스 | 90.3% |

결과 JSONL은 2025-12-31과 2026-03-31을 **각각 별도 관측값**으로 저장하므로 총 14건이다. 두 시점의 값이 같다는 사실만으로 그 사이 또는 이후에도 값이 계속 같았다고 단정하지 않는다.

**주석 확인:** 홀딩스가 보유한 아모레퍼시픽 의결권 지분은 과반 미만이지만 보고서는 사실상 지배력으로 종속기업에 포함했다고 설명한다. 이니스프리 지분율에 대해서는 별도재무제표에 자기주식을 제외한 실질지분율이라는 주석이 있어 함께 보존했다.

### 5.4 결과를 사용할 때 확인할 점

- 공시 결과의 홀딩스 ID는 신규 제안 ID다. 기존 기사에서 추출된 홀딩스와 동일 법인인지 확인한 뒤 연결한다.
- 7개 회사 대표 ID와 기사에서 별도로 추출된 회사 ID도 같은 법인인지 검토한다. 브랜드와 회사는 이름이 같아도 자동 병합하지 않는다.
- 퍼시픽테크에 대해 공시 표의 투자회사와 기존 기사 추출 관계가 다르게 표현된 사례가 있다. 출처와 시점을 대조하기 전 하나의 확정 관계로 합치지 않는다.
- 공시 추출 JSONL과 기존 뉴스 M4·M5 결과는 필드 형식이 다르다. 이후 통합 및 M6 적재 시 ID·근거·기준일 매핑이 필요하다.

## 6. 프롬프트와 기존 결과의 관계

어제 뉴스 결과는 **어제 사용한 프롬프트**로 생성됐다. 오늘 M0 CQ와 M2 스키마를 바탕으로 새로 작성한 M3 프롬프트가 기존 결과에 소급 적용된 것은 아니다.

기존 병렬 M4 코드는 입력 파일·모델·프롬프트 등의 설정을 확인하므로, 새 프롬프트를 기존 진행 폴더에 그대로 적용하면 설정 불일치로 실행이 중단된다. 새 출력 폴더를 사용하면 기존 성공분이 자동으로 제외되는 것도 아니다. 미처리 청크에 새 프롬프트를 적용하려면 대상 선정, 이력 기록과 결과 통합 방법을 따로 준비해야 한다.

현재 계획은 **기존 M4 성공 결과와 공시 추출 결과를 우선 활용**하는 것이다. 새 프롬프트를 작성했다는 이유만으로 뉴스 전체를 다시 추출하지 않는다.

## 7. M4 현재 판정과 다음 작업

### 확보한 결과

- [x] 뉴스 추출 실행 코드와 당시 프롬프트
- [x] 뉴스 청크 4,757개의 추출 성공 결과
- [x] 실패·대기 청크와 확인된 오류 기록
- [x] 공시 보고서 2건의 지분 표 추출 코드와 시점별 결과

### 남은 작업

- [ ] 뉴스 전체 추출 여부와 범위 결정. 실패 13개와 대기 2,108개는 현재 스냅샷에서 미완료
- [ ] 뉴스와 공시의 같은 회사 후보를 M5에서 검토하고 정규화
- [ ] 원문·기준일·서술어의 의미가 맞는지 검토하고 충돌 관계 분리
- [ ] 최종 적재 범위를 정한 뒤 M6 입력 형식과 ID에 맞게 매핑
- [ ] AuraDB 적재 후 CQ를 조회하고 원문과 대조

> **판정:** 뉴스 전체에 대한 M4는 진행 중 중단됐다. 뉴스 성공분과 공시 지분 추출 결과를 확보했으며, 이후 M5 정규화와 M6 적재 준비에 활용할 수 있다.

## 8. 공시 추출 전체 코드

아래는 공시 작업 ZIP의 `build.py`를 그대로 수록한 것이다. `lxml`로 원문 HTML을 읽으며 LLM API를 사용하지 않는다. 실행 방법과 각 결과 파일 설명은 ZIP의 `README.md`를 참고한다. 기존 `results` 파일을 다시 작성하므로 재실행할 때는 별도 폴더에 압축을 풀어 사용한다.

```python
from pathlib import Path
from lxml import html
import json, csv, re, hashlib

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results'
OUT.mkdir(exist_ok=True)
SOURCES = [
    {'id':'APH-2025-ANNUAL','file':'holdings_2025_annual.html','as_of':'2025-12-31','filed':'2026-03-18','url':'https://kind.krx.co.kr/external/2026/03/18/001082/20260318005107/11011.htm'},
    {'id':'APH-2026-Q1','file':'holdings_2026_q1.html','as_of':'2026-03-31','filed':'2026-05-15','url':'https://kind.krx.co.kr/external/2026/05/15/001430/20260515003119/11013.htm'},
]
COMPANIES = {
    '아모레퍼시픽홀딩스': ('COMPANY-AMOREPACIFIC-HOLDINGS','주식회사 아모레퍼시픽홀딩스'),
    '아모레퍼시픽': ('COMPANY-AMOREPACIFIC','주식회사 아모레퍼시픽'),
    '이니스프리': ('COMPANY-INNISFREE','주식회사 이니스프리'),
    '에스쁘아': ('COMPANY-ESPOIR','주식회사 에스쁘아'),
    '에뛰드': ('COMPANY-ETUDE','주식회사 에뛰드'),
    '퍼시픽테크': ('COMPANY-PACIFICTECH','주식회사 퍼시픽테크'),
    '아모스프로페셔널': ('COMPANY-AMOSPROFESSIONAL','주식회사 아모스프로페셔널'),
    '코스알엑스': ('COMPANY-COSRX','주식회사 코스알엑스'),
}
def compact(element):
    return ' '.join(element.text_content().split())
def identify(text):
    text = re.sub(r'\(\*\d+\)', '', text).strip().replace('㈜','').replace('(주)','').strip()
    return text if text in COMPANIES else None
def save_jsonl(name, rows):
    with (OUT / name).open('w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

entities = [{'entity_id': value[0], 'name': value[1], 'type':'Company', 'identity_status': '기존_대표ID' if key != '아모레퍼시픽홀딩스' else '신규_제안ID_기존홀딩스와_대조필요'} for key,value in COMPANIES.items()]
chunks, relations, manifests = [], [], []
for source in SOURCES:
    path = ROOT / 'sources' / source['file']
    tree = html.parse(str(path))
    selected = []
    for table in tree.xpath('//table'):
        trs=table.xpath('.//tr')
        rows = [[compact(c) for c in tr.xpath('./th|./td')] for tr in trs]
        if rows and '투자회사' in rows[0] and '피투자회사' in rows[0] and any('퍼시픽테크' in ' '.join(row) and '100.0' in row for row in rows):
            selected.append((table,trs,rows))
    if not selected:
        raise RuntimeError(f'종속기업 표를 찾지 못함: {path}')
    table, trs, rows = selected[0]
    table_xpath = tree.getpath(table)
    data_count = 0
    for i, row in enumerate(rows[1:],1):
        if len(row) < 6: continue
        parent, child = identify(row[0]), identify(row[1])
        if parent not in ('아모레퍼시픽홀딩스','아모레퍼시픽') or child not in COMPANIES or child == '아모레퍼시픽홀딩스': continue
        n=float(row[3]); assert 0 <= n <= 100
        row_path = tree.getpath(trs[i]); chunk_id=source['id']+'-'+COMPANIES[child][0]
        # 표의 결산일은 피투자회사의 결산일이며 소유 기준일이 아니다.
        text=' | '.join(row)
        chunk={'document_id':source['id'],'chunk_id':chunk_id,'as_of_date':source['as_of'], 'section':'연결재무제표 주석 1.2 종속기업의 현황','header':rows[0], 'text':text,'source_xpath':row_path,'source_url':source['url']}
        chunks.append(chunk)
        qualifier='보고서 기재 지분율; 주식 종류 및 분모 별도 확인'
        if child=='아모레퍼시픽': qualifier='연결 종속기업 표의 지분율 38.1%; 의결권 50% 미만에도 사실상 지배 주석. 별도 보통주 주주현황 38.0%와 표·분모 구분'
        if child=='이니스프리': qualifier='보고서 별도재무제표 지분율 주석: 이니스프리 자기주식을 제외한 실질지분율; 명목 지분율로 단정 금지'
        relations.append({'relation_id':'OWN-'+source['as_of']+'-'+COMPANIES[child][0], 'subject_id':COMPANIES[parent][0], 'subject_name':COMPANIES[parent][1], 'predicate':'OWNS_STAKE','object_id':COMPANIES[child][0], 'object_name':COMPANIES[child][1], 'value_number':n,'unit':'%', 'as_of_date':source['as_of'], 'percentage_basis':qualifier, 'source_document_id':source['id'], 'chunk_id':chunk_id,'evidence_quote':text,'review_status':'공시표_대조완료_적재전_스키마검토필요','scope':'표의 투자회사별 지분율; 간접 지분 추정 아님'})
        data_count += 1
    assert data_count==7,(source['id'],data_count)
    # 38.1%에 붙은 주석을 원문에서 추출하여 별도 보존한다.
    notes=[compact(e) for e in tree.xpath('//p') if '지배기업이 보유한 의결권 있는 지분율은 50% 미만' in compact(e)]
    assert notes
    notes2=[compact(e) for e in tree.xpath('//p') if '이니스프리가 보유하고 있는 자기주식을 제외한 실질지분율' in compact(e)]
    assert notes2
    for kind,txt in [('control',notes[0]),('innisfree_basis',notes2[0])]:
        chunks.append({'document_id':source['id'],'chunk_id':source['id']+'-NOTE-'+kind,'as_of_date':source['as_of'],'section':'종속기업 지분율 주석','text':txt,'source_url':source['url']})
    manifests.append({**source,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'table_xpath':table_xpath,'target_rows':data_count})

# 기존 M5의 별도 회사 노드는 같은 법인인지 검토할 후보로만 기록한다.
aliases=[('이니스프리','AUTO-3d295451c1408042c9ad79cb'),('에스쁘아','AUTO-7785385cb280f1df432367ec'),('에뛰드','AUTO-48ad7b9e61f64a1c361248a0'),('퍼시픽테크','AUTO-7f4fedbbd22e3c9296148c89'),('아모스프로페셔널','AUTO-043dbec8e837fb94f889d3eb'),('아모레퍼시픽홀딩스','AUTO-35e7396534ca88cbf4b974da')]
crosswalk=[{'original_entity_id':old,'original_name':name,'candidate_entity_id':COMPANIES[name][0],'entity_type':'Company','decision':'동일법인_검토후_병합','reason':'명칭 후보; 기존 원문 문맥과 법인 식별자 확인 필요. 브랜드 개체는 병합하지 않음'} for name,old in aliases]
save_jsonl('documents.jsonl', manifests)
save_jsonl('chunks.jsonl', chunks)
save_jsonl('entities.jsonl', entities)
save_jsonl('relations.jsonl', relations)
save_jsonl('identity_crosswalk_review.jsonl', crosswalk)
with (OUT/'relations.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(relations[0]));w.writeheader();w.writerows(relations)
assert len(relations)==14 and len(entities)==8
assert len({r['relation_id'] for r in relations})==14
print(f'문서 {len(manifests)}, 근거 청크 {len(chunks)}, 회사 {len(entities)}, 관계 {len(relations)}, 매핑 검토 {len(crosswalk)}')

```
