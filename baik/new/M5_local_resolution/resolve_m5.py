#!/usr/bin/env python3
"""M4 뉴스·공시 결과의 보수적인 개체 정규화. LLM·DB 호출 없음."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path


# 기존 M4 코드에서 허용하는 서술어와 주어·목적어 유형이다.
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
ENTITY_TYPES = set().union(*(a | b for a, b in RULES.values()))


def digest(value: str) -> str:
    """같은 입력에서 동일한 식별자를 재현한다."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def file_hash(path: Path) -> str:
    """입력 파일이 바뀌었는지 추적한다."""
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def company_search_key(name: str) -> str:
    """회사의 표기 차이를 후보 검색에만 사용한다. 병합 근거가 아니다."""
    name = unicodedata.normalize('NFKC', name).casefold()
    name = re.sub(r'주식회사|\(\s*주\s*\)', '', name)
    return re.sub(r'\s+', '', name).strip()


class InputFiles:
    """압축 파일 또는 디렉터리의 JSONL을 압축 해제 없이 읽는다."""
    def __init__(self, path: Path):
        if not path.exists():
            raise ValueError(f'입력 경로가 없습니다: {path}')
        self.path = path
        self.archive = zipfile.ZipFile(path) if path.is_file() and zipfile.is_zipfile(path) else None
        if self.archive is None and not path.is_dir():
            raise ValueError(f'입력은 ZIP 파일 또는 폴더여야 합니다: {path}')

    @contextmanager
    def open(self, filename: str):
        # 서로 다른 경로에 동명 파일이 여러 개면 임의로 선택하지 않는다.
        if self.archive:
            matches = [n for n in self.archive.namelist() if not n.endswith('/') and Path(n).name == filename]
            if len(matches) != 1:
                raise ValueError(f'{self.path}: {filename} 파일 {len(matches)}개 발견. 정확히 1개여야 합니다.')
            import io
            with self.archive.open(matches[0]) as raw:
                with io.TextIOWrapper(raw, encoding='utf-8-sig') as text:
                    yield text
        else:
            matches = list(self.path.rglob(filename))
            if len(matches) != 1:
                raise ValueError(f'{self.path}: {filename} 파일 {len(matches)}개 발견. 정확히 1개여야 합니다.')
            with matches[0].open(encoding='utf-8-sig') as text:
                yield text

    def rows(self, filename: str):
        with self.open(filename) as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f'{filename}:{line_no}: JSON 오류: {error}') from error
                if not isinstance(value, dict):
                    raise ValueError(f'{filename}:{line_no}: JSON 객체가 필요합니다.')
                yield value

    def close(self):
        if self.archive:
            self.archive.close()


def read_decisions(path: Path | None) -> dict:
    """사람이 확인한 청크·개체별 결정만 읽는다. 빈 행은 무시한다."""
    if not path:
        return {}
    result = {}
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'chunk_id', 'local_id', 'representative_id', 'decision', 'note'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('검토 CSV에는 chunk_id,local_id,representative_id,decision,note 열이 필요합니다.')
        for row_no, row in enumerate(reader, 2):
            decision = (row.get('decision') or '').strip()
            if not decision:
                continue
            if decision != '승인':
                raise ValueError(f'검토 CSV {row_no}행: decision은 비워 두거나 승인으로 입력하세요.')
            key = ((row.get('chunk_id') or '').strip(), (row.get('local_id') or '').strip())
            rep = (row.get('representative_id') or '').strip()
            if not all(key) or not rep or key in result:
                raise ValueError(f'검토 CSV {row_no}행: 식별자 누락 또는 중복 결정입니다.')
            result[key] = {'representative_id': rep, 'decision': decision, 'note': (row.get('note') or '').strip()}
    return result


def put_canonical(nodes: dict, row: dict, source: str):
    """기준 개체를 보존한다. 같은 ID의 충돌은 무시하지 않는다."""
    eid, typ, name = row.get('entity_id'), row.get('type'), row.get('name')
    if not all(isinstance(x, str) and x.strip() for x in (eid, typ, name)):
        raise ValueError(f'{source}: 개체 ID·유형·이름이 필요합니다.')
    if eid in nodes:
        old = nodes[eid]
        if old['type'] != typ or old['name'] != name:
            raise ValueError(f'같은 ID의 개체 유형/이름이 충돌합니다: {eid}')
        # 기존 속성을 덮어쓰지 않고 공시의 원래 레코드도 유지한다.
        old['source_records'].append({'source': source, 'record': row})
    else:
        nodes[eid] = {'entity_id': eid, 'type': typ, 'name': name,
                      'source_records': [{'source': source, 'record': row}],
                      'identity_status': '입력_기준개체_원출처검토필요'}


def write_jsonl(path: Path, rows):
    with path.open('w', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def main():
    parser = argparse.ArgumentParser(description='뉴스 M4 결과와 공시 지분 결과를 규칙 기반으로 정규화합니다.')
    parser.add_argument('--m4', type=Path, required=True, help='M4 결과 ZIP 또는 결과 폴더')
    parser.add_argument('--companies', type=Path, required=True, help='7개 기업의 companies.jsonl')
    parser.add_argument('--disclosure', type=Path, required=True, help='공시 결과 ZIP 또는 결과 폴더')
    parser.add_argument('--output', type=Path, required=True, help='새 결과 폴더')
    parser.add_argument('--limit', type=int, default=None, help='시험할 뉴스 성공 청크 수. 생략하면 전체')
    parser.add_argument('--decisions', type=Path, default=None, help='사람이 검토해 승인한 CSV (선택)')
    parser.add_argument('--previous-m5', type=Path, default=None, help='기존 M5 결과 ZIP/폴더. 검토 상태를 유지하며 재사용 (선택)')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit은 1 이상이어야 합니다.')
    if not args.companies.is_file():
        parser.error('companies.jsonl 파일을 찾을 수 없습니다.')
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error('기존 결과 보존을 위해 비어 있는 새 출력 폴더를 지정하세요.')

    # CSV에서 승인된 결정만 사용한다. 파일 이름만 같다는 이유로 자동 병합하지 않는다.
    decisions = read_decisions(args.decisions)
    used_decisions = set()
    companies = []
    with args.companies.open(encoding='utf-8-sig') as handle:
        for line in handle:
            if line.strip():
                companies.append(json.loads(line))
    ids = [x.get('company_id') for x in companies]
    if not ids or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError('기업 ID가 없거나 중복됩니다.')

    m4, disclosure = InputFiles(args.m4), InputFiles(args.disclosure)
    previous = InputFiles(args.previous_m5) if args.previous_m5 else None
    try:
        canonical = {}
        for row in m4.rows('structured_entities.jsonl'):
            put_canonical(canonical, row, 'M4_structured')
        for row in disclosure.rows('entities.jsonl'):
            put_canonical(canonical, row, 'disclosure')
        # 기업 기준 파일과 M4의 대표 회사가 서로 일치하는지 확인한다.
        for company in companies:
            cid = company['company_id']
            node = canonical.get(cid)
            if not node or node['type'] != 'Company' or node['name'] != company.get('legal_name'):
                raise ValueError(f'기업 기준 파일과 구조화 회사 ID/법인명이 다릅니다: {cid}')
            node['source_records'].append({'source': 'companies.jsonl', 'record': company})

        # 후보 검색 대상은 회사 기준 개체뿐이다. Brand를 Company로 연결하지 않는다.
        company_index = {}
        for cid, node in canonical.items():
            if node['type'] == 'Company':
                aliases = [node['name']]
                for record in node['source_records']:
                    value = record['record']
                    aliases.extend([value.get('input_name'), value.get('legal_name')])
                for alias in aliases:
                    if isinstance(alias, str) and company_search_key(alias):
                        company_index.setdefault(company_search_key(alias), set()).add(cid)

        # 기존 M5 결과는 선택 사항이다. 원본 언급과 정확히 같은지 검사하고,
        # 기존의 자동·잠정 연결을 사람의 승인으로 바꾸지 않는다.
        previous_mentions, previous_nodes, previous_relations = {}, {}, {}
        if previous:
            for item in previous.rows('mentions_mapping.jsonl'):
                key = (item.get('chunk_id'), item.get('local_id'))
                if key in previous_mentions:
                    raise ValueError(f'기존 M5에 중복 언급이 있습니다: {key}')
                previous_mentions[key] = item
            for item in previous.rows('news_entities.jsonl'):
                key = item.get('entity_id')
                if not key or key in previous_nodes:
                    raise ValueError('기존 M5의 뉴스 개체 ID가 없거나 중복됩니다.')
                previous_nodes[key] = item
            for item in previous.rows('news_assertions.jsonl'):
                key = item.get('assertion_id')
                if not key or key in previous_relations:
                    raise ValueError('기존 M5 관계 ID가 없거나 중복됩니다.')
                previous_relations[key] = item

        # 원문·표 위치를 공시 관계와 결합한다. 기준일이 다른 행은 별개로 남긴다.
        docs = {x['id']: x for x in disclosure.rows('documents.jsonl')}
        chunks = {x['chunk_id']: x for x in disclosure.rows('chunks.jsonl')}
        base_relations = []
        for index, row in enumerate(m4.rows('structured_relations.jsonl'), 1):
            sid, oid = row.get('subject_id'), row.get('object_id')
            if sid not in canonical or oid not in canonical:
                raise ValueError(f'구조화 관계의 개체 ID를 찾을 수 없습니다: {sid}, {oid}')
            base_relations.append({'relation_id': f'STRUCTURED-{index:06d}', 'subject_id': sid,
                'predicate': row.get('predicate'), 'object_id': oid, 'attributes': {},
                'evidence': row.get('evidence'), 'source_kind': 'structured',
                'review_status': row.get('review_status', '원출처_검토_필요')})
        for row in disclosure.rows('relations.jsonl'):
            sid, oid, chunk_id, doc_id = (row.get(x) for x in ('subject_id','object_id','chunk_id','source_document_id'))
            if sid not in canonical or oid not in canonical or chunk_id not in chunks or doc_id not in docs:
                raise ValueError(f'공시 관계에 연결할 개체 또는 출처가 없습니다: {row.get("relation_id")}')
            if chunks[chunk_id].get('document_id') != doc_id:
                raise ValueError(f'공시 청크의 문서 ID가 다릅니다: {chunk_id}')
            quote = row.get('evidence_quote')
            if not isinstance(quote, str) or quote != chunks[chunk_id].get('text'):
                raise ValueError(f'공시 표 행과 근거가 다릅니다: {chunk_id}')
            note_kind = {'COMPANY-AMOREPACIFIC':'control', 'COMPANY-INNISFREE':'innisfree_basis'}.get(oid)
            note_id = doc_id + '-NOTE-' + note_kind if note_kind else None
            if note_id and note_id not in chunks:
                raise ValueError(f'연관 공시 주석 청크가 없습니다: {note_id}')
            base_relations.append({'relation_id': row['relation_id'], 'subject_id': sid,
                'predicate': row.get('predicate'), 'object_id': oid,
                'attributes': {k: row.get(k) for k in ('value_number','unit','as_of_date','percentage_basis','scope')},
                'evidence': {'document': docs[doc_id], 'chunk': chunks[chunk_id], 'quote': quote,
                             'related_note_chunk_ids': [note_id] if note_id else []},
                'source_kind': 'disclosure', 'review_status': row.get('review_status')})
        for row in base_relations:
            predicate = row.get('predicate')
            st = canonical[row['subject_id']]['type']
            ot = canonical[row['object_id']]['type']
            if predicate not in RULES or st not in RULES[predicate][0] or ot not in RULES[predicate][1]:
                raise ValueError(f'구조화·공시 관계의 유형 또는 방향이 잘못됐습니다: {row["relation_id"]}')

        # 원문에서 추출된 각 개체는 (청크 ID, local_id)로 식별한다.
        mappings, news_nodes, news_relations, candidates = [], [], [], []
        seen_news_node_ids = set()
        review_representative_types = {}
        seen_chunks, seen_relation_ids = set(), set()
        total_mentions = 0
        for record in m4.rows('extractions.jsonl'):
            if args.limit is not None and len(seen_chunks) >= args.limit:
                break
            inp, output = record.get('input', {}), record.get('output', {})
            doc_id, chunk_id, text = inp.get('document_id'), inp.get('chunk_id'), inp.get('primary_text')
            if not all(isinstance(x, str) and x for x in (doc_id, chunk_id)) or not isinstance(text, str):
                raise ValueError('M4 입력에 문서 ID·청크 ID·본문이 필요합니다.')
            if chunk_id in seen_chunks or output.get('document_id') != doc_id or output.get('chunk_id') != chunk_id:
                raise ValueError(f'청크 ID 중복 또는 입출력 ID 불일치: {chunk_id}')
            if not isinstance(output.get('entities'), list) or not isinstance(output.get('relations'), list):
                raise ValueError(f'개체·관계 배열이 없습니다: {chunk_id}')
            seen_chunks.add(chunk_id)
            local = {}
            for entity in output['entities']:
                lid, typ, name = entity.get('local_id'), entity.get('type'), entity.get('name')
                if not all(isinstance(x, str) and x.strip() for x in (lid, typ, name)) or lid in local or typ not in ENTITY_TYPES:
                    raise ValueError(f'개체 ID·유형·이름 오류: {chunk_id}/{lid}')
                key = (chunk_id, lid)
                local_id = 'MENTION-' + digest(json.dumps(key, ensure_ascii=False))
                possible = sorted(company_index.get(company_search_key(name), set())) if typ == 'Company' else []
                prior = previous_mentions.get(key) if previous else None
                if previous and (not prior or prior.get('document_id') != doc_id or prior.get('original_entity') != entity):
                    raise ValueError(f'기존 M5의 원본 언급이 현재 M4와 다릅니다: {chunk_id}/{lid}')
                approved = decisions.get(key)
                prior_status = prior.get('output_status') if prior else None
                prior_rep = prior.get('output_entity_id') if prior else None
                if approved:
                    rep = approved['representative_id']
                    # 기준 개체, 이전 뉴스 대표 개체 또는 사람이 직접 만든 REVIEW- ID만 허용한다.
                    if rep in canonical:
                        target_type = canonical[rep]['type']
                    elif rep in previous_nodes:
                        target_type = previous_nodes[rep].get('type')
                    elif re.fullmatch(r'REVIEW-[A-Za-z0-9_-]{1,80}', rep):
                        target_type = review_representative_types.setdefault(rep, typ)
                    else:
                        raise ValueError(f'승인할 기준 ID가 없거나 REVIEW- 형식이 아닙니다: {rep}')
                    if target_type != typ:
                        raise ValueError(f'검토 승인 대상 ID의 유형이 일치하지 않습니다: {chunk_id}/{lid} -> {rep}')
                    used_decisions.add(key)
                    status = '사람검토_승인'
                    note = approved['note']
                elif prior_status in ('자동연결_미검토', '잠정_검토필요'):
                    # 이전에 연결한 ID를 재사용하되, 검토 필요 상태를 유지한다.
                    prior_node = previous_nodes.get(prior_rep)
                    if not prior_node or prior_node.get('type') != typ:
                        raise ValueError(f'기존 M5 대표 개체가 없거나 유형이 다릅니다: {chunk_id}/{lid}')
                    if prior_rep in canonical and canonical[prior_rep]['type'] != typ:
                        raise ValueError(f'기존 M5 대표 ID가 구조화 개체와 충돌합니다: {prior_rep}')
                    rep, status, note = prior_rep, '기존_' + prior_status, '기존 M5 결과 재사용; 사람 검토 필요'
                else:
                    # 이름이 같다는 이유만으로 확정 병합하지 않는다.
                    rep, status, note = local_id, '미결_원문검토필요', ''
                item = {'document_id':doc_id, 'chunk_id':chunk_id, 'local_id':lid,
                    'original_name':name, 'original_type':typ, 'mention_id':local_id,
                    'representative_id':rep, 'resolution_status':status,
                    'candidate_company_ids':possible, 'decision_note':note,
                    'previous_output_entity_id': prior_rep, 'previous_output_status': prior_status,
                    'previous_mention_record': prior,
                    'source_metadata':inp.get('metadata', {}), 'original_attributes':entity.get('attributes', {})}
                mappings.append(item)
                if rep not in canonical and rep not in seen_news_node_ids:
                    # 기존 대표 개체라면 원래의 속성 변형과 검토 상태도 함께 보존한다.
                    news_nodes.append({'entity_id':rep,'type':typ,
                        'name':previous_nodes[rep].get('name', name) if rep in previous_nodes else name,
                        'identity_status':status,'source_mention':{'document_id':doc_id,'chunk_id':chunk_id,'local_id':lid},
                        'attributes':entity.get('attributes', {}),
                        'previous_record':previous_nodes.get(rep)})
                    seen_news_node_ids.add(rep)
                if not approved:
                    # 원문에서 이름이 나온 주변 일부를 함께 기록해 검토를 돕는다.
                    index = text.find(name)
                    start = max(0, index - 150) if index >= 0 else 0
                    excerpt = text[start:start + 400].replace('\n', ' ')
                    candidates.append({'chunk_id':chunk_id,'local_id':lid,'original_type':typ,
                        'original_name':name,'candidate_ids':' | '.join(possible),
                        'previous_representative_id':prior_rep or '', 'previous_status':prior_status or '',
                        'representative_id':'','decision':'','note':'', 'context_excerpt':excerpt,
                        'document_id':doc_id,'source_url':inp.get('metadata',{}).get('source_url','')})
                local[lid] = item
                total_mentions += 1
            for number, row in enumerate(output['relations'], 1):
                sid, oid, predicate = row.get('subject_id'), row.get('object_id'), row.get('predicate')
                if sid not in local or oid not in local:
                    raise ValueError(f'관계의 로컬 개체 ID가 없습니다: {chunk_id}/{number}')
                st, ot = local[sid]['original_type'], local[oid]['original_type']
                if predicate not in RULES or st not in RULES[predicate][0] or ot not in RULES[predicate][1]:
                    raise ValueError(f'관계 유형 또는 방향 오류: {chunk_id}/{number}')
                quote = (row.get('evidence') or {}).get('quote')
                if not isinstance(quote, str) or not quote.strip() or quote not in text:
                    raise ValueError(f'관계의 원문 근거가 청크에 없습니다: {chunk_id}/{number}')
                rid = chunk_id + ':R' + f'{number:04d}'
                if rid in seen_relation_ids:
                    raise ValueError(f'관계 ID 중복: {rid}')
                seen_relation_ids.add(rid)
                if previous:
                    old = previous_relations.get(rid)
                    if (not old or old.get('document_id') != doc_id or old.get('chunk_id') != chunk_id
                        or old.get('predicate') != predicate or old.get('attributes') != row.get('attributes', {})
                        or old.get('evidence') != row.get('evidence')
                        or old.get('source_metadata') != inp.get('metadata', {})
                        or old.get('source_candidate_subject_id') != previous_mentions[(chunk_id, sid)].get('candidate_entity_id')
                        or old.get('source_candidate_object_id') != previous_mentions[(chunk_id, oid)].get('candidate_entity_id')):
                        raise ValueError(f'기존 M5 관계의 근거·속성이 현재 M4와 다릅니다: {rid}')
                endpoint_status = (local[sid]['resolution_status'], local[oid]['resolution_status'])
                if '미결_원문검토필요' in endpoint_status:
                    relation_status = '개체_미결_검토필요'
                elif all(x == '사람검토_승인' for x in endpoint_status):
                    relation_status = '관계의미_원문검토필요'
                else:
                    relation_status = '기존자동또는잠정연결_검토필요'
                news_relations.append({'relation_id':rid,'subject_id':local[sid]['representative_id'],
                    'predicate':predicate,'object_id':local[oid]['representative_id'],
                    'subject_resolution':local[sid]['resolution_status'], 'object_resolution':local[oid]['resolution_status'],
                    'attributes':row.get('attributes',{}),
                    'evidence':{'document_id':doc_id,'chunk_id':chunk_id,'quote':quote,
                        'source_metadata':inp.get('metadata',{})},
                    'source_kind':'news','review_status':relation_status})
        unused = set(decisions) - used_decisions
        if unused:
            raise ValueError(f'입력에서 찾지 못한 승인 결정 {len(unused)}건. --limit 범위와 CSV를 확인하세요.')

        # 대표 개체에 모인 언급의 상태가 섞일 수 있어 최초 언급의 상태로 전체를 판단하지 않는다.
        mention_status_counts = {}
        for item in mappings:
            mention_status_counts.setdefault(item['representative_id'], Counter())[item['resolution_status']] += 1
        for node in news_nodes:
            node['mention_status_counts'] = dict(mention_status_counts.get(node['entity_id'], {}))
            node['identity_status'] = '언급별_검토상태_확인'
        for eid, node in canonical.items():
            node['news_mention_status_counts'] = dict(mention_status_counts.get(eid, {}))

        # 계산이 끝나고 검증된 뒤에만 새 폴더에 결과를 쓴다.
        args.output.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.output/'canonical_nodes.jsonl', canonical.values())
        write_jsonl(args.output/'news_nodes.jsonl', news_nodes)
        write_jsonl(args.output/'mention_mapping.jsonl', mappings)
        write_jsonl(args.output/'structured_disclosure_relations.jsonl', base_relations)
        write_jsonl(args.output/'disclosure_documents.jsonl', docs.values())
        write_jsonl(args.output/'disclosure_chunks.jsonl', chunks.values())
        write_jsonl(args.output/'news_relations.jsonl', news_relations)
        fields=['chunk_id','local_id','original_type','original_name','candidate_ids','previous_representative_id','previous_status','representative_id','decision','note','context_excerpt','document_id','source_url']
        with (args.output/'review_mentions.csv').open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(candidates)
        # 정규화 전후 사례는 전체 결과를 대표하는 정확도 표본이 아니다.
        examples = []
        per_status = Counter()
        for item in mappings:
            status = item['resolution_status']
            if per_status[status] < 3:
                examples.append({k:item.get(k) for k in ('chunk_id','local_id','original_type','original_name',
                    'mention_id','representative_id','resolution_status','previous_output_entity_id','previous_output_status')})
                per_status[status] += 1
        example_fields=['chunk_id','local_id','original_type','original_name','mention_id',
                        'representative_id','resolution_status','previous_output_entity_id','previous_output_status']
        with (args.output/'before_after_examples.csv').open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=example_fields);writer.writeheader();writer.writerows(examples)
        try:
            with m4.open('summary.json') as handle:
                original_m4_summary = json.load(handle)
        except ValueError:
            original_m4_summary = None
        summary={'m4_input_status_counts':original_m4_summary.get('status_counts') if original_m4_summary else None,
            'mode':'시험_일부청크' if args.limit is not None else 'M4_성공청크_전체',
            'news_chunks_processed':len(seen_chunks),'news_mentions':total_mentions,
            'canonical_nodes':len(canonical),'news_nodes':len(news_nodes),
            'unresolved_mentions':sum(x['resolution_status']=='미결_원문검토필요' for x in mappings),
            'previous_m5_mentions_reused':sum(x['resolution_status'].startswith('기존_') for x in mappings),
            'news_relations':len(news_relations),'review_mentions':len(candidates),
            'reviewed_mentions':len(used_decisions),'structured_disclosure_relations':len(base_relations),
            'news_relations_by_status':dict(Counter(x['review_status'] for x in news_relations)),
            'disclosure_dates':dict(Counter(x['attributes'].get('as_of_date') for x in base_relations if x['source_kind']=='disclosure')),
            'inputs':{'m4':str(args.m4),'companies':str(args.companies),'companies_sha256':file_hash(args.companies),
                      'disclosure':str(args.disclosure), 'decisions':str(args.decisions) if args.decisions else None,
                      'previous_m5':str(args.previous_m5) if args.previous_m5 else None},
            'warnings':['뉴스 개체의 이름 일치만으로 자동 병합하지 않음','관계의 원문 포함 여부는 의미·사실 검증이 아님',
                        '뉴스 미결 개체와 관계는 별도 검토 필요','M6 로더 형식에 맞춘 매핑·적재는 이 코드의 범위 밖']}
        if args.m4.is_file():summary['inputs']['m4_sha256']=file_hash(args.m4)
        if args.disclosure.is_file():summary['inputs']['disclosure_sha256']=file_hash(args.disclosure)
        if args.decisions:summary['inputs']['decisions_sha256']=file_hash(args.decisions)
        if args.previous_m5 and args.previous_m5.is_file():summary['inputs']['previous_m5_sha256']=file_hash(args.previous_m5)
        (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False,indent=2))
    finally:
        m4.close()
        disclosure.close()
        if previous:
            previous.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile, csv.Error) as error:
        print(f'정규화 실패: {type(error).__name__}: {error}', file=sys.stderr)
        raise SystemExit(1)
