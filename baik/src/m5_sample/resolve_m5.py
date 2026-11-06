#!/usr/bin/env python3
"""Apply explicit review decisions to M4 entity mentions; no API or database writes."""
import argparse
import hashlib
import json
from pathlib import Path


def fingerprint(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def read_jsonl(path):
    with path.open(encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]


def save(path, rows):
    with path.open('w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='M4 JSONL 네 파일이 있는 폴더')
    parser.add_argument('--decisions', type=Path, default=Path(__file__).with_name('review_decisions.jsonl'))
    parser.add_argument('--output', required=True, type=Path, help='존재하지 않는 새 출력 폴더')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('출력 폴더가 이미 존재합니다. 새 폴더를 지정하세요.')
    extracts = read_jsonl(args.input / 'extractions.jsonl')
    entities = read_jsonl(args.input / 'structured_entities.jsonl')
    structured_rels = read_jsonl(args.input / 'structured_relations.jsonl')
    decisions = read_jsonl(args.decisions)
    entity_by_id = {x['entity_id']: x for x in entities}
    if len(entity_by_id) != len(entities):
        raise ValueError('구조화 개체 ID 중복')
    by_key = {}
    for d in decisions:
        key = (d['document_id'], d['chunk_id'], d['local_id'])
        if key in by_key:
            raise ValueError('검토 결정 중복')
        by_key[key] = d
    mentions, unresolved, assertions, unresolved_relations = [], [], [], []
    seen = set()
    for row in extracts:
        inp, out = row['input'], row['output']
        doc, chunk, text = inp['document_id'], inp['chunk_id'], inp['primary_text']
        if out['document_id'] != doc or out['chunk_id'] != chunk:
            raise ValueError('입출력 문서 ID 불일치')
        local_map = {}
        for ent in out['entities']:
            key = (doc, chunk, ent['local_id'])
            if key in seen: raise ValueError('언급 ID 중복')
            seen.add(key)
            d = by_key.get(key)
            # 확인한 원문·개체 내용이 바뀌면 기존 결정을 적용하지 않는다.
            match = d and d['chunk_sha256'] == hashlib.sha256(text.encode('utf-8')).hexdigest() and d['entity_sha256'] == fingerprint(ent)
            mention = {'document_id':doc,'chunk_id':chunk,'local_id':ent['local_id'],'name':ent['name'],'type':ent['type'],'entity_id':d['entity_id'] if match else None,'decision':'reviewed' if match else 'unresolved'}
            mentions.append(mention)
            if match:
                candidate = {'entity_id': d['entity_id'], 'type': d['type'], 'name': d['canonical_name'], 'review_status': '수동_사례_검토'}
                existing = entity_by_id.get(d['entity_id'])
                if existing and existing['type'] != d['type']:
                    raise ValueError('검토 결정과 기존 개체의 유형 충돌')
                if not existing:
                    entity_by_id[d['entity_id']] = candidate
                local_map[ent['local_id']] = d['entity_id']
            else:
                unresolved.append(mention)
        for i, rel in enumerate(out['relations'], 1):
            quote = rel.get('evidence', {}).get('quote')
            item = {'assertion_id':f'{chunk}:R{i:03d}', 'document_id':doc, 'chunk_id':chunk, 'subject_id':local_map.get(rel['subject_id']), 'predicate':rel['predicate'], 'object_id':local_map.get(rel['object_id']), 'attributes':rel['attributes'], 'evidence':rel['evidence'], 'source_url':inp.get('metadata',{}).get('source_url'), 'review_status':'의미_검토_필요'}
            if not quote or quote not in text or not item['subject_id'] or not item['object_id']:
                item['reason'] = '미결 개체 또는 원문 근거 불일치'; unresolved_relations.append(item)
            else: assertions.append(item)
    for rel in structured_rels:
        if rel['subject_id'] not in entity_by_id or rel['object_id'] not in entity_by_id:
            raise ValueError('구조화 관계 대상 ID 없음')
    # 같은 S-P-O라도 시점/상태/속성이 다르면 다른 관계 후보로 유지한다.
    grouped = {}
    for a in assertions:
        key = (a['subject_id'],a['predicate'],a['object_id'],fingerprint(a['attributes']))
        if key not in grouped:
            grouped[key] = {'subject_id':a['subject_id'],'predicate':a['predicate'],'object_id':a['object_id'],'attributes':a['attributes'],'assertion_ids':[]}
        grouped[key]['assertion_ids'].append(a['assertion_id'])
    args.output.mkdir(parents=True)
    save(args.output/'entities.jsonl', entity_by_id.values())
    save(args.output/'mentions_mapping.jsonl', mentions)
    save(args.output/'news_assertions.jsonl', assertions)
    save(args.output/'news_relations_grouped.jsonl', grouped.values())
    save(args.output/'structured_relations.jsonl', structured_rels)
    save(args.output/'unresolved_mentions.jsonl', unresolved)
    save(args.output/'unresolved_relations.jsonl', unresolved_relations)
    summary = {'structured_entities':len(entities),'structured_relations':len(structured_rels),'news_mentions':len(mentions),'news_assertions':len(assertions),'news_grouped_relations':len(grouped),'all_entity_candidates':len(entity_by_id),'unresolved_mentions':len(unresolved),'unresolved_relations':len(unresolved_relations),'review_status':'수동 사례 시험; 원출처 및 관계 의미 검토 필요'}
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
