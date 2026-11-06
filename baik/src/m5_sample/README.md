# M5 개체 정규화: 실제 M4 소규모 사례

이 패키지는 실제 LLM 추출 5청크에 대한 검토 결정과 적용 코드, 결과를 보존한다. 자동 API 추출 전체에 대한 확정 결과가 아니다. 데이터베이스 접속·변경은 없다.

## 전후

| 항목 | 정규화 전 | 정규화 후 |
|---|---:|---:|
| 뉴스 개체 언급 | 9 | 4개 대표 개체 후보 |
| 구조화 개체 | 21 | 21 (아모레퍼시픽은 뉴스와 공유) |
| 전체 대표 개체 후보 | - | 24 |
| 뉴스 관계 | 5 | 출처별 주장 5, 동일 속성 그룹 관계 3 |
| 구조화 관계 | 14 | 14 (원출처 검토 필요) |

두 기사에서 아모레퍼시픽→국회 입법박람회, 행사→국회 중앙잔디광장 관계가 각각 반복된다. 뉴스 주장 5건은 `news_assertions.jsonl`에 각각 원문 인용·기사 URL·청크 ID로 보존한다. `news_relations_grouped.jsonl`의 세 관계에는 그 주장 ID 목록이 연결되어 출처를 역추적할 수 있다. 즉 19건의 출처별 관계 기록(구조화 14 + 뉴스 5)과 17건의 그룹 관계 후보(14 + 3)는 다른 집계다. Neo4j에 실제로 적재된 수가 아니다.

## 개체 결정

- 뉴스 Company 아모레퍼시픽 4개 언급 → 기존 `COMPANY-AMOREPACIFIC`. 법인 문맥을 고려한 소규모 사례 판단이며 전체 기사에 자동 적용하지 않는다.
- 기사 2건의 2026 국회 입법박람회 → `M5-EVENT-2026-ASSEMBLY-EXPO`.
- 기사 2건의 국회 중앙잔디광장 → `M5-PLACE-ASSEMBLY-LAWN`.
- 기사 1건의 인물 박원석 → 임시 `M5-PERSON-PARK-WONSEOK-EXAMPLE`. 동명이인 자동 병합 금지.
- 동일명 브랜드/법인은 별도 개체다. 원문이 충분하지 않은 출처·기업 정보, 재무자료는 원출처 검토 상태 유지.

`review_decisions.jsonl`은 각 문서·청크·local_id에 대해 확인한 결정이다. 원문 청크와 개체의 SHA-256을 기록해 텍스트나 추출 개체가 바뀌면 같은 이름이라도 자동 승인하지 않는다. 새 청크의 새로운 언급은 `unresolved_mentions.jsonl`로 분리되며 연결 관계는 `unresolved_relations.jsonl`에 남는다. 이 파일은 편의상 만든 수동 사례이지 팀의 최종 승인 결정이 아니다. 엔티티 자체 해시 외에 관계 전체 변경은 별도 검증해야 한다.

## 실행

Python 3.10 이상, 표준 라이브러리만 사용한다. 압축을 풀고 해당 폴더에서 PowerShell로:

```powershell
uv run .\resolve_m5.py --input .\sample_input --decisions .\review_decisions.jsonl --output .\my_m5_output
```

출력 폴더가 존재하면 덮어쓰지 않고 중단한다. `sample_output`은 제공된 5개 청크에 대해 실행한 결과다. 새로 추출한 결과는 동일한 `extractions.jsonl`, `structured_entities.jsonl`, `structured_relations.jsonl`이 있는 폴더를 input으로 쓰되, 이 결정은 기존 5청크에만 적용된다. 새로운 언급을 검토하려면 M5 결정 기록·검증을 별도 진행해야 한다.

## 결과 파일

- `entities.jsonl`: 구조화 21개 + 새 뉴스 후보 3개. 기업 정보의 원문 출처 및 검토 상태 포함.
- `mentions_mapping.jsonl`: 문서·청크·로컬 ID에서 대표 ID로 연결한 전후 사례.
- `news_assertions.jsonl`: 뉴스 관계 5개와 각각의 근거·출처.
- `news_relations_grouped.jsonl`: 양 끝점·유형·속성이 완전히 같은 관계를 묶은 조회 후보와 assertion ID.
- `structured_relations.jsonl`: 기업→재무 지표 14개와 원자료 출처.
- `unresolved_mentions.jsonl`, `unresolved_relations.jsonl`: 검토되지 않은 언급 및 관계. 비어 있어도 파일 생성.
- `summary.json`: 건수 요약.

## 한계

관계의 근거 문자열이 청크에 포함되어 있는지 검사하며 의미상 옳은지 자동 판단하지 않는다. 첫 두 기사에서 같은 행사를 지칭한다는 것은 현재 사례의 문맥을 바탕으로 한 판단이므로 행사 시점 등 원문 재검토가 필요하다. 정규화는 M5이며 AuraDB 적재·재적재 중복 검증이 아니다. 직원수 후보는 국민연금 가입자수일 수 있고 필드별 출처가 부족하다. 재무 수치의 단위·기간과 원문을 대조해야 한다. 민감정보와 저작권 자료를 포함할 수 있으므로 샘플 입력과 결과를 팀 외부에 공유하기 전 확인한다.
