# 수연 OpenAI 개체·관계 추출 결과

## 처리 범위

- 모델: `gpt-6-luna`
- 처리 청크: 1,033/1,033
- 입력/출력 토큰: 1,980,955 / 534,980
- OpenAI 표준 단가 기준 사용액 추정: $0.4656 (실제 청구 금액은 계정의 요금 조건에 따라 달라질 수 있음)
- 호출 오류 미해결: 0
- API 응답 저장은 끈 상태(`store=False`)로 실행했습니다.

## 추출·정규화 결과

- 관계 후보: 5,540건
- 중복 제거 후 관계: 4,977건
- 확인 가능한 인용 위치: 4,881건
- 근거 재검토 대상: 96건
- 정규화 개체: 1,038개 (팀 공통 기업 ID 매핑 7개; 나머지는 정확 표기 기반 후보 ID)

### 관계 후보의 domain 분포

- `company_info`: 4,546건
- `market`: 76건
- `owner`: 257건
- `politics`: 1건
- `social_issue`: 18건
- `strategy`: 79건

## 사용 기준

이 결과는 청크 단위 LLM 추출 후보입니다. 인용문이 원문 청크에 그대로 위치하지 않는 관계는 검토 파일로 분리했습니다. domain 분류·사실 해석·인물 및 일반 조직 개체의 병합은 자동 확정하지 않았습니다. 기존 수집 JSONL 및 Neo4j에는 반영하지 않았습니다.

## 파일

- 전체 청크별 결과: `data/processed/suyeon/openai_extraction_candidates.jsonl`
- 정규화 개체: `data/processed/suyeon/openai_extraction_entities_normalized.jsonl`
- 중복 제거 전체 관계: `data/processed/suyeon/openai_extraction_relations_deduped.jsonl`
- 인용 위치 확인 관계: `data/processed/suyeon/openai_extraction_relations_with_evidence.jsonl`
- 인용 위치 검토 관계: `data/processed/suyeon/openai_extraction_relations_needs_review.jsonl`
