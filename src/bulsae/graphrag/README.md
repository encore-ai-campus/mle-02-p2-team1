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
