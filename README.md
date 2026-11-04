# MLE 2기 2차프로젝트 1팀 — 데이터 수집·정리 작업공간

## 폴더 구성

- `data/raw/`: API 응답과 공시 원문 ZIP 등 수집 원본
- `data/shared/`: 확인된 공통 기업 목록과 기업 간 관계
- `data/collected/suyeon/`: 이니스프리·에스쁘아 담당 자료
- `data/collected/anna/`, `data/collected/seonghyeon/`: 같은 파일 형식의 담당자별 작업 폴더
- `data/SCHEMA.md`: CONNECT 설계안에 맞춘 JSONL 레코드 단위와 필드 기준

담당자 폴더마다 `documents.jsonl`과 6개 조사 JSONL 파일을 둡니다. 모든 조사 레코드는 공통 기업 ID와 담당자별 문서 ID로 연결합니다. 수연 폴더에는 이니스프리·에스쁘아의 DART 공시, 기업개황 응답 및 확인된 공개자료를 CONNECT 필드 기준으로 정리했습니다. 자세한 건수와 남은 확인 사항은 `data/collected/suyeon/COLLECTION_STATUS.md`에 있습니다.

## 이니스프리·에스쁘아 수집 흐름

1. `.env.example`을 `.env`로 복사하고 `OPENDART_API_KEY`와 공공데이터포털 `DATA_GO_KR_API_KEY`를 로컬에서 입력합니다. 두 키는 서로 다른 서비스용이며, 키를 채팅·코드·JSONL 파일에 넣지 않습니다.
2. DART 법인 후보를 수집합니다.

   ```powershell
   python src/collect_dart.py --discover
   ```

3. 공식 법인명·DART 고유번호를 확인하고 `shared/companies.jsonl`의 내부 `company_id`와 `config/targets.json`을 대조합니다. 브랜드명만으로 법인을 자동 확정하지 않습니다. 금융위 기업기본정보 API도 별도 수집할 수 있습니다.

   ```powershell
   python src/collect_public_data.py
   ```

   API 응답에서 Open DART 고유번호가 일치하는 법인만 확인하고 `data/raw/public_data/`에 원응답을 저장합니다. 계열회사 조회는 기준일·법인번호 필터가 확인된 경우에만 사용합니다.
4. 기간을 정해 기업개황 및 공시목록을 받고, 필요 공시 원문 ZIP을 내려받습니다.

   ```powershell
   python src/collect_dart.py --from-date YYYYMMDD --to-date YYYYMMDD --download-documents
   ```

5. 수집 원문을 정리합니다. 문서마다 고유 `DOC-SY-` ID를 부여하고 `source_name`, `company_ids`, `raw_path`, `clean_text`, `processing_status`를 기록합니다. 원문 이용이 허용되지 않으면 본문 대신 출처와 메타데이터만 남깁니다.

   ```powershell
   python src/preprocess_dart.py
   ```

6. 감사보고서에서 재무기간별 기본 정보와 주요 손익을 추출합니다. 매출액·영업이익은 스키마에 따라 원 단위 숫자로 기록하며, 확인되지 않은 정보는 `null`로 둡니다.

   ```powershell
   python src/extract_company_info.py
   ```

재무 기간별 자료와 나머지 주제별 레코드는 CONNECT의 공통 필드와 파일별 추가 필드를 함께 씁니다. 한 레코드 안에 서로 다른 재무 기간을 합치지 않고, 모든 사실은 해당 문서 ID와 확인 근거에 연결합니다. 필드명·허용값·null 기준은 `data/SCHEMA.md`를 따릅니다.

## 환경

Visual Studio Code와 Python은 이미 설치되어 있습니다. 기존 프로젝트 환경은 `pyproject.toml`과 `uv.lock`으로 준비하고, 수집·Neo4j·LLM 작업에 추가로 필요한 라이브러리는 `requirements-data-pipeline.txt`로 설치합니다. 이 프로젝트에서 실제로 사용하는 라이브러리는 요청·HTML 수집, Neo4j 연결, LangGraph 검색 흐름에 필요한 패키지입니다. JSONL 파일 처리에는 표준 라이브러리를 사용하므로 pandas는 추가하지 않았습니다. 다른 PC에서는 `uv` 설치 후 다음 명령으로 같은 환경을 준비합니다.

```powershell
uv sync
uv pip install -r requirements-data-pipeline.txt
```

## 저장소에 포함하는 데이터 범위

저장소의 `data/collected/suyeon/documents.jsonl`은 자료 ID·제목·출처 링크 등 문서 메타데이터만 담습니다. 원문 본문(`clean_text`)과 로컬 원문 경로(`raw_path`)는 공개 저장소에 포함하지 않습니다. API 원응답과 전처리·LLM 후보 파일도 `.gitignore`에 따라 로컬에만 둡니다.

## Neo4j 연결 및 수연 자료 적재

1. `.env.example`을 `.env`로 복사하고 Neo4j 비밀번호를 `NEO4J_PASSWORD`에 로컬로 입력합니다. 비밀번호는 채팅이나 데이터 파일에 넣지 않습니다.
2. 먼저 JSONL 참조와 적재 범위를 확인한 뒤 서버 연결을 점검합니다.

   ```powershell
   uv run python src/neo4j_suyeon.py validate
   uv run python src/neo4j_suyeon.py check
   ```

3. 연결 확인이 성공하면 이니스프리·에스쁘아 자료만 멱등 적재합니다. 기존 데이터를 삭제하는 명령은 없습니다.

   ```powershell
   uv run python src/neo4j_suyeon.py load
   uv run python src/neo4j_suyeon.py search "매출 영업이익"
   ```

현재 그래프 라벨과 관계는 `data/collected/suyeon/GRAPH_IMPORT_PREPARATION.md`에 적힌 제안입니다. 팀의 확정 구조도와 대조한 뒤 공통 그래프 스키마가 다르면 적재 전에 맞춥니다.

## 수연 자료 전처리 청킹

수집·정제된 이니스프리·에스쁘아 문서에 안정적인 청크 ID와 원문 문자 위치를 부여하고, 조사 JSONL의 필수 필드·회사 ID·문서 ID·근거 연결을 점검합니다.

```powershell
uv run python src/prepare_suyeon_chunks.py
```

산출물은 `data/processed/suyeon/document_chunks.jsonl`, `PREPARATION_REPORT.md`, `preparation_manifest.json`입니다. 청킹은 기존 정제 본문을 나누기만 하며 새로운 사실이나 LLM 출력을 만들지 않습니다.

## OpenAI 개체·관계 추출 후보

추출 결과는 검토용 후보 파일로 저장하며, 기존 수집 JSONL이나 Neo4j를 자동 변경하지 않습니다. 기본 모델은 `gpt-6-luna`입니다. `.env`에 `OPENAI_API_KEY`를 로컬로 입력한 뒤 비용 추정과 작은 범위 실행을 먼저 할 수 있습니다.

```powershell
uv run python src/extract_suyeon_openai.py estimate
uv run python src/extract_suyeon_openai.py run --limit 5
```

결과 확인 후 전체 수연 문서를 처리하려면 다음을 실행합니다. 완료된 청크는 건너뛰어 중단 후 재실행할 수 있습니다. 기본 비용 상한은 보수적 추정액 기준 $1.75입니다.

```powershell
uv run python src/extract_suyeon_openai.py run
```

원 후보는 `openai_extraction_candidates.jsonl`, 정규화 개체와 중복 제거 관계는 `openai_extraction_entities_normalized.jsonl`, `openai_extraction_relations_deduped.jsonl`에 저장됩니다. 인용 위치가 확인된 관계와 수동 검토 관계는 각각 `openai_extraction_relations_with_evidence.jsonl`, `openai_extraction_relations_needs_review.jsonl`로 나뉩니다. 전체 결과는 `OPENAI_EXTRACTION_REPORT.md`, 사용량 요약은 `openai_extraction_summary.json`을 확인하세요. API 응답 저장은 끄고(`store=False`) 처리합니다. 자동 추출은 기존 조사 파일이나 Neo4j에 반영하지 않으므로 팀 검토 후 반영합니다.

현재 수연 담당 범위의 DART 수집·전처리, 금융위 기업개요·계열회사 API 전체 응답 확인, 공정위 기업집단 API 확인 및 공개자료 기록을 정리했습니다. 기준일별 건수와 해석상 제한은 `data/collected/suyeon/COLLECTION_STATUS.md`에 기록합니다. 뉴스와 정치·정책 자료는 해당 문서에 적힌 검색 범위 기준이며 새 자료가 발견되면 추가합니다. 재수집 시 API 키와 법인 식별 정보를 확인합니다. Open DART API 호출의 세부 기준은 [수집 안내](https://connect-architecture-docs.dkssk136136.chatgpt.site/#disclosure-links)와 [공식 API 안내](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001)를 따릅니다.

수연 담당 자료의 건수와 수집 범위·해석상 유의점은 `data/collected/suyeon/COLLECTION_STATUS.md`를 확인하세요. 파일 단위와 필드 기준은 `data/SCHEMA.md`를 참고하세요.
