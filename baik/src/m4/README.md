# 네 파일 M4 추출 실행 안내

Python 3.10 이상, OpenAI API 키와 모델 접근 권한이 필요합니다. 실행 시 API 요금이 발생하며 뉴스가 외부 API에 전송됩니다. 팀에서 전송 가능한 자료인지 확인하세요. Neo4j에 쓰지 않습니다. LLM은 완전성이나 사실 정확성을 보장하지 않습니다.

## 준비

`run_m4.py`, `system_prompt.txt`와 네 JSONL을 같은 폴더에 둡니다. Windows PowerShell에서 프로젝트 폴더에 설치합니다.

```powershell
uv add openai python-dotenv
```

프로젝트 `.env`에 `OPENAI_API_KEY=자신의_키`를 설정합니다. 실제 키는 채팅·GitHub에 공유하지 마세요. 출력은 원문과 모델 응답을 포함하므로 공유 전 검토합니다.

## 소량 실행

`사용할_모델명`을 자신의 API 계정에서 접근 가능한 JSON 출력 지원 모델로 바꿉니다.

```powershell
uv run .\run_m4.py --companies .\companies.jsonl --company-info .\company_info.jsonl --financials .\financials.jsonl --news '.\news(1).jsonl' --output .\m4_output --model 사용할_모델명 --limit 5
```

5는 **기사 건수가 아니라 청크 건수**입니다. 긴 기사는 여러 청크가 됩니다. 전체 기사와 청크 목록은 미리 생성하고 5개만 호출합니다.

## 전체 실행과 재시도

같은 폴더와 같은 인자에서 `--limit 5`만 빼고 다시 실행하면 이미 성공한 청크를 건너뛰고 미처리 청크를 이어갑니다.

```powershell
uv run .\run_m4.py --companies .\companies.jsonl --company-info .\company_info.jsonl --financials .\financials.jsonl --news '.\news(1).jsonl' --output .\m4_output --model 사용할_모델명
```

실패 건은 기본적으로 보존하며 자동 반복하지 않습니다. 문제 해결 후 같은 명령에 `--retry-failed`를 추가하면 실패도 재시도합니다. 인증·권한·요금 제한 오류는 중단합니다. 중단 후 재실행하면 SQLite 기록을 사용해 이어갑니다. 다른 입력 파일·프롬프트·모델·청크 길이는 새 결과 폴더를 사용해야 합니다. 여러 프로세스에서 같은 출력 폴더를 동시에 실행하지 마세요.

## 결과 파일

- `structured_entities.jsonl`, `structured_relations.jsonl`: 기업과 재무 관측 및 회사→지표 관계 후보. 원본 레코드와 출처를 보존하며 확정 사실은 아닙니다.
- `structured_candidates.jsonl`: 기업·기본정보·재무 원본 레코드와 검토 상태. LLM 출력이 아니며 노드·관계로 정규화된 확정 결과가 아닙니다. 국민연금 가입자 수와 전체 직원 수는 구분해야 합니다.
- `chunks.jsonl`: 문서 ID·청크 ID·원문·출처 및 원문 오프셋.
- `extractions.jsonl`: 성공한 입력과 LLM 개체·관계 JSON.
- `status.jsonl`: 성공(success), 실패(failed), 미처리(pending), 빈 본문(empty) 및 오류 종류. 빈 결과와 빈 본문은 다릅니다.
- `summary.json`, `run_config.json`, `progress.sqlite3`: 통계, 입력/설정 해시, 재개 기록. sqlite 파일을 지우면 진행 상황도 사라집니다.

비정상 종료 시 SQLite에 완료된 청크별 결과는 유지되지만 JSONL 내보내기는 종료 시점에 갱신됩니다. 같은 명령을 다시 실행해 내보내세요. 원본 파일, 기사 본문, 출처 및 수집된 기업 ID를 보존하며 활용 가치나 중복으로 삭제하지 않습니다. 동일 ID가 중복되면 충돌 방지를 위해 중단합니다.

## 검증 범위

개체·관계 유형, 참조 방향, 키, 날짜, 근거가 청크의 연속 문자열인지 확인합니다. 문자열이 들어 있다는 사실은 관계가 의미상 옳다는 보장은 아닙니다. 사람의 원문 대조와 M5 정규화가 필요합니다. 제품·관계가 청크 경계에 걸리면 누락될 수 있습니다. 숫자 비교·의미 검증·완전 자동 중복 제거 및 AuraDB 적재는 포함하지 않습니다. `--chunk-size`는 문자 수이며 토큰 수가 아닙니다. 구조화 데이터는 별도 출처 검증 후 M6에서 매핑해야 합니다.

## 병렬 실행과 이어 하기

이 버전은 기존 `run_config.json` 및 `progress.sqlite3`를 유지하며 기본 3개 동시 요청을 실행합니다. `--workers 1`부터 `20`까지 지정할 수 있습니다. 속도와 제한은 계정마다 다르므로 3개부터 시험하세요. 예를 들어 기존 실행에서 이어서 처리하려면 기존과 **동일한 입력 경로·파일 내용, 모델, 청크 크기, system_prompt.txt, 출력 폴더**를 사용하고 명령 뒤에 `--workers 3`을 추가합니다. `--limit`은 이번 실행에서 요청할 청크 최대 개수이며 빼면 남은 청크 전체를 진행합니다. 기존 성공은 건너뛰고 실패는 `--retry-failed` 옵션을 넣어야 재시도합니다.

```powershell
uv run .\run_m4.py --companies .\companies.jsonl --company-info .\company_info.jsonl --financials .\financials.jsonl --news '.\news.jsonl' --output .\m4_output --model gpt-6.1-terra --workers 3
```

기존 실행 터미널을 Ctrl+C로 멈추고 종료한 다음 실행하세요. 같은 출력 폴더를 여러 프로세스에서 동시에 사용하면 안 됩니다. 기존 코드에서 `reasoning_effort`를 직접 변경했다면 기존 설정 기록에 추론 수준이 없어 자동 확인되지 않습니다. 기존 실행의 요청 설정을 확인하고 다르다면 결과를 섞지 않도록 별도 폴더를 쓰세요.

화면에 완료 건수·분당 처리량·예상 남은 시간이 나옵니다. 예상은 현재까지의 처리량 기준이라 오차가 큽니다. 일시적 속도 제한(429), 서버 오류 및 연결 오류는 기본 최대 3회 백오프로 재시도합니다(`--max-retries` 0~8). 재시도 소진·인증·권한·요금 소진 오류 시 신규 호출을 중단합니다. 이미 보낸 병렬 요청은 종료까지 기다리며 비용이 발생할 수 있습니다. Ctrl+C 후에도 진행 중 호출을 정리하는 동안 화면이 잠시 멈출 수 있습니다. 성공한 결과는 청크별 SQLite에 즉시 저장되고 종료시 JSONL도 갱신됩니다. 강제 종료되면 진행 중 응답이 저장되지 않을 수 있으며 해당 호출은 비용이 청구될 수 있습니다. 실제 API 및 과금/속도 제한 상황은 이 테스트 환경에서 검증하지 않았습니다.

`--reasoning-effort medium`이 기본이며 `--reasoning-effort high` 등으로 변경할 수 있습니다. 기존 코드의 설정을 유지해야 하며 과거 설정은 자동 판별 불가능합니다. 이 병렬 버전 첫 실행 이후에는 선택값을 별도 파일에 기록해 같은 출력 폴더에서 다른 수준을 차단합니다.
