"""M5 소량 결과의 출처별 근거를 직접 관계 속성에 저장한다."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET = 'brian_m6_direct_20261106_v1'
ENTITY_TYPES = {'Company', 'MetricObservation', 'Event', 'Place', 'Person'}
RELATION_TYPES = {'REPORTS_METRIC', 'PARTICIPATES_IN', 'EVENT_IN_PLACE', 'HOLDS_POSITION'}
INPUTS = ['entities.jsonl', 'news_assertions.jsonl', 'structured_relations.jsonl', 'unresolved_mentions.jsonl', 'unresolved_relations.jsonl']


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_jsonl(path):
    with path.open(encoding='utf-8-sig') as file:
        return [json.loads(line) for line in file if line.strip()]


def scalar_values(values):
    return {key: value for key, value in values.items() if value is not None and isinstance(value, (str, int, float, bool))}


def prepare(folder):
    raw = {name: read_jsonl(folder / name) for name in INPUTS}
    if raw['unresolved_mentions.jsonl'] or raw['unresolved_relations.jsonl']:
        raise ValueError('미결 개체나 관계가 있습니다. 검토 후 진행하세요.')
    entities = raw['entities.jsonl']
    ids = [e['entity_id'] for e in entities]
    if len(ids) != len(set(ids)) or any(e['type'] not in ENTITY_TYPES for e in entities):
        raise ValueError('개체 ID 중복 또는 미지원 유형')
    all_sources = []
    for item in raw['news_assertions.jsonl']:
        all_sources.append({'subject': item['subject_id'], 'predicate': item['predicate'], 'object': item['object_id'], 'attributes': item.get('attributes', {}), 'source': {'kind': 'news', 'record': item}})
    for item in raw['structured_relations.jsonl']:
        all_sources.append({'subject': item['subject_id'], 'predicate': item['predicate'], 'object': item['object_id'], 'attributes': {}, 'source': {'kind': 'structured', 'record': item}})
    grouped = {}
    for item in all_sources:
        if item['subject'] not in ids or item['object'] not in ids or item['predicate'] not in RELATION_TYPES:
            raise ValueError('관계의 끝점 또는 유형 오류')
        # 속성이 다르면 다른 관계로 둔다. 시점 등 다른 주장을 무작정 합치지 않는다.
        key = json.dumps([item['subject'], item['predicate'], item['object'], item['attributes']], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if key not in grouped:
            grouped[key] = {'subject': item['subject'], 'object': item['object'], 'predicate': item['predicate'], 'attributes': item['attributes'], 'id': digest(key), 'sources': []}
        grouped[key]['sources'].append(item['source'])
    relations = list(grouped.values())
    # 입력 내용과 실행 계약의 지문. 같은 데이터셋에 다른 입력이 섞이지 않게 한다.
    return entities, relations, digest({'raw': raw, 'contract': 'direct-v1'}), len(all_sources)


def verify(tx):
    q1 = 'MATCH (n:B_M6Entity {dataset_id:$d}) RETURN count(n) AS n'
    q2 = 'MATCH (s:B_M6Entity {dataset_id:$d})-[r]->(o:B_M6Entity {dataset_id:$d}) WHERE r.dataset_id=$d RETURN count(r) AS n'
    q3 = 'MATCH (:B_M6Entity {dataset_id:$d})-[r]->(:B_M6Entity {dataset_id:$d}) WHERE r.dataset_id=$d AND r.sources_json IS NOT NULL RETURN count(r) AS n'
    return {k: tx.run(q, d=DATASET).single()['n'] for k, q in [('entities', q1), ('relations', q2), ('relations_with_sources', q3)]}


def write(tx, entities, relations, input_hash):
    # 같은 식별자를 다른 데이터 버전에 재사용하면 출처가 섞이므로 중단한다.
    existing = tx.run('MATCH (n:B_M6Entity {dataset_id:$d}) RETURN collect(DISTINCT coalesce(n.input_hash, "")) AS hashes', d=DATASET).single()['hashes']
    if any(item != input_hash for item in existing):
        raise ValueError('기존 데이터셋의 입력 지문이 다릅니다. 기존 데이터를 확인하세요.')
    for entity in entities:
        props = scalar_values(entity.get('properties') or {})
        props.update({'entity_id': entity['entity_id'], 'name': entity['name'], 'entity_type': entity['type'], 'dataset_id': DATASET, 'input_hash': input_hash, 'review_status': entity.get('review_status') or '검토_필요', 'evidence_json': json.dumps(entity.get('evidence', {}), ensure_ascii=False)})
        # 레이블은 위 허용 집합에서만 가져오고 값은 파라미터로 전달한다.
        tx.run(f"MERGE (n:B_M6Entity {{uid:$uid}}) SET n:B_{entity['type']} SET n += $props", uid=DATASET+'|'+entity['entity_id'], props=props).consume()
    for relation in relations:
        props = scalar_values(relation['attributes'])
        props.update({'dataset_id': DATASET, 'relation_id': relation['id'], 'sources_json': json.dumps(relation['sources'], ensure_ascii=False, sort_keys=True), 'source_count': len(relation['sources'])})
        tx.run(f"MATCH (s:B_M6Entity {{uid:$s}}), (o:B_M6Entity {{uid:$o}}) MERGE (s)-[r:B_{relation['predicate']} {{relation_id:$rid}}]->(o) SET r += $props", s=DATASET+'|'+relation['subject'], o=DATASET+'|'+relation['object'], rid=relation['id'], props=props).consume()
    actual = verify(tx)
    expected = {'entities': len(entities), 'relations': len(relations), 'relations_with_sources': len(relations)}
    if actual != expected:
        raise ValueError(f'적재 건수 불일치, 트랜잭션 롤백: {actual} != {expected}')
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'input')
    parser.add_argument('--dry-run', action='store_true', help='DB 연결 없이 데이터 검사')
    parser.add_argument('--verify-only', action='store_true', help='DB 조회만 수행')
    args = parser.parse_args()
    entities, relations, input_hash, source_count = prepare(args.input)
    print(f'입력 검사: 개체 {len(entities)}, 관계 {len(relations)}, 출처별 근거 {source_count}')
    if args.dry_run:
        return
    from dotenv import load_dotenv
    from neo4j import GraphDatabase
    load_dotenv()
    uri, user, password = (os.getenv(k) for k in ('NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD'))
    database = os.getenv('NEO4J_DATABASE') or 'neo4j'
    if not all((uri, user, password)) or not uri.startswith('neo4j+s://'):
        raise ValueError('.env의 NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD를 확인하세요')
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        print('AuraDB 연결 성공, DB:', database)
        with driver.session(database=database) as session:
            if args.verify_only:
                print('현재 상태:', session.execute_read(verify))
                return
            # 제약 생성은 별도 트랜잭션이므로 적재 실패 시에도 남을 수 있다.
            session.run('CREATE CONSTRAINT b_m6_entity_uid_unique IF NOT EXISTS FOR (n:B_M6Entity) REQUIRE n.uid IS UNIQUE').consume()
            print('적재 및 확인:', session.execute_write(write, entities, relations, input_hash))


if __name__ == '__main__':
    main()
