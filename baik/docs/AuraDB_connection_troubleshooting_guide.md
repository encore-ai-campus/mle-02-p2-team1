# Neo4j AuraDB 연결 오류 해결 및 학습 가이드

> Windows · PowerShell · Python · uv 환경에서 발생한 실제 사례  
> 작성 기준: 2026년 11월 6일  
> 대상: AuraDB에 Python으로 연결하거나 팀 프로젝트의 데이터를 시험 적재하는 팀원

## 빠른 요약: 발생한 문제와 해결 방법

**문제:** `uv run .\check_aura.py`를 실행해 AuraDB 연결을 확인했을 때 아래 오류가 출력됐다. 처음 표시된 라우팅 오류의 안쪽에 있는 인증서 오류가 문제를 파악하는 단서였다.

```text
Unable to retrieve routing information
...
CERTIFICATE_VERIFY_FAILED
self-signed certificate in certificate chain
```

이는 Python이 기본 인증서 설정으로 서버가 보낸 인증서 체인을 신뢰할 수 있는지 확인하지 못했다는 뜻이다. TCP 포트 연결은 성공했지만 그다음 TLS 인증서 검증에서 실패했다. 정확히 어떤 인증서가 누락되었는지 또는 왜 기본 설정에서 실패했는지는 확인되지 않았다.

**해결:** PowerShell에서 `certifi`가 제공하는 신뢰 인증서 목록의 경로를 지정한 뒤 연결을 확인했다. 인증서 검증은 계속 수행하며, `neo4j+s://` 주소도 그대로 사용한다.

```powershell
# 현재 PowerShell 창에 인증서 경로를 설정한다.
$env:SSL_CERT_FILE = (uv run --with certifi python -c "import certifi; print(certifi.where())")

# 설정한 인증서 파일이 있는지 확인한다. True여야 한다.
Test-Path $env:SSL_CERT_FILE

# AuraDB 연결만 확인한다. 데이터를 적재하지 않는다.
uv run .\check_aura.py
```

첫 번째 명령의 `--with certifi`는 인증서 파일 위치를 찾을 때 사용한다. 경로가 유효하고 연결 코드가 해당 환경 변수를 사용한다면, 두 번째 명령에는 `--with certifi`가 필요하지 않다. **실제 사례에서는 연결 확인 시 `uv run --with certifi .\check_aura.py`를 사용해 성공했으며**, `--with certifi` 없이 실행하는 위 명령은 같은 설정을 사용하는 방식으로 설명한 것이고 별도로 성공 결과를 받은 것은 아니다.

**적용 범위:** 환경 변수는 현재 PowerShell 창에만 유지된다. 같은 창에서 계속 작업할 때는 보통 다시 설정하지 않아도 된다. 창을 닫고 새 창을 열거나 컴퓨터를 다시 켠 후에는 첫 번째 명령을 다시 실행한다. `uv` 캐시 정리 등으로 파일이 없어져도 다시 설정한다.

**적재:** 같은 창에서 인증서 경로가 유효하다면 `uv run .\load_trial.py`로 실행할 수 있다. 연결 확인은 별도로 필요할 때 수행하며 매번 필수는 아니다. 단, 적재는 데이터를 변경한다. 이번 시험은 이미 노드 8개·관계 3개를 적재했으며, 재실행 시 중복 방지는 확인되지 않았다.

**실제 확인 결과:** `certifi` 인증서 검증 성공 → AuraDB 연결 성공 → 시험 데이터 노드 8개와 관계 3개 적재·조회 성공. `routing information` 오류의 원인은 사례마다 다를 수 있으므로, 아래 상세 절차에서 가장 안쪽 오류를 확인한다.

---

## 1. 먼저 읽어 보기

이번 사례에서는 AuraDB 인스턴스가 실행 중이고 네트워크 포트도 열려 있었지만, Python에서 다음 오류가 발생했다.

```text
Unable to retrieve routing information
```

오류 내용을 더 깊게 확인하니 진짜 원인을 알려 주는 메시지가 있었다.

```text
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
self-signed certificate in certificate chain
```

**확인된 사실:** Python 기본 인증서 설정으로는 인증서 검증에 실패했지만, `certifi` 인증서 목록으로 검증했을 때 성공했다. 이후 같은 인증서 목록을 사용해 AuraDB 연결에도 성공했고, 시험 데이터 **노드 8개와 관계 3개**를 적재하고 조회했다.

**아직 확정되지 않은 것:** 기본 인증서 검증이 실패한 정확한 이유다. 특정 루트 인증서 누락, 중간 인증서 문제, PC 보안 프로그램 등 어느 하나가 원인이라고 확정할 근거는 없다. `self-signed certificate in certificate chain`이라는 오류도 어떤 특정 프로그램이 개입했다는 증거는 아니다.

> 같은 `Unable to retrieve routing information`이라도 인증, DNS, 네트워크, TLS 등 원인이 다를 수 있다. 반드시 가장 안쪽의 오류를 먼저 확인한다.

## 2. 연결 과정을 쉽게 이해하기

아파트에 들어가는 상황으로 생각해 보자.

1. **주소 확인:** 어느 아파트로 가야 할지 확인한다. → AuraDB URI와 DNS 확인
2. **입구 도착:** 아파트 입구까지 도착한다. → 서버의 7687 포트에 TCP 연결
3. **신원 확인:** 정식 출입구인지 인증서를 검증한다. → TLS 인증서 검증
4. **계정 확인:** 출입 권한이 있는지 확인한다. → AuraDB 인증 및 연결 확인
5. **업무 수행:** 방에 들어가 요청한 일을 처리한다. → Cypher 실행 및 데이터 적재

이 그림은 이해를 위한 단순화다. 실제 드라이버는 라우팅 정보 확인 등 내부 과정을 거친다. **TCP 포트가 열려 있어도 그 뒤의 TLS 인증서 검증에서 실패할 수 있다.**

| 용어 | 쉬운 설명 | 이번 사례 |
|---|---|---|
| URI | AuraDB에 연결할 주소 | `neo4j+s://`로 시작하는 주소가 콘솔과 일치 |
| 포트 7687 | Neo4j 드라이버의 연결 통로 | TCP 연결 성공 |
| TLS | 통신을 암호화하고 연결 상대를 확인하는 방식 | 인증서 검증 실패 후 해결 |
| 인증서 체인 | 서버 인증서부터 신뢰하는 인증기관까지 이어지는 검증 관계 | 기본 설정에서 검증 실패 |
| CA | 인증서를 발급하거나 신뢰의 기준이 되는 인증기관 | 신뢰할 CA 목록이 검증에 사용됨 |
| `certifi` | 공개 CA 인증서 묶음을 제공하는 Python 패키지 | 이 목록으로 인증서 검증 성공 |
| 라우팅 정보 | 드라이버가 데이터베이스 요청을 보낼 서버를 알아내는 데 쓰는 정보 | 정보를 얻기 전 TLS 단계에서 실패 |

`neo4j+s://`는 암호화와 인증서 검증을 사용하는 연결 방식이다. 이 사례의 해결 과정에서는 이를 유지했다. [Neo4j 연결 설정 문서](https://neo4j.com/docs/python-manual/current/connect-advanced/)

## 3. 실제 사례의 흐름

| 순서 | 확인한 내용 | 실제 결과 | 의미 |
|---|---|---|---|
| 1 | Aura 콘솔의 인스턴스 | `RUNNING` | 인스턴스는 실행 중이었음. 클라이언트 연결 성공을 보장하지는 않음 |
| 2 | 환경 변수와 URI | URI·사용자명·비밀번호 설정됨, URI 일치 | 값이 존재하고 주소가 일치함. 비밀번호의 정확성까지 확인된 것은 아님 |
| 3 | `Test-NetConnection` | `TcpTestSucceeded : True` | 서버 7687 포트까지 TCP 연결 성공 |
| 4 | `check_aura.py` 오류 상세 | `CERTIFICATE_VERIFY_FAILED` | 인증서 검증 단계의 실패 확인 |
| 5 | 휴대폰 핫스팟 | 같은 인증서 오류 | 기존 Wi-Fi만의 문제일 가능성이 낮아짐. PC 또는 다른 공통 요인을 확정한 것은 아님 |
| 6 | Python 기본 인증서 설정 | 인증서 37개 로드, `SSL_CERT_FILE`·`SSL_CERT_DIR` 미설정 | 인증서가 아예 없는 상황은 아님. 개수만으로 필요한 인증서가 있는지 판정 불가 |
| 7 | 서버가 전달한 인증서 정보 | 대상 `neo4j.io`, 발급자 표시 | 내용을 읽은 것일 뿐, 당시 확인 방식은 검증을 건너뛰었으므로 신뢰성 증명은 아님 |
| 8 | `certifi`로 TLS 검증 | `CERTIFI TLS CHECK: SUCCESS` | 해당 환경에서 certifi 목록으로 인증서 검증 성공. 계정 연결은 아직 확인 전 |
| 9 | `SSL_CERT_FILE` 지정 후 연결 확인 | `AuraDB 연결 성공` | 드라이버 수준의 연결 확인 성공 |
| 10 | `load_trial.py` 실행 | 노드 8개·관계 3개 적재 및 조회 | 소규모 시험 데이터 적재 성공. 재적재 중복 방지는 이번에 시험하지 않음 |

## 4. 가장 먼저 따라 할 절차

### 4-1. 사전 준비

- Windows PowerShell과 `uv`가 있어야 한다.
- 팀 프로젝트를 내려받고, 프로젝트가 요구하는 `neo4j`, `python-dotenv` 등 의존성을 준비한다.
- Neo4j Aura 콘솔에 표시된 **본인 또는 팀 인스턴스의 Connection URI**를 사용한다. 아래 주소는 형식만 보여 주는 예시다.
- `.env`에는 팀에서 전달받은 실제 연결 정보를 넣는다. 비밀번호는 채팅, 문서, 화면 캡처, Git 저장소에 공유하지 않는다.

```dotenv
NEO4J_URI=neo4j+s://<인스턴스_ID>.databases.neo4j.io
NEO4J_USERNAME=<사용자명>
NEO4J_PASSWORD=<비밀번호>
```

꺾쇠를 포함한 예시를 그대로 사용하면 연결되지 않는다. `.env`는 `.gitignore`에 등록한다. 이미 Git에 올라간 비밀번호는 파일을 지우는 것만으로 충분하지 않을 수 있으므로 팀에 알리고 해당 인증 정보를 교체한다.

PowerShell에서 프로젝트의 스크립트가 있는 폴더로 이동한다. 아래는 **예시 경로**이므로 각자 PC에 맞게 바꾼다.

```powershell
cd C:\Users\<사용자명>\Desktop\<프로젝트폴더>\src\AuraDB_M6_trial
```

> 경로에 빈칸이 있으면 `cd "C:\경로 이름\AuraDB_M6_trial"`처럼 따옴표로 감싼다. `uv run`은 현재 프로젝트 위치에 따라 실행 환경이 달라질 수 있으므로 프로젝트 폴더에서 실행한다.

### 4-2. 에러의 가장 안쪽 확인

`check_aura.py`가 준비되어 있다면 먼저 실행한다.

```powershell
uv run .\check_aura.py
```

`Unable to retrieve routing information`만으로 인증서 문제라고 단정하지 않는다. 화면 아래쪽에 `CERTIFICATE_VERIFY_FAILED`와 `self-signed certificate in certificate chain`이 있는지 찾는다. 오류가 여러 단계로 묶일 수 있으므로 끝까지 확인한다.

`check_aura.py`가 없거나 상세 오류가 보이지 않으면 **7절의 연결 확인 코드**를 별도 파일로 만들어 사용한다.

### 4-3. 포트 연결 확인

Aura 콘솔의 URI가 `neo4j+s://abcd1234.databases.neo4j.io`라면 `neo4j+s://`를 빼고 호스트 이름만 사용한다.

```powershell
Test-NetConnection abcd1234.databases.neo4j.io -Port 7687
```

- `TcpTestSucceeded : True`: 해당 포트에 TCP 연결됨. 인증서·로그인·적재 성공을 의미하지는 않는다.
- `False`: 방화벽, 네트워크, 주소, 인스턴스 상태 등을 확인한다. 네트워크 관리자에게 문의할 수 있다.

### 4-4. `certifi` 인증서로 검증 시험

다음 코드를 **전체 복사해서 한 번에** PowerShell에 붙여 넣는다. `abcd1234`는 본인의 인스턴스 ID로 바꾼다. 문자열 시작의 `@'`와 끝의 `'@`는 PowerShell에 여러 줄의 Python 코드를 전달하기 위한 표기다.

```powershell
@'
# 서버와 TCP 연결을 만들기 위한 표준 라이브러리
import socket

# 인증서를 검증하며 암호화 연결을 만들기 위한 표준 라이브러리
import ssl

# 공개 인증기관의 인증서 묶음 경로를 제공하는 패키지
import certifi

# Neo4j Aura 콘솔에서 확인한 주소의 호스트 이름만 적는다.
# neo4j+s://는 적지 않는다.
host = "abcd1234.databases.neo4j.io"

# Neo4j 연결에 사용하는 기본 포트
port = 7687

try:
    # certifi의 CA 목록을 이용해 인증서 검증 설정을 만든다.
    # create_default_context는 서버 인증서 검증을 활성화한다.
    context = ssl.create_default_context(cafile=certifi.where())

    # 지정한 서버와 포트에 TCP 연결을 만든다.
    with socket.create_connection((host, port), timeout=10) as connection:
        # TLS를 적용하고 서버 이름과 인증서를 함께 검증한다.
        with context.wrap_socket(connection, server_hostname=host):
            # 여기까지 도착했다면 이 TLS 검증이 성공했다.
            print("CERTIFI TLS CHECK: SUCCESS")

except Exception as error:
    # 진단을 위해 오류 종류와 메시지를 출력한다.
    print("CERTIFI TLS CHECK: FAILED")
    print("ERROR TYPE:", type(error).__name__)
    print("ERROR:", error)
'@ | uv run --with certifi python -
```

이 코드는 **인증서 검증을 수행한다**. Neo4j 계정 정보를 사용하지 않으며, 데이터를 읽거나 쓰지 않는다. `uv run --with certifi`는 해당 실행에 필요한 패키지를 추가한다. 처음에는 다운로드가 필요할 수 있다. [uv 실행 문서](https://docs.astral.sh/uv/concepts/projects/run/)

| 결과 | 해석 및 다음 행동 |
|---|---|
| `SUCCESS` | 이 환경에서 `certifi`로 TLS 검증 성공. 다음 절의 드라이버 연결 확인을 진행한다. |
| `FAILED`와 인증서 오류 | 인증서 체인 또는 보안 환경을 추가 확인한다. 아래 해결법이 반드시 작동한다고 가정하지 않는다. |
| 연결 시간 초과 등 | 네트워크·포트·인스턴스 상태를 먼저 확인한다. |
| `certifi` 다운로드 오류 | 네트워크 또는 패키지 접근 환경을 확인한다. TLS 서버 검증 결과가 아니다. |

### 4-5. 현재 PowerShell 창에 인증서 경로 설정

위 TLS 시험이 성공한 경우, **같은 PowerShell 창에서** 아래 명령을 실행한다.

```powershell
$env:SSL_CERT_FILE = (uv run --with certifi python -c "import certifi; print(certifi.where())")
```

- `certifi.where()`는 인증서 묶음 파일의 경로를 반환한다.
- `$env:SSL_CERT_FILE`은 현재 PowerShell과 이 창에서 실행하는 자식 프로세스에 전달되는 환경 변수다.
- Python/OpenSSL이 기본 인증서를 찾을 때 참고하는 파일 경로를 지정한다.
- 현재 창에만 적용된다. 다른 창을 열면 다시 설정해야 한다.
- `uv` 캐시 정리 등으로 해당 경로가 사라질 수 있으므로 새 세션에서는 이 명령을 다시 실행한다.
- 명령이 실패했거나 경로가 비어 있다면 다음 단계로 진행하지 말고 오류를 확인한다.

설정한 파일이 존재하는지 확인한다. 이 명령은 경로의 존재 여부만 표시한다.

```powershell
Test-Path $env:SSL_CERT_FILE
```

`True`가 나오면 다음과 같이 실제 Neo4j 드라이버의 연결을 확인한다.

```powershell
uv run .\check_aura.py
```

인증서 경로가 유효하다면 이 명령에는 `--with certifi`가 필수는 아니다. 이번에 실제로 성공을 확인한 명령은 `uv run --with certifi .\check_aura.py`이며, 위 명령은 별도로 실행 결과를 확인하지 않았다. `AuraDB 연결 성공`이 나오면 연결 확인 단계는 끝이다. 이 결과는 `certifi`를 시스템 전체의 영구 해결책으로 설치했다는 뜻은 아니다. 이번 창에서 적용한 설정으로 연결이 성공한 것이다.

### 4-6. 시험 데이터 적재

**연결 확인만 할 때는 아래 명령을 실행하지 않는다.** 팀 프로젝트의 시험 데이터를 DB에 쓰기로 정한 경우에만 실행한다.

```powershell
uv run .\load_trial.py
```

인증서 경로를 같은 창에서 설정하고 파일이 유효하다면 `--with certifi` 없이 실행할 수 있다. 이번에 실제 적재 성공을 확인한 명령은 `uv run --with certifi .\load_trial.py`였다.

이 명령은 준비된 스크립트의 동작에 따라 데이터베이스를 변경한다. 실행 전 대상 인스턴스와 스크립트를 확인한다. 이 시험은 처음 적재를 위한 것이며, **반복 실행 시 안전성이나 중복 방지는 별도로 검증해야 한다.**

## 5. 이번 적재 결과와 경고 해석

이번 시험에서는 아래 결과가 출력됐다.

```text
AuraDB 연결 성공
적재 및 확인: 노드 8개, 관계 3개
```

| 출발 개체 | 관계 | 도착 개체 | 확인된 세부 정보 |
|---|---|---|---|
| 김승환 | `HOLDS_POSITION` | 아모레퍼시픽 | `position`: 대표이사 |
| 아모레퍼시픽 | `OWNS_STAKE` | 코스알엑스 | `number`: 93.2, `unit`: %, `status`: planned |
| 듀얼 리페어 리프트 M.D. 크림 미스트 | `PRODUCT_UNDER_BRAND` | 에이피 뷰티(AP BEAUTY) | 원문 근거 표시 |

세 관계의 조회 결과에는 `document_id`, `chunk_id`, `evidence`가 포함됐다. 즉, 해당 관계가 어느 문서의 어느 청크에서 어떤 문장에 근거했는지 추적할 수 있다. `planned`는 원문의 “보유하게 될 예정이다”를 반영한 상태로, 현재 지분율을 확정한 값으로 해석하지 않는다.

출력에는 COSRX 브랜드, AnyMind Group, Sun Smile이 독립 노드라고 표시됐다. 독립 노드는 적재되어 있지만 이번 시험에서 다른 노드와 연결된 관계가 없는 노드다.

초기 실행 시 다음과 유사한 경고가 있었다.

```text
warn: property key does not exist. The property `dataset_id` does not exist
warn: label does not exist. The label `M6Trial` does not exist
```

기존 시험 데이터를 세는 쿼리를 빈 데이터베이스에서 먼저 실행해, 해당 레이블과 속성이 아직 없는 상황과 일치한다. 실제 실행에서는 뒤이어 적재 및 확인이 성공했다. **경고가 언제나 무해한 것은 아니므로** 이후에도 같은 경고가 계속 발생하거나 기대 결과가 없으면 레이블·속성 이름과 쿼리를 확인한다.

### Aura 화면에서 보기

Aura 콘솔에서 인스턴스의 **Open** 메뉴를 통해 사용할 수 있는 Query 또는 Explore 도구를 연다. 화면 이름은 변경될 수 있다. 다음 Cypher는 시험 레이블이 붙은 노드와 그 사이의 관계를 조회한다.

```cypher
MATCH (n:M6Trial)
OPTIONAL MATCH (n)-[r]-(m:M6Trial)
RETURN n, r, m
```

- `MATCH (n:M6Trial)`: `M6Trial` 레이블이 있는 노드를 찾는다.
- `OPTIONAL MATCH`: 연결된 시험 노드가 없어도 `n`을 반환한다.
- `RETURN`: 찾은 노드와 관계를 표시한다.

이 쿼리는 읽기 전용이다. 시각화 UI에 따라 같은 관계가 여러 행에 표시될 수 있다. 정확한 수량은 적재 프로그램 결과나 별도의 집계 쿼리로 확인한다.

## 6. 연결 단계별 진단표

| 증상 | 우선 확인 | 주의할 점 |
|---|---|---|
| 인스턴스가 실행 중이 아님 | Aura 콘솔에서 상태와 해당 인스턴스 확인 | `RUNNING`이어도 모든 연결이 성공하는 것은 아님 |
| URI 누락 또는 불일치 | `.env` 변수 이름과 콘솔 URI 비교 | 값을 출력해 공유하기보다 일치 여부만 확인 |
| 포트 연결 실패 | 호스트, 7687 포트, 네트워크 정책 | 인증서 문제가 아니라 다른 단계에서 실패했을 수 있음 |
| `CERTIFICATE_VERIFY_FAILED` | 내부 오류와 인증서 경로, 4-4절 시험 | 인증서 검증을 끄지 않는다 |
| `Unauthorized` 등 인증 오류 | 계정, 비밀번호, 대상 인스턴스 | 비밀번호를 화면이나 채팅에 붙여 넣지 않는다 |
| 연결은 되지만 쓰기 실패 | DB 권한, Cypher, 스크립트 출력 | 연결 확인과 데이터 적재는 다른 작업 |
| 기대한 노드 수와 다름 | 대상 DB, 조건, 이전 데이터 및 스크립트 확인 | 임의로 삭제하거나 재실행하기 전에 원인 확인 |

## 7. 학습용 연결 확인 코드

아래 코드는 **연결만 확인**하는 독립 예시다. 파일 이름을 `check_aura_example.py`로 저장하고, `python-dotenv`와 Neo4j 드라이버가 프로젝트 환경에 설치돼 있는지 확인한다. 이미 팀의 `check_aura.py`가 있다면 굳이 덮어쓸 필요는 없다.

```python
# 운영체제 환경 변수에서 접속 정보를 읽는다.
import os

# 실패할 때 프로그램의 종료 코드를 지정한다.
import sys

# .env 파일에 정의된 값을 환경 변수로 불러온다.
from dotenv import load_dotenv

# Neo4j 데이터베이스에 연결하기 위한 공식 드라이버다.
from neo4j import GraphDatabase


# .env 파일을 찾아 환경 변수를 불러온다.
# 기본 설정에서는 이미 존재하는 환경 변수를 덮어쓰지 않는다.
load_dotenv()

# 실제 값은 출력하지 않고 프로그램 내부에서만 사용한다.
uri = os.getenv("NEO4J_URI")
username = os.getenv("NEO4J_USERNAME")
password = os.getenv("NEO4J_PASSWORD")

# 입력값이 비어 있으면 연결을 시도하기 전에 종료한다.
if not uri or not username or not password:
    print("연결 정보를 확인하세요: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD")
    sys.exit(1)

try:
    # with 문을 사용하면 작업이 끝났을 때 드라이버를 닫는다.
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        # 드라이버가 실제 서버에 연결할 수 있는지 확인한다.
        # 별도의 데이터 적재 Cypher는 실행하지 않는다.
        driver.verify_connectivity()

    # 오류 없이 검증이 끝났을 때만 성공을 출력한다.
    print("AuraDB 연결 성공")

except Exception as error:
    # 오류 종류를 표시한다. 비밀번호 값은 따로 출력하지 않는다.
    print("AuraDB 연결 실패")
    print("오류 종류:", type(error).__name__)
    print("오류 내용:", error)

    # 안쪽 원인이 있는 경우 확인한다.
    # ExceptionGroup의 개별 예외는 아래 재귀 함수에서 다룬다.
    def print_inner_errors(current_error, depth=1, seen=None):
        # 같은 예외를 반복해서 출력하는 것을 막기 위한 집합이다.
        if seen is None:
            seen = set()
        if id(current_error) in seen:
            return
        seen.add(id(current_error))

        # cause, context와 ExceptionGroup 내부 예외를 모은다.
        inner_errors = []
        if current_error.__cause__ is not None:
            inner_errors.append(current_error.__cause__)
        elif current_error.__context__ is not None:
            inner_errors.append(current_error.__context__)
        if isinstance(current_error, BaseExceptionGroup):
            inner_errors.extend(current_error.exceptions)

        # 각 내부 오류를 들여쓰기하여 순서대로 출력한다.
        for inner_error in inner_errors:
            indent = "  " * depth
            print(f"{indent}오류 종류: {type(inner_error).__name__}")
            print(f"{indent}오류 내용: {inner_error}")
            print_inner_errors(inner_error, depth + 1, seen)

    # 최상위 오류부터 내부 오류를 차례로 탐색한다.
    print_inner_errors(error)

    # 실패했음을 운영체제에 전달한다.
    sys.exit(1)
```

위 코드의 `BaseExceptionGroup`은 Python 3.11 이상에서 사용할 수 있다. 이번 프로젝트의 Python 버전은 3.12.14였다. 오류 출력에는 환경에 따라 주소 등 환경 정보가 포함될 수 있으므로 외부에 공유하기 전 검토한다.

```powershell
uv run .\check_aura_example.py
```

이 명령만으로 `SSL_CERT_FILE`이 자동 설정되는 것은 아니다. 기본 인증서 검증이 실패하는 경우 4-5절의 환경 변수 설정을 먼저 수행한다. `verify_connectivity()`는 쿼리 실행 없이 연결을 확인하는 공식 드라이버 기능이다. [Neo4j Python 연결 문서](https://neo4j.com/docs/python-manual/current/connect/)

## 8. 자주 묻는 질문

### Q1. `certifi`를 사용하면 인증서 검증을 끄는 건가?

아니다. 이번 방법은 신뢰할 인증기관 목록으로 `certifi`를 사용해 **검증을 수행**한다. `neo4j+s://`도 그대로 유지한다. 다만 이 방법이 조직의 보안 정책에 적합한지는 해당 환경의 관리자에게 확인해야 한다.

### Q2. `neo4j+ssc://`로 변경하면 안 되나?

`+ssc`는 신뢰할 인증서에 대한 검증 수준이 달라진다. 이 문제를 피하기 위해 무조건 변경하면 서버의 신원을 제대로 확인하지 못할 수 있다. 이번 사례에서는 `neo4j+s://`를 유지하며 해결했다. [Neo4j 드라이버 API](https://neo4j.com/docs/api/python-driver/current/api.html)

### Q3. 기본 인증서가 37개였는데 왜 실패했나?

인증서 **개수만으로** 필요한 신뢰 체인이 포함되어 있는지 알 수 없다. 이번에는 기본 설정과 certifi의 결과가 달랐다는 사실만 확인됐으며, 정확한 차이와 근본 원인은 추가 조사가 필요하다. Windows에서 Python은 기본 인증서를 불러올 때 시스템 저장소도 사용한다. [Python ssl 문서](https://docs.python.org/3/library/ssl.html#ssl.SSLContext.load_default_certs)

### Q4. PowerShell을 닫았다가 다시 열면?

현재 창에 설정한 `$env:SSL_CERT_FILE`은 유지되지 않는다. 프로젝트 폴더에서 4-5절의 경로 설정을 다시 실행한다. 다른 팀원 PC도 각자 설정하고 시험해야 한다.

### Q5. 팀 프로젝트에 영구 적용하려면?

먼저 팀의 운영 방식과 보안 정책에 맞춰 방법을 합의한다. 예를 들어 `certifi`를 프로젝트 의존성으로 고정하고, 실행 환경에서 올바른 CA 경로를 주입하는 방식을 검토할 수 있다. 이 경우 `pyproject.toml`과 `uv.lock` 변경, 배포·운영 환경, 기존 조직 인증서 요구사항을 함께 확인하고 재시험해야 한다. 이번 문서의 일시적인 PowerShell 설정은 그 결정의 대체물이 아니다.

### Q6. 시험 적재에 성공했으면 전체 자료를 넣을 수 있나?

소규모 데이터로 연결과 적재 가능성을 확인한 것이다. 전체 자료의 매핑 정확성, 출처 보존, 데이터 규모, 중복·재적재 및 오류 처리는 별도로 검증해야 한다.

### Q7. 출력에 `???`가 보인다.

PowerShell에서 여러 줄 코드를 Python으로 전달할 때 문자 인코딩 영향으로 한글이 깨질 수 있다. 진단 결과의 영문 오류와 수치를 확인하고, 필요하면 코드를 UTF-8로 저장한 `.py` 파일로 실행한다. 문자 깨짐 자체가 TLS 오류라는 뜻은 아니다.

## 9. 팀원용 빠른 점검 목록

- [ ] Aura 콘솔에서 대상 인스턴스가 실행 중인지 확인했다.
- [ ] `.env`의 변수 이름과 URI가 맞는지 확인했다. 비밀번호는 공유하지 않았다.
- [ ] `Test-NetConnection`으로 7687 포트를 확인했다.
- [ ] 가장 안쪽 오류가 인증서 검증 실패인지 확인했다.
- [ ] 인증서 문제가 맞다면 `certifi`로 검증 시험을 했다.
- [ ] 성공했다면 현재 PowerShell 창에 `SSL_CERT_FILE`을 설정하고 연결을 확인했다.
- [ ] 데이터 쓰기가 허용된 대상인지 확인하고 시험 적재를 실행했다.
- [ ] 적재 결과와 출처를 확인했다. 재적재 안전성은 별도 검증 대상으로 남겼다.

## 10. 참고 자료

- [Neo4j Python Driver: 연결하기](https://neo4j.com/docs/python-manual/current/connect/)
- [Neo4j Python Driver: 고급 연결 설정](https://neo4j.com/docs/python-manual/current/connect-advanced/)
- [Neo4j Python Driver API: TLS와 신뢰 인증서](https://neo4j.com/docs/api/python-driver/current/api.html)
- [Python 표준 라이브러리: ssl](https://docs.python.org/3/library/ssl.html)
- [uv: 프로젝트 명령 실행과 `--with`](https://docs.astral.sh/uv/concepts/projects/run/)
