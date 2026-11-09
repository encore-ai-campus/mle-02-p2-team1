# 아모레퍼시픽 GraphRAG 파일럿

뉴스 JSONL을 청크로 나누고 OpenAI로 관계 후보를 추출해 근거를 검증한 뒤 Neo4j Aura에 적재한다. 질문은 청크 벡터 검색과 연결 개체를 통한 관계 확장으로 근거를 모아 답한다. 팀의 최종 온톨로지가 아닌 시험용이며 자동 추출 관계는 미검토다.

## 준비

저장소 루트에서 실행한다. Python 환경에 기존 의존성 외 Neo4j 드라이버가 필요하다. 현재 잠금 파일에는 드라이버가 없으므로 다음 명령으로 설치한다.

```sh
uv pip install 'neo4j>=5.26,<7'
```

기존 `.env`에 다음 값을 설정한다. 비밀값은 저장소에 올리거나 대화에 붙여 넣지 않는다.

```dotenv
OPENAI_API_KEY=발급받은_키
NEO4J_URI=neo4j+s://인스턴스주소.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=발급받은_비밀번호
NEO4J_DATABASE=neo4j
```

뉴스 본문은 추출과 임베딩 시 OpenAI에 전송되고 Aura에도 저장된다. 이용 조건을 확인한 자료만 실행한다. API 사용료와 Aura 사용량이 발생한다. 출력 파일에 기사 전문이 담기므로 `/tmp` 등 로컬에 두고 커밋하지 않는다.

## 실행

```sh
# 새 출력 파일을 지정한다. 입력은 전체 1,236건이며 아모레퍼시픽 언급 여부를 별도로 필터링하지 않는다.
PYTHONPATH=src .venv/bin/python -m bulsae.graphrag.prepare data/collected/news.jsonl /tmp/bulsae-chunks.jsonl
# 처음 5개 청크만 추출한다. 모델은 접근 권한에 맞춰 --model로 변경할 수 있다.
PYTHONPATH=src .venv/bin/python -m bulsae.graphrag.pipeline extract /tmp/bulsae-chunks.jsonl /tmp/bulsae-extracted.jsonl --limit 5
# extracted.jsonl의 claims, rejected와 원문을 사람이 검토한다.
PYTHONPATH=src .venv/bin/python -m bulsae.graphrag.pipeline load-structured
PYTHONPATH=src .venv/bin/python -m bulsae.graphrag.pipeline load /tmp/bulsae-extracted.jsonl
PYTHONPATH=src .venv/bin/python -m bulsae.graphrag.pipeline ask '아모레퍼시픽의 주요 협력 관계는 무엇인가요?'
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

`extract` 기본 모델은 `gpt-4o-mini`, 임베딩은 `text-embedding-3-small` 1,536차원이다. 각 추출 파일은 새 파일이어야 하며 실패 시 일부 결과가 남을 수 있다. 재시도하려면 새 파일을 지정한다. 청크 설정을 바꾸면 ID가 달라지며 기존 DB 노드는 자동 삭제되지 않는다. 파일럿 전용 Aura 데이터베이스를 사용한다. 재적재는 같은 ID를 `MERGE`하지만 추출 결과에서 없어진 기존 관계는 삭제하지 않는다.

## 근거와 모델

청크에는 문서 ID, URL, 게시일, 원문 해시, 수집된 `content`의 문자 오프셋을 보관한다. 청크 기본 크기는 1,200자, 중복은 150자다. 수집된 본문 기준 오프셋이지 웹 HTML 위치가 아니다. 모델이 추출한 인용이 청크에 정확히 존재하지 않거나 필드가 잘못되면 거부한다. 이 검사는 인용 존재만 확인하며 관계 해석의 진위를 보장하지 않는다.

그래프는 `Document`–`Chunk`, `Claim`–주어/목적어 `Entity`, `Claim`–근거 `Chunk`로 구성한다. 아모레퍼시픽 법인만 기존 `COMPANY-AMOREPACIFIC` ID로 연결하며 다른 이름은 문서별로 구분해 동명이인 오결합을 줄인다. 그 결과 같은 외부 개체가 다른 문서에 있어도 자동으로 합쳐지지 않는다. 발언·계획·불확실성은 claim 상태에 남고 모든 관계는 기본적으로 `unreviewed`다. 아모레퍼시픽 기업 기본정보 및 재무기록은 구조화 JSONL에서 별도로 가져오며 필드별 출처도 저장한다.

검색 결과는 유사도 상위 청크와 해당 청크의 관계, 공유 개체에 연결된 관계의 근거를 포함한다. 공유 개체가 아모레퍼시픽일 때 관련성이 낮은 관계도 확장될 수 있으므로 답변과 출처를 확인한다. 회사 정보와 재무 기록도 답변 근거로 전달된다. 동일 질문에서 일반 청크 검색과 비교하고, 관계 정확도·근거 적합성·누락을 사람이 검토한 다음 규모를 늘린다.
# Neo4j 정제 원문 기반 관계 후보 추출

`extract-documents`는 이미 저장된 `BulsaeDocument.content`를 기사 단위로 읽습니다.
문서·청크 관계선은 만들지 않습니다. 근거 줄 번호와 문자 위치는 해당 정제 본문의
SHA-256을 함께 저장하므로, 이후 본문이 바뀌었다면 근거를 다시 대조해야 합니다.
기사 1건당 추출 호출 1회, 유효 후보가 있으면 의미 검토 호출이 추가됩니다.
형식과 근거 검사, 두 번째 모델 검토를 통과한 결과도 검증된 사실이 아닌
`검토 전` 관계 후보입니다. 기존 대상 기업 ID를 재사용하고, 다른 대상은 문서별
후보로 분리하므로 같은 이름이 다른 기사에 등장해도 자동 병합하지 않습니다.

노드는 `BulsaePerson`, `BulsaeCompany` 등 유형별 공통 라벨을 사용합니다.
자동 추출 노드는 구분과 `candidate_id` 제약을 위해 `BulsaeKGCandidate` 라벨을
추가로 가집니다. 같은 이름은 동일 개체가 아닐 수 있으므로 자동 병합하지 않습니다.

```bash
uv run python -m bulsae.graphrag.pipeline extract-documents \
  --checkpoint private_data/document_kg.sqlite --workers 4 --limit 10
```

`--load`를 추가하면 검토 전 후보와 기존 정형 재무 기록의 기업 연결을 Neo4j에
적재합니다. 같은 체크포인트로 재실행하면 완료된 기사를 건너뛰며
`--retry-failed`로 실패한 기사를 재시도할 수 있습니다. 체크포인트에 기사에서
추출한 이름과 근거 ID가 들어가므로 공유·커밋하지 않습니다. 사용자가 허용한
처리 건수를 확인하고, 전체 실행은 `--limit` 없이 실행합니다.

`--workers`는 기사 추출의 동시 작업 수이며, Neo4j 쓰기는 최대 4건으로 별도
제한합니다. 모델·입력 토큰 제한 또는 DB 용량에 따라 적절히 조절합니다. 연속
실패가 발생하면 실행을 멈추고 성공·실패 기록을 체크포인트에 남깁니다.
진행 상황은 외부 호출 없이 다음 명령으로 확인할 수 있습니다.

```bash
uv run python -m bulsae.graphrag.pipeline report-documents \
  --checkpoint private_data/document_kg.sqlite
```

`uv run python -m bulsae.graphrag.pipeline audit-document-graph`는 근거에 회사가
아니라 이름이 비슷한 그룹·재단만 나타나는 의심 사례를 집계합니다. `--mark`를
추가하면 해당 관계를 삭제하지 않고 `검토 필요`로 표시합니다. 이 검사는 일부
명칭 혼동만 찾는 보조 규칙이며 모든 오류를 찾거나 사실을 확정하지 않습니다.

한계: 자동 검사와 모델의 2차 검토가 정확성·완전성을 보장하지 않습니다. 특히
같은 사람이나 외부 기업을 다른 기사 사이에서 동일 인물로 자동 병합하지 않아
일부 다중 문서 경로가 끊어질 수 있습니다. 검토 대기 후보와 실패 건은
체크포인트에 보존되며 골든셋과 표본으로 추출 품질을 별도 평가해야 합니다.

### 테스트 화면의 답변 표시

사용자 요청에 따라 자동 검사를 통과한 답변은 사람의 추가 승인 없이 표시합니다.
DB의 검토 상태는 변경하지 않으며 화면에 `검토 전` 안내를 반복하지 않습니다.
일반 답변은 쉬운 한국어 설명과 원문 인용을 분리합니다. 인용의 원문 일치를
검사한 다음 LLM이 설명의 대상·수치·기간·관계 방향을 인용과 대조합니다.
불일치 또는 근거 부족이면 기존 답변 보류 흐름을 유지합니다.

`web_server.present_response`가 답변 항목과 근거 기사 목록을 분리해 반환합니다.
일반 관계·인물 행사 답변의 근거는 화면에서 펼쳐 보며 같은 기사 내 중복 문장을
합칩니다. 정형 기업 정보·재무 답변은 기존 텍스트 형식도 지원합니다.
배포 화면은 로컬 `web_server`에 연결하므로 서버 실행이 필요합니다.
