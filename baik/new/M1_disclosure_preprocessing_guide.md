# M1 추가 보고서 · 공시 전처리 코드와 전후 예시

> **특정 산업 분야의 기업 조사 업무를 지원하는 지식그래프 구축**  
> M1 보충 자료: 공시의 종속기업 표와 주석 처리

| 항목 | 내용 |
| --- | --- |
| 단계 | M1 · 공시 표 전처리, 후속 추출·정규화 연계 |
| 작성일 | 2026-11-07 |
| 처리 자료 | 아모레퍼시픽홀딩스의 2025년 사업보고서와 2026년 1분기 보고서 |
| 범위 | 전체 문서가 아닌 종속기업 현황 표와 지분율 관련 주석 |
| 관련 산출물 | [공시 원문·실행 코드·JSONL 결과 ZIP](https://chatgpt.com/library?file_id=libfile_647b2155d8ac819189e30c31022710cf&account_id=572db941-93e9-4f5f-a926-7a495084b755) |

## 1. 무엇을 한 작업인가?

공시 원문은 웹 문서인 HTML 형식이고, 투자회사·피투자회사·지분율은 표 안에 들어 있다. 이 표에서 시범 대상 기업과 관련된 행을 찾아 **한 행씩 읽기 쉬운 텍스트와 JSONL로 정리**했다.

같은 프로그램에서 전처리한 표를 바탕으로 기업 식별자와 지분 관계도 만들었기 때문에 결과를 세 단계로 구분해서 읽는다.

1. **M1 전처리:** 원문 HTML에서 표·행·주석을 읽고 문서 ID, 기준일, 원문 위치를 붙인다.
2. **관계 추출:** 투자회사 → 지분 보유 → 피투자회사와 지분율을 기록한다.
3. **M5 정규화:** 대상 기업을 대표 회사 ID에 맞춘다. 기사에서 추출된 별도 회사 ID와의 병합은 검토 후보로 남긴다.

이 작업은 **규칙 기반 코드**로 진행했다. 표를 읽기 위해 LLM API를 호출하지 않았다. 코드에서 표 위치와 내용을 선택하므로, 다른 형태의 보고서에 그대로 적용할 수 있다고 보장하지 않는다.

## 2. 처리한 공시 원문

| 문서 ID | 보고서 | 제출일 | 지분 관측 기준일 |
| --- | --- | --- | --- |
| `APH-2025-ANNUAL` | [홀딩스 2025년 사업보고서](https://kind.krx.co.kr/external/2026/03/18/001082/20260318005107/11011.htm) | 2026-03-18 | 2025-12-31 |
| `APH-2026-Q1` | [홀딩스 2026년 1분기 보고서](https://kind.krx.co.kr/external/2026/05/15/001430/20260515003119/11013.htm) | 2026-05-15 | 2026-03-31 |

대상은 각 보고서의 **연결재무제표 주석 → 1.2 종속기업의 현황**이다. 해당 표의 첫 행에는 투자회사, 피투자회사, 업종, 지분율, 결산일, 소재국이 기재되어 있다.

## 3. 전처리 전후 예시

### 전처리 전: 공시 HTML 표의 한 행

아래는 2026년 1분기 원문의 해당 표 행을 읽은 모습이다. `<tr>`은 표의 한 행, `<td>`는 각 칸이다.

```html
<tr>
  <td>㈜아모레퍼시픽홀딩스</td>
  <td>㈜아모레퍼시픽(*1)</td>
  <td>화장품 제조 및 판매</td>
  <td>38.1</td>
  <td>12월 31일</td>
  <td>대한민국</td>
</tr>
```

실제 원문에는 화면 표시를 위한 `width`, `style` 등의 HTML 속성도 들어 있다. 위 예시는 **내용을 보기 쉽게 해당 속성만 생략**한 것이다. `(*1)`은 지배력에 대한 원문 주석 표시다.

### 전처리 후: 표 행 청크

프로그램은 표의 내용을 그대로 순서대로 읽어 `text`로 만들고, 원문으로 돌아갈 수 있는 정보를 덧붙인다.

```json
{
  "document_id": "APH-2026-Q1",
  "chunk_id": "APH-2026-Q1-COMPANY-AMOREPACIFIC",
  "as_of_date": "2026-03-31",
  "section": "연결재무제표 주석 1.2 종속기업의 현황",
  "header": ["투자회사", "피투자회사", "업 종", "지분율(%)", "결산일", "소재국"],
  "text": "㈜아모레퍼시픽홀딩스 | ㈜아모레퍼시픽(*1) | 화장품 제조 및 판매 | 38.1 | 12월 31일 | 대한민국",
  "source_xpath": "/html/body/table[133]/tbody/tr/td/table[2]/tbody/tr[1]",
  "source_url": "https://kind.krx.co.kr/external/2026/05/15/001430/20260515003119/11013.htm"
}
```

`source_xpath`는 원본 HTML 안에서 해당 행을 찾는 위치다. `text` 안의 **12월 31일은 피투자회사 결산일**이고, 이 보고서의 지분 관측 기준일은 별도 `as_of_date`인 **2026년 3월 31일**이다.

### 후속 추출·정규화 결과 예시

전처리한 행에서 투자회사와 피투자회사를 식별하고 다음 관계를 만들었다. 아래는 **주요 필드만 보여주는 발췌**다.

```json
{
  "subject_id": "COMPANY-AMOREPACIFIC-HOLDINGS",
  "predicate": "OWNS_STAKE",
  "object_id": "COMPANY-AMOREPACIFIC",
  "value_number": 38.1,
  "unit": "%",
  "as_of_date": "2026-03-31",
  "source_document_id": "APH-2026-Q1",
  "review_status": "공시표_대조완료_적재전_스키마검토필요"
}
```

전체 관계 파일에는 근거 문장, 청크 ID와 지분율 해석상의 주의점이 추가되어 있다. 보고서의 `(*1)` 주석도 별도 청크로 보존했다. 주석에는 의결권 있는 지분이 과반 미만이지만 **사실상 지배력이 있다고 판단**했다는 내용이 있다.

## 4. 전체 처리 순서

| 순서 | 처리 내용 | 결과 |
| ---: | --- | --- |
| 1 | 두 HTML 원문과 보고서별 기준일·출처 정의 | 문서 목록 후보 |
| 2 | `lxml`로 HTML 표를 읽고 종속기업 현황 표 선택 | 표와 열 제목 |
| 3 | 투자회사·피투자회사가 대상 범위인 행 선택 | 보고서당 7행 |
| 4 | 행을 텍스트로 만들고 문서 ID·청크 ID·XPath 기록 | 표 행 청크 14건 |
| 5 | 지배력과 지분율 기준에 관한 주석 문단 저장 | 주석 청크 4건 |
| 6 | 회사 ID와 지분 관계 후보 생성 | 회사 8개, 시점별 관계 14건 |
| 7 | 기사 회사 ID와 대표 회사 ID의 연결을 검토 후보로 기록 | 동일 법인 매핑 검토 6건 |

## 5. 실제 코드 읽는 방법

아래는 실행 코드의 핵심 부분과 역할이다. **실제 사용한 전체 코드**는 이 문서 8절에 그대로 수록했다.

### HTML을 읽고 표를 찾는 부분

```python
# 공시 HTML 파일을 읽어 구조를 해석합니다.
tree = html.parse(str(path))

# 문서에 들어 있는 모든 표를 순서대로 살펴봅니다.
for table in tree.xpath('//table'):
    # 표 안의 행과, 각 행에 들어 있는 칸을 읽습니다.
    trs = table.xpath('.//tr')
    rows = [[compact(c) for c in tr.xpath('./th|./td')] for tr in trs]
```

실제 코드는 첫 행의 `투자회사`·`피투자회사`와 퍼시픽테크 관련 조건이 맞는 표를 후보로 잡고 **첫 번째 후보**를 사용해. 따라서 다른 보고서에 비슷한 표가 여러 개 있으면 잘못된 표가 선택될 수 있어. 새 보고서에 사용할 때는 반드시 원문과 결과를 다시 대조해야 해.

### 기업명을 정리해 대상 행을 고르는 부분

```python
def identify(text):
    # 회사명 뒤의 주석 표시를 제거하고 법인 표기를 정리합니다.
    text = re.sub(r'\(\*\d+\)', '', text).strip()
    text = text.replace('㈜', '').replace('(주)', '').strip()

    # 미리 정한 기업 목록에 있는 이름만 반환합니다.
    return text if text in COMPANIES else None
```

이 함수는 이름을 찾기 위한 보조 작업이다. **이름만 같다고 모든 기사 노드를 자동 병합하지 않는다.** 본문 문맥과 법인 식별 정보의 추가 확인이 필요하다.

### 원문 위치와 전처리 결과를 기록하는 부분

```python
# 원본 HTML에서 현재 행의 위치를 기록합니다.
row_path = tree.getpath(trs[i])

# 표의 각 칸을 순서대로 이어 읽기 쉬운 문자열로 만듭니다.
text = ' | '.join(row)

# 문서 ID, 청크 ID, 기준일, 표 제목, 원문 위치와 URL을 함께 보존합니다.
chunk = {
    'document_id': source['id'],
    'chunk_id': chunk_id,
    'as_of_date': source['as_of'],
    'section': '연결재무제표 주석 1.2 종속기업의 현황',
    'header': rows[0],
    'text': text,
    'source_xpath': row_path,
    'source_url': source['url'],
}
```

## 6. 실행 방법

1. [공시 작업 ZIP](https://chatgpt.com/library?file_id=libfile_647b2155d8ac819189e30c31022710cf&account_id=572db941-93e9-4f5f-a926-7a495084b755)을 내려받아 별도 폴더에 압축을 푼다.
2. 압축 안의 `ownership_evidence_package` 폴더에서 PowerShell을 연다.
3. 아래 명령어를 실행한다.

```powershell
uv run --with lxml python .\build.py
```

정상 실행 시 문서 2건, 근거 청크 18건, 회사 8개, 관계 14건, 매핑 검토 6건이 출력된다. `lxml`은 HTML 문서 구조를 읽기 위한 파이썬 패키지다.

**주의:** 실행 코드는 같은 폴더의 `results` 파일을 다시 작성한다. 기존 결과를 보존하려면 먼저 압축을 새 폴더에 풀거나 `results`를 별도 복사한다. 이 코드는 AuraDB에 접속하거나 적재하지 않는다.

## 7. 결과 파일과 검토 사항

| 파일 | 내용 |
| --- | --- |
| `results/documents.jsonl` | 두 보고서의 ID, URL, 제출일, 기준일, 해시, 표 위치 |
| `results/chunks.jsonl` | 표 행 14건과 주석 4건 |
| `results/entities.jsonl` | 회사 8개의 대표 ID 또는 신규 제안 ID |
| `results/relations.jsonl` | 시점별 지분 관계 14건 |
| `results/relations.csv` | 관계 결과를 표로 확인하는 파일 |
| `results/identity_crosswalk_review.jsonl` | 기존 기사 회사 ID와 대표 ID의 연결 검토 후보 |
| `review_issues.md` | 공시와 기사 관계 충돌, 날짜 및 ID 확인 사항 |

14건은 **서로 다른 14개 기업 관계가 아니라, 7개 관계를 두 기준일에 관측한 결과**다. 홀딩스의 ID는 신규 제안 상태이므로 기존 홀딩스 개체와의 동일성 확인이 필요하다.

이니스프리 90.4%에는 자기주식 제외 실질지분율에 관한 보고서 주석이 있으므로 명목 지분율로 단정하지 않는다. 기사에서 추출된 퍼시픽테크 관계와 공시 표의 투자회사에는 차이가 있어 검토 대상으로 분리했다. 2026년 3월 이후 변동 여부는 이 자료만으로 확정하지 않는다.

## 8. 실제 사용한 전체 코드

아래 코드는 산출물 ZIP의 `build.py`를 그대로 수록한 것이다. 파일 경로와 입력 자료 구성은 ZIP 기준이다. 변수 설명과 단계별 역할은 앞의 4~7절을 함께 참고한다.

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
