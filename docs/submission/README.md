# 프로젝트 필수 산출물 안내

이 문서는 MLE 2기 2단위 프로젝트의 두 필수 산출물과 관련 자료를 찾기 위한 안내입니다. 팀의 최종 제출본은 아닙니다. 기존 자료의 작성 시점과 대상 데이터셋이 다르므로 제출 전 팀이 실제 구현과 대조해야 합니다.

## 1. LLM 기반 개체·관계 추출 프롬프트 및 코드

| 항목 | 현재 자료 | 제출 전 확인 |
|---|---|---|
| 문서와 프로젝트 소개 | [프로젝트 README](../../README.md), [프로젝트 이해 가이드](../guides/01_프로젝트_이해_가이드.md) | 최종 문서 목록, 출처, 버전, 선정 이유와 사용 범위를 정리합니다. |
| 전처리·분할 | [청크 생성 코드](../../src/bulsae/graphrag/prepare.py), [수집 및 실험 노트북](../../data_code/) | 실제 제출 파이프라인의 전처리 기준과 공유 가능한 전후 예시를 선정합니다. |
| 실제 추출 프롬프트 | [문서 단위 추출 프롬프트 `prompt_for`](../../src/bulsae/graphrag/document_graph.py), [팀원 M3 추출 프롬프트](../../baik/new/M3_extraction_prompt.txt) | 서로 다른 작업 경로입니다. 실제 시연에 사용한 프롬프트와 모델 설정을 명시합니다. |
| 추출·검증 | [문서 기반 추출 코드](../../src/bulsae/graphrag/document_graph.py), [실행 명령](../../src/bulsae/graphrag/pipeline.py) | 실제 입력 → 추출 → 검증 → 저장 과정을 같은 문서 사례로 연결합니다. |
| 개체 정규화 | [정규화 코드](../../src/bulsae/graphrag/resolve_identities.py), [추가 정규화](../../src/bulsae/graphrag/resolve_more.py), [LLM 비교](../../src/bulsae/graphrag/resolve_llm.py) | 시연에 쓰인 방법과 동일·상이 개체의 판단 근거를 정리합니다. |
| 실행 안내 | [프로젝트 파일 안내](../../00_파일_안내.md), [파이프라인 안내](../../src/bulsae/graphrag/README.md) | 데이터 위치와 최신 환경·명령을 실제로 확인합니다. 파이프라인 안내에는 이전 파일럿 설명도 섞여 있습니다. |

문서 기반 추출은 `BulsaeDocument.content`의 줄과 문자 위치를 근거로 사용합니다. 문서·청크 노드에 관계선을 만들지 않는 구현이므로, 청크 중심의 이전 파일럿 설명과 혼동하지 않습니다. API 추출 및 적재는 비용이나 DB 변경이 발생할 수 있으므로 실행 조건을 먼저 확인합니다.

## 2. Neo4j 지식그래프 시각화 결과물 및 스키마

| 항목 | 현재 자료 | 제출 전 확인 |
|---|---|---|
| 현재 추출 허용 유형과 방향 | [문서 단위 추출 코드의 `NodeType`, `RelationType`, `PATTERNS`](../../src/bulsae/graphrag/document_graph.py) | 실제 적재 데이터와 일치하는 팀 최종 스키마 표를 작성합니다. |
| 팀원 스키마 초안 | [M2 스키마](../../baik/docs/M2_four_files_schema.md), [M2 연결 규칙](../../baik/new/M2_schema_and_connection_rules.md) | 초안과 문서 기반 구현은 동일한 최종 스키마가 아닙니다. 적용 범위를 구분합니다. |
| 정규화 사례 | [M5 완료 보고서](../../baik/new/M5_completion_report.md), [M5 결과 안내](../../baik/new/M5_local_resolution/README.md) | 실제 시연 데이터셋에 해당하는 전후 사례와 오병합 점검 결과를 선정합니다. |
| 적재 코드 | [문서 단위 추출·적재 코드](../../src/bulsae/graphrag/document_graph.py), [팀원 M6 패키지](../../baik/new/M6_AuraDB_loading_package/M6_aura_complete/README.md) | 두 경로의 대상과 데이터셋을 구분하고 실행 방법을 확인합니다. |
| Cypher와 시각화 | [팀원 M7 쿼리](../../baik/new/M7_query_package/M7_query_package/queries.py), [M7 완료 보고서](../../baik/new/M7_completion_report.md), [그래프 이미지 폴더](../../baik/new/M7_completion_report_bundle/images/) | 시연할 실제 데이터셋의 쿼리, 결과 화면과 설명을 함께 선정합니다. M7 패키지 README는 작성 당시 조회 전 상태를 설명하므로 완료 보고서와 구분합니다. |
| 정합성 검증 | [팀원 M8 완료 보고서](../../baik/new/M8_completion_report.md), [검증·시연 체크리스트](검증_시연_체크리스트.md) | 실제 검토 대상과 범위, 오류 수정·재확인 내역을 제출 자료로 정리합니다. |

## 공통 제출 준비

1. [ ] 위 두 산출물에서 **팀이 실제 시연할 데이터셋과 코드 경로**를 정하고 팀원들과 일치 여부를 확인합니다.
2. [ ] 공유 가능한 실제 입력·출력 예시와 원문 근거를 선정하고, 자료별 공유 범위를 확인합니다.
3. [ ] 전처리 → 추출 → 정규화 → 적재 → 조회가 이어지는 대표 사례를 준비합니다.
4. [ ] 실제 Neo4j 쿼리와 시각화 화면, 검증 사례 및 현재 한계를 정리합니다.
5. [ ] 팀 역할 분담과 [KPT 회고](검증_시연_체크리스트.md#팀-회고-kpt)를 팀원과 작성합니다.
6. [ ] README에서 실행 환경, 환경변수 **이름**, 실행 순서와 산출물 위치를 확인합니다. 비밀값은 넣지 않습니다.
7. [ ] 1차 가이드의 제출 경로·파일 형식과 발표자료 요구사항을 확인합니다. 이 문서는 형식 요건 확인을 대신하지 않습니다.

로컬 `private_data/`의 기록은 Git에서 제외되며 기사 원문과 근거가 포함될 수 있습니다. 위 링크는 위치 안내이지 공유·제출 승인을 뜻하지 않습니다. Git에 이미 추적 중인 데이터도 있으므로 공유 범위를 별도 확인합니다.
