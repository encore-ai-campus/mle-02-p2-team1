#!/usr/bin/env python3
"""4개 JSONL의 구조화 기록 변환 및 뉴스 청크별 LLM 추출. Neo4j에 쓰지 않음."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import random
import threading

ENTITY_TYPES = {'Company', 'CorporateGroup', 'Brand', 'Product', 'Person', 'Organization', 'Event', 'Market', 'Place', 'MetricObservation', 'Regulation', 'Character'}
RULES = {
    'HOLDS_POSITION': ({'Person'}, {'Company', 'Organization'}),
    'OWNS_STAKE': ({'Company', 'Person'}, {'Company'}),
    'PART_OF_GROUP': ({'Company'}, {'CorporateGroup'}),
    'OPERATES_BRAND': ({'Company'}, {'Brand'}),
    'PRODUCT_UNDER_BRAND': ({'Product'}, {'Brand'}),
    'PARTICIPATES_IN': ({'Company', 'CorporateGroup', 'Brand', 'Person', 'Organization'}, {'Event'}),
    'REPORTS_METRIC': ({'Company', 'CorporateGroup', 'Brand', 'Market', 'Product'}, {'MetricObservation'}),
    'MARKET_IN_PLACE': ({'Market'}, {'Place'}),
    'EVENT_IN_PLACE': ({'Event'}, {'Place'}),
    'PRODUCT_FEATURED_IN': ({'Product'}, {'Event'}),
    'EVENT_FEATURES': ({'Event'}, {'Character'}),
    'REGULATES': ({'Regulation'}, {'Product', 'Market'}),
}


def hash_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_jsonl(path):
    with path.open(encoding='utf-8-sig') as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{number}: 잘못된 JSON') from exc
            if not isinstance(item, dict):
                raise ValueError(f'{path}:{number}: 객체가 아닙니다')
            yield number, item


def split_chunks(text, size):
    # 원문을 변경하지 않고 연속 구간으로 자른다. 근거와 위치가 그대로 대응한다.
    pos = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        if end < len(text):
            boundary = text.rfind('\n\n', pos + size // 2, end)
            if boundary > pos:
                end = boundary + 2
        yield pos, end, text[pos:end]
        pos = end


def validate(result, doc_id, chunk_id, text):
    if not isinstance(result, dict) or set(result) != {'document_id', 'chunk_id', 'entities', 'relations'}:
        raise ValueError('최상위 키 불일치')
    if result['document_id'] != doc_id or result['chunk_id'] != chunk_id:
        raise ValueError('문서 또는 청크 ID 불일치')
    if not isinstance(result['entities'], list) or not isinstance(result['relations'], list):
        raise ValueError('entities/relations 배열 필요')
    entities = {}
    for entity in result['entities']:
        if not isinstance(entity, dict) or set(entity) != {'local_id', 'type', 'name', 'attributes'}:
            raise ValueError('개체 필드 오류')
        local_id, typ, name = entity['local_id'], entity['type'], entity['name']
        if not isinstance(local_id, str) or not local_id or local_id in entities or typ not in ENTITY_TYPES or not isinstance(name, str) or not name.strip():
            raise ValueError('개체 ID/유형/이름 오류')
        attrs = entity['attributes']
        if not isinstance(attrs, dict) or set(attrs) != {'metric_name', 'value_number', 'unit', 'period_text', 'market', 'is_forecast'}:
            raise ValueError('개체 속성 오류')
        for key in ('metric_name', 'unit', 'period_text', 'market'):
            if attrs[key] is not None and not isinstance(attrs[key], str):
                raise ValueError('개체 속성 문자열 오류')
        if attrs['value_number'] is not None and (isinstance(attrs['value_number'], bool) or not isinstance(attrs['value_number'], (int, float))):
            raise ValueError('개체 수치 오류')
        if attrs['is_forecast'] is not None and not isinstance(attrs['is_forecast'], bool):
            raise ValueError('예측 여부 오류')
        entities[local_id] = typ
    for relation in result['relations']:
        if not isinstance(relation, dict) or set(relation) != {'subject_id', 'predicate', 'object_id', 'attributes', 'evidence'}:
            raise ValueError('관계 필드 오류')
        s, p, o = relation['subject_id'], relation['predicate'], relation['object_id']
        if s not in entities or o not in entities or p not in RULES or entities[s] not in RULES[p][0] or entities[o] not in RULES[p][1]:
            raise ValueError('관계 참조 또는 방향 오류')
        a = relation['attributes']
        if not isinstance(a, dict) or set(a) != {'value_text', 'value_number', 'unit', 'status', 'event_date', 'as_of_date', 'valid_from', 'valid_to'} or a['status'] not in {'unknown','planned','ongoing','completed'}:
            raise ValueError('관계 속성 오류')
        for key in ('value_text', 'unit'):
            if a[key] is not None and not isinstance(a[key], str):
                raise ValueError('관계 속성 문자열 오류')
        if a['value_number'] is not None and (isinstance(a['value_number'], bool) or not isinstance(a['value_number'], (int, float))):
            raise ValueError('관계 수치 오류')
        for key in ('event_date','as_of_date','valid_from','valid_to'):
            if a[key] is not None:
                from datetime import date
                try:
                    if not isinstance(a[key], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', a[key]):
                        raise ValueError()
                    date.fromisoformat(a[key])
                except ValueError:
                    raise ValueError('날짜 형식 오류')
        ev = relation['evidence']
        if not isinstance(ev, dict) or set(ev) != {'quote'} or not isinstance(ev['quote'], str) or not ev['quote'].strip() or ev['quote'] not in text:
            raise ValueError('원문 근거 불일치')
    return result


def write_jsonl(path, rows):
    with path.open('w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def structured(inputs, out):
    records = {}
    for kind in ('companies','company_info','financials'):
        records[kind] = [row for _, row in read_jsonl(inputs[kind])]
        ids = [row.get('company_id') for row in records[kind]]
        if not all(isinstance(x, str) and x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError(f'{kind}: 누락되거나 중복된 company_id')
    ids = {x['company_id'] for x in records['companies']}
    if any({x['company_id'] for x in records[k]} != ids for k in ('company_info','financials')):
        raise ValueError('세 구조화 파일의 기업 ID 목록이 다릅니다')
    # 레코드 자체를 보존한다. 검증된 사실이나 확정 노드로 표시하지 않는다.
    write_jsonl(out / 'structured_candidates.jsonl', [
        {'record_type': kind, 'source_file': inputs[kind].name, 'record': row, 'review_status': '원출처_검토_필요'}
        for kind in records for row in records[kind]
    ])
    companies = {r['company_id']: r for r in records['companies']}
    info = {r['company_id']: r for r in records['company_info']}
    entities, relations = [], []
    for cid, company in companies.items():
        entities.append({'entity_id': cid, 'type': 'Company', 'name': company.get('legal_name') or company.get('input_name'), 'properties': {'dart_corp_code': company.get('dart_corp_code'), 'input_name': company.get('input_name'), **{k:v for k,v in info[cid].items() if k not in ('company_id','field_sources')}}, 'evidence': {'company_record': company, 'field_sources': info[cid].get('field_sources')}, 'review_status':'원출처_검토_필요'})
    for row in records['financials']:
        fid = row.get('financial_id')
        if not isinstance(fid, str) or not fid:
            raise ValueError('financial_id가 필요합니다')
        for field, label in (('revenue_krw','매출액'), ('operating_profit_krw','영업이익')):
            value = row.get(field)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'{fid}: {field} 숫자 오류')
            mid = fid + ':' + field
            entities.append({'entity_id':mid, 'type':'MetricObservation', 'name':label, 'properties': {'value_number':value, 'unit':'KRW', 'fiscal_year':row.get('fiscal_year'), 'period':row.get('period'), 'statement_scope':row.get('statement_scope')}, 'evidence': {'financial_id':fid, 'source':row.get('source'), 'source_field':field}, 'review_status':'원출처_검토_필요'})
            relations.append({'subject_id':row['company_id'], 'predicate':'REPORTS_METRIC', 'object_id':mid, 'evidence': {'financial_id':fid, 'source':row.get('source'), 'source_field':field}, 'review_status':'원출처_검토_필요'})
    write_jsonl(out/'structured_entities.jsonl', entities)
    write_jsonl(out/'structured_relations.jsonl', relations)
    return {k: len(v) for k, v in records.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('companies', 'company-info', 'financials', 'news'):
        parser.add_argument('--' + key, required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--model', required=True, help='접근 가능한 OpenAI API 모델명')
    parser.add_argument('--prompt', type=Path, default=Path(__file__).with_name('system_prompt.txt'))
    parser.add_argument('--chunk-size', type=int, default=2500)
    parser.add_argument('--limit', type=int, default=None, help='이번 실행에서 신규 시도할 최대 청크 수. 생략 시 전체')
    parser.add_argument('--retry-failed', action='store_true', help='이전 실패 청크도 재시도')
    parser.add_argument('--reasoning-effort', choices=['none','low','medium','high','xhigh','max'], default='medium', help='추론 수준, 기본 medium. 이전 실행 설정과 일치시켜야 합니다')
    parser.add_argument('--workers', type=int, default=3, help='동시 요청 수 (1~20, 기본 3)')
    parser.add_argument('--max-retries', type=int, default=3, help='일시 오류 재시도 횟수 (0~8)')
    args = parser.parse_args()
    if not 1 <= args.workers <= 20 or not 0 <= args.max_retries <= 8:
        parser.error('workers는 1~20, max-retries는 0~8이어야 합니다')
    if args.chunk_size < 200 or (args.limit is not None and args.limit < 1):
        parser.error('chunk-size는 200 이상, limit는 1 이상이어야 합니다')
    inputs = {'companies': args.companies, 'company_info': args.company_info, 'financials': args.financials, 'news': args.news}
    for path in inputs.values():
        if not path.is_file():
            parser.error(f'입력 파일 없음: {path}')
    if not os.getenv('OPENAI_API_KEY'):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
    if not os.getenv('OPENAI_API_KEY'):
        parser.error('OPENAI_API_KEY를 환경 변수 또는 .env에 설정하세요')
    try:
        from openai import OpenAI
    except ImportError:
        parser.error('openai 패키지가 필요합니다. uv add openai python-dotenv')
    prompt = args.prompt.read_text(encoding='utf-8')
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    # 실행 설정·입력 파일을 해시해 다른 입력/프롬프트로 기존 작업을 이어 쓰지 않는다.
    config = {'input_hashes': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k,p in inputs.items()}, 'prompt_hash': hash_text(prompt), 'chunk_size': args.chunk_size, 'model': args.model, 'version': 1}
    config_path = out / 'run_config.json'
    if config_path.exists() and json.loads(config_path.read_text(encoding='utf-8')) != config:
        raise ValueError('입력·모델·프롬프트·청크 설정이 기존 실행과 다릅니다. 새 출력 폴더를 사용하세요.')
    effort_path = out / 'reasoning_effort_parallel.txt'
    if effort_path.exists() and effort_path.read_text(encoding='utf-8').strip() != args.reasoning_effort:
        raise ValueError('이 폴더의 병렬 실행 추론 수준이 다릅니다. 새 출력 폴더를 사용하세요.')
    if config_path.exists() and not effort_path.exists():
        print('주의: 이전 코드의 추론 수준은 기록되지 않아 자동 확인할 수 없습니다. 이전 실행과 동일한지 확인하세요.', flush=True)
    effort_path.write_text(args.reasoning_effort + '\n', encoding='utf-8')
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    structured_counts = structured(inputs, out)
    db = sqlite3.connect(out / 'progress.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS chunks (chunk_id TEXT PRIMARY KEY, doc_id TEXT, payload TEXT, status TEXT, result TEXT, error TEXT)')
    # 중복 ID는 서로 다른 본문이 합쳐질 수 있어 사전에 중단한다.
    news = list(read_jsonl(inputs['news']))
    doc_ids = [x.get('document_id') for _, x in news]
    if not all(isinstance(x, str) and x for x in doc_ids) or len(set(doc_ids)) != len(doc_ids):
        raise ValueError('뉴스 document_id 누락 또는 중복: 원본을 먼저 확인하세요')
    pending = 0
    for row_no, record in news:
        text = record.get('content')
        if not isinstance(text, str):
            raise ValueError(f'뉴스 {row_no}행의 content가 문자열이 아닙니다')
        pieces = list(split_chunks(text, args.chunk_size)) if text.strip() else [(0, len(text), text)]
        for index, (start, end, piece) in enumerate(pieces, 1):
            doc_id = record['document_id']
            cid = f'{doc_id}-C{index:05d}'
            payload = {'document_id': doc_id, 'chunk_id': cid, 'primary_text': piece, 'metadata': {'title': record.get('title'), 'source_url': record.get('original_url'), 'published_at': record.get('published_at'), 'company_ids': record.get('company_ids'), 'source_row': row_no, 'char_start': start, 'char_end': end}}
            state = 'pending' if piece.strip() else 'empty'
            db.execute('INSERT OR IGNORE INTO chunks VALUES (?, ?, ?, ?, NULL, NULL)', (cid, doc_id, json.dumps(payload, ensure_ascii=False), state))
    db.commit()
    # SDK 자체 재시도는 끄고, 아래의 제한된 재시도만 사용한다.
    client = OpenAI(max_retries=0, timeout=90.0)
    query = "SELECT chunk_id,doc_id,payload FROM chunks WHERE status='pending'" + (" OR status='failed'" if args.retry_failed else '') + ' ORDER BY rowid'
    rows = db.execute(query).fetchall()
    if args.limit:
        rows = rows[:args.limit]
    stop_event = threading.Event()

    def call_one(row):
        cid, did, payload_text = row
        payload = json.loads(payload_text)
        for attempt in range(args.max_retries + 1):
            if stop_event.is_set():
                return 'cancelled', None, None
            try:
                response = client.chat.completions.create(
                    model=args.model, reasoning_effort=args.reasoning_effort, response_format={'type':'json_object'},
                    messages=[{'role':'system','content':prompt}, {'role':'user','content':json.dumps(payload,ensure_ascii=False)}])
                content = response.choices[0].message.content
                return 'success', validate(json.loads(content), did, cid, payload['primary_text']), None
            except Exception as exc:
                status = getattr(exc, 'status_code', None)
                code = getattr(exc, 'code', None)
                # 할당량/결제 소진은 일시적인 요청 제한과 다르다.
                fatal = status in (401, 403) or code in ('insufficient_quota', 'billing_hard_limit_reached')
                if fatal:
                    stop_event.set()
                    return 'fatal', None, type(exc).__name__ + (':' + str(code) if code else '')
                transient = status == 429 or (isinstance(status, int) and 500 <= status < 600) or type(exc).__name__ in ('APIConnectionError', 'APITimeoutError', 'TimeoutError')
                if transient and attempt < args.max_retries:
                    delay = min(30.0, 2 ** attempt + random.uniform(0, 1))
                    if stop_event.wait(delay):
                        return 'cancelled', None, None
                    continue
                if transient:
                    stop_event.set()
                    return 'fatal', None, type(exc).__name__
                return 'failed', None, type(exc).__name__

    start = time.monotonic()
    completed = 0
    position = 0
    active = {}
    interrupted = False
    pool = ThreadPoolExecutor(max_workers=args.workers)
    try:
        while position < len(rows) or active:
            while not stop_event.is_set() and position < len(rows) and len(active) < args.workers:
                row = rows[position]
                active[pool.submit(call_one, row)] = row
                position += 1
            if not active:
                break
            done, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                cid, did, payload_text = active.pop(future)
                state, result, error = future.result()
                if state == 'success':
                    db.execute('UPDATE chunks SET status=?,result=?,error=NULL WHERE chunk_id=?', ('success', json.dumps(result, ensure_ascii=False), cid))
                elif state in ('failed', 'fatal'):
                    db.execute('UPDATE chunks SET status=?,result=NULL,error=? WHERE chunk_id=?', ('failed', error, cid))
                db.commit()
                completed += 1
                elapsed = time.monotonic() - start
                speed = completed / elapsed * 60 if elapsed else 0
                eta = (len(rows)-completed)/speed if speed else 0
                print(f'[{completed}/{len(rows)}] {cid}: {state} | 분당 {speed:.1f}개 | 남은 시간 약 {eta:.1f}분', flush=True)
            if stop_event.is_set():
                print('인증·권한·할당량 또는 일시 오류 재시도 소진으로 신규 요청을 중단합니다. 이미 시작된 요청은 처리합니다.', flush=True)
    except KeyboardInterrupt:
        interrupted = True
        stop_event.set()
        print('중단 요청: 이미 완료된 결과는 저장되었습니다. 진행 중 요청 종료까지 기다립니다.', flush=True)
    finally:
        # 이미 성공했으나 메인 스레드가 아직 수집하지 않은 결과를 저장한다.
        pool.shutdown(wait=True, cancel_futures=True)
        for future, (cid, _, _) in active.items():
            if future.cancelled():
                continue
            state, result, error = future.result()
            if state == 'success':
                db.execute('UPDATE chunks SET status=?,result=?,error=NULL WHERE chunk_id=?', ('success', json.dumps(result, ensure_ascii=False), cid))
            elif state in ('failed', 'fatal'):
                db.execute('UPDATE chunks SET status=?,result=NULL,error=? WHERE chunk_id=?', ('failed', error, cid))
            db.commit()
    # 재실행할 때 전체 누적 상태를 다시 내보낸다.
    all_rows = db.execute('SELECT payload,status,result,error FROM chunks ORDER BY rowid').fetchall()
    write_jsonl(out/'chunks.jsonl', (json.loads(p) for p,_,_,_ in all_rows))
    write_jsonl(out/'extractions.jsonl', ({'input': json.loads(p), 'output':json.loads(r)} for p,s,r,e in all_rows if s=='success'))
    write_jsonl(out/'status.jsonl', ({'document_id':json.loads(p)['document_id'],'chunk_id':json.loads(p)['chunk_id'],'status':s,'error_type':e} for p,s,r,e in all_rows))
    counts = {s: sum(row[1] == s for row in all_rows) for s in ('success','failed','pending','empty')}
    (out/'summary.json').write_text(json.dumps({'structured_counts':structured_counts,'news_documents':len(news),'news_chunks':len(all_rows),'status_counts':counts,'model':args.model},ensure_ascii=False,indent=2),encoding='utf-8')
    db.close()
    print(json.dumps(counts,ensure_ascii=False))
    if interrupted or stop_event.is_set():
        raise SystemExit(1)

if __name__ == '__main__':
    main()
