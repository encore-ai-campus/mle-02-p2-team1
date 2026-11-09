"""M5 잠정 결과를 B_ 접두사의 직접 관계로 AuraDB에 적재한다."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys

from mapper import build_graph

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / 'M5_remaining_quick_result.zip'
DEFAULT_DATASET = 'brian_m6_20261108_v1'
ALLOWED_TYPES = {'Company', 'CorporateGroup', 'Organization', 'Person', 'Character',
                 'Brand', 'Product', 'Market', 'Event', 'Place', 'MetricObservation', 'Regulation'}
ALLOWED_RELATIONS = {'HOLDS_POSITION', 'OWNS_STAKE', 'PART_OF_GROUP', 'OPERATES_BRAND',
                     'PRODUCT_UNDER_BRAND', 'PARTICIPATES_IN', 'REPORTS_METRIC',
                     'MARKET_IN_PLACE', 'EVENT_IN_PLACE', 'PRODUCT_FEATURED_IN',
                     'EVENT_FEATURES', 'REGULATES'}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def graph_fingerprint(graph):
    """입력뿐 아니라 실제 매핑된 노드·관계·출처가 바뀌면 다른 지문을 만든다."""
    return hashlib.sha256(json_text({'nodes': graph['nodes'], 'relationships': graph['relationships']}).encode('utf-8')).hexdigest()


def chunks(items, size):
    for offset in range(0, len(items), size):
        yield items[offset:offset + size]


def validate_graph(graph):
    nodes, relationships = graph['nodes'], graph['relationships']
    ids = [n['id'] for n in nodes]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('노드 ID가 비었거나 중복되었습니다.')
    known = set(ids)
    relation_ids = [r['id'] for r in relationships]
    if len(set(relation_ids)) != len(relation_ids):
        raise ValueError('관계 ID가 중복되었습니다.')
    for node in nodes:
        if len(node['labels']) != 1 or node['labels'][0] not in ALLOWED_TYPES:
            raise ValueError(f"허용하지 않은 노드 유형: {node['labels']}")
        validate_properties(node['properties'])
    for relation in relationships:
        if relation['type'] not in ALLOWED_RELATIONS:
            raise ValueError(f"허용하지 않은 관계 유형: {relation['type']}")
        if relation['start'] not in known or relation['end'] not in known:
            raise ValueError(f"관계의 노드가 없습니다: {relation['id']}")
        validate_properties(relation['properties'])
        source_json = relation['properties'].get('sources_json')
        if not source_json:
            raise ValueError(f"관계에 출처가 없습니다: {relation['id']}")
        try:
            sources = json.loads(source_json)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"출처 JSON을 읽을 수 없습니다: {relation['id']}") from exc
        if not isinstance(sources, list) or not sources or len(sources) != relation['properties'].get('source_count'):
            raise ValueError(f"출처 건수가 다릅니다: {relation['id']}")


def validate_properties(properties):
    # Neo4j 속성에 중첩 사전 또는 혼합 배열을 그대로 저장할 수 없다.
    for key, value in properties.items():
        if not isinstance(key, str):
            raise ValueError('속성 이름이 문자열이 아닙니다.')
        if value is None or isinstance(value, (str, bool, int, float)):
            continue
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            continue
        raise ValueError(f'저장할 수 없는 속성 형식: {key} ({type(value).__name__})')


def run_write(tx, query, **parameters):
    return tx.run(query, **parameters).single()


def existing_hashes(tx, dataset):
    row = tx.run('MATCH (n:B_M6Entity {dataset_id:$dataset}) '
                 'RETURN collect(DISTINCT coalesce(n.input_hash, "")) AS hashes',
                 dataset=dataset).single()
    return row['hashes']


def write_nodes(tx, label, rows, dataset, fingerprint):
    # label은 외부 입력이 아닌 ALLOWED_TYPES 통과 후 결정된다.
    query = f'''UNWIND $rows AS row
    MERGE (n:B_M6Entity {{uid: row.uid}})
    SET n:B_{label}
    SET n += row.properties
    SET n.dataset_id = $dataset, n.input_hash = $fingerprint
    RETURN count(n) AS count'''
    return run_write(tx, query, rows=rows, dataset=dataset, fingerprint=fingerprint)['count']


def write_relations(tx, relation_type, rows, dataset, fingerprint):
    # 동일 주어·관계·목적어·의미 속성의 여러 근거는 mapper가 하나의 관계로 묶는다.
    query = f'''UNWIND $rows AS row
    MATCH (s:B_M6Entity {{uid: row.start_uid, dataset_id: $dataset}})
    MATCH (o:B_M6Entity {{uid: row.end_uid, dataset_id: $dataset}})
    MERGE (s)-[r:B_{relation_type} {{uid: row.uid}}]->(o)
    SET r += row.properties
    SET r.dataset_id = $dataset, r.input_hash = $fingerprint
    RETURN count(r) AS count'''
    return run_write(tx, query, rows=rows, dataset=dataset, fingerprint=fingerprint)['count']


def read_verify(tx, dataset):
    nodes = tx.run('MATCH (n:B_M6Entity {dataset_id:$dataset}) '
                   'RETURN n.uid AS uid, n.input_hash AS input_hash, labels(n) AS labels, properties(n) AS properties', dataset=dataset)
    rels = tx.run('MATCH (s:B_M6Entity {dataset_id:$dataset})-[r]->'
                  '(o:B_M6Entity {dataset_id:$dataset}) WHERE r.dataset_id=$dataset '
                  'RETURN r.uid AS uid, r.input_hash AS input_hash, '
                  'r.sources_json AS sources_json, r.source_count AS source_count, '
                  's.uid AS start_uid, o.uid AS end_uid, type(r) AS relation_type, '
                  'properties(r) AS properties', dataset=dataset)
    return [dict(row) for row in nodes], [dict(row) for row in rels]


def verify_contents(actual_nodes, actual_rels, graph, dataset, fingerprint):
    expected_nodes = {dataset + '|' + n['id']: n for n in graph['nodes']}
    expected_rels = {dataset + '|' + r['id']: r for r in graph['relationships']}
    node_ids = [n['uid'] for n in actual_nodes]
    rel_ids = [r['uid'] for r in actual_rels]
    if len(node_ids) != len(expected_nodes) or set(node_ids) != set(expected_nodes):
        raise ValueError(f'노드 검증 실패: 실제 {len(node_ids)}, 예상 {len(expected_nodes)}')
    if len(rel_ids) != len(expected_rels) or set(rel_ids) != set(expected_rels):
        raise ValueError(f'관계 검증 실패: 실제 {len(rel_ids)}, 예상 {len(expected_rels)}')
    if any(x['input_hash'] != fingerprint for x in actual_nodes + actual_rels):
        raise ValueError('입력 지문이 다른 노드 또는 관계가 있습니다.')
    for row in actual_nodes:
        node = expected_nodes[row['uid']]
        if 'B_' + node['labels'][0] not in row['labels']:
            raise ValueError(f"노드 유형 검증 실패: {row['uid']}")
        if any(row['properties'].get(k) != v for k, v in node['properties'].items() if v is not None):
            raise ValueError(f"노드 속성 검증 실패: {row['uid']}")
    for row in actual_rels:
        expected = expected_rels[row['uid']]
        if (row['start_uid'] != dataset+'|'+expected['start'] or
            row['end_uid'] != dataset+'|'+expected['end'] or
            row['relation_type'] != 'B_'+expected['type']):
            raise ValueError(f"관계 방향 또는 유형 검증 실패: {row['uid']}")
        props = expected['properties']
        if any(row['properties'].get(k) != v for k, v in props.items() if v is not None):
            raise ValueError(f"관계 속성 검증 실패: {row['uid']}")
        if row['sources_json'] != props.get('sources_json') or row['source_count'] != props.get('source_count'):
            raise ValueError(f"출처 보존 검증 실패: {row['uid']}")
    return {'nodes': len(node_ids), 'relationships': len(rel_ids),
            'source_records': sum(x['source_count'] for x in actual_rels)}


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT, help='최종 M5 결과 ZIP')
    parser.add_argument('--dataset-id', default=DEFAULT_DATASET, help='다른 팀 데이터와 분리할 데이터셋 ID')
    parser.add_argument('--batch-size', type=int, default=500, help='트랜잭션당 처리할 최대 개수')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='AuraDB 연결 없이 변환·입력 검사')
    mode.add_argument('--verify-only', action='store_true', help='DB에 저장된 내용만 조회·검증')
    return parser.parse_args()


def main():
    args = parse_arguments()
    if not args.dataset_id.strip() or len(args.dataset_id) > 160:
        raise ValueError('dataset-id는 1~160자의 비어 있지 않은 문자열이어야 합니다.')
    if not 1 <= args.batch_size <= 2000:
        raise ValueError('batch-size는 1~2000이어야 합니다.')
    graph = build_graph(args.input)
    validate_graph(graph)
    fingerprint = graph_fingerprint(graph)
    print('입력·매핑 검사:', json.dumps(graph['summary'], ensure_ascii=False), flush=True)
    print(f"대상 노드 {len(graph['nodes']):,}개, 직접 관계 {len(graph['relationships']):,}개", flush=True)
    print('dataset_id:', args.dataset_id, '| 입력 지문:', fingerprint[:16], flush=True)
    if args.dry_run:
        print('DB에 접속하거나 데이터를 변경하지 않았습니다.')
        return
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # 환경변수로 이미 설정되어 있다면 dotenv는 선택 사항이다.
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError('Neo4j 드라이버가 없습니다. uv add neo4j python-dotenv 을 실행하세요.') from exc
    uri = os.getenv('NEO4J_URI', '').strip()
    username = os.getenv('NEO4J_USERNAME', '').strip()
    password = os.getenv('NEO4J_PASSWORD', '')
    database = os.getenv('NEO4J_DATABASE', '').strip() or None
    if not uri.startswith('neo4j+s://') or not username or not password:
        raise ValueError('NEO4J_URI(neo4j+s://), NEO4J_USERNAME, NEO4J_PASSWORD 설정을 확인하세요.')
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        print('AuraDB 연결 성공', flush=True)
        with driver.session(database=database) as session:
            hashes = session.execute_read(existing_hashes, args.dataset_id)
            if hashes and set(hashes) != {fingerprint}:
                raise ValueError('같은 dataset-id에 다른 입력 결과가 있습니다. 새 --dataset-id를 지정하세요.')
            if not args.verify_only:
                # 최초 한 번 제약을 만든다. 이 제약은 적재 중단 후에도 남는다.
                session.run('CREATE CONSTRAINT b_m6_entity_uid_unique IF NOT EXISTS '
                            'FOR (n:B_M6Entity) REQUIRE n.uid IS UNIQUE').consume()
                by_type = defaultdict(list)
                for n in graph['nodes']:
                    props = {k: v for k, v in n['properties'].items() if v is not None}
                    by_type[n['labels'][0]].append({'uid': args.dataset_id+'|'+n['id'], 'properties': props})
                done = 0
                for label, rows in sorted(by_type.items()):
                    for batch in chunks(rows, args.batch_size):
                        written = session.execute_write(write_nodes, label, batch, args.dataset_id, fingerprint)
                        if written != len(batch): raise RuntimeError('노드 적재 건수가 일치하지 않습니다.')
                        done += written
                        print(f'노드 {done:,}/{len(graph["nodes"]):,}', flush=True)
                by_type.clear()
                for r in graph['relationships']:
                    props = {k: v for k, v in r['properties'].items() if v is not None}
                    by_type[r['type']].append({'uid': args.dataset_id+'|'+r['id'],
                        'start_uid': args.dataset_id+'|'+r['start'],
                        'end_uid': args.dataset_id+'|'+r['end'], 'properties': props})
                done = 0
                for relation_type, rows in sorted(by_type.items()):
                    for batch in chunks(rows, args.batch_size):
                        written = session.execute_write(write_relations, relation_type, batch, args.dataset_id, fingerprint)
                        if written != len(batch): raise RuntimeError('끝점 누락 등으로 관계 적재 건수가 일치하지 않습니다.')
                        done += written
                        print(f'관계 {done:,}/{len(graph["relationships"]):,}', flush=True)
            actual_nodes, actual_rels = session.execute_read(read_verify, args.dataset_id)
            result = verify_contents(actual_nodes, actual_rels, graph, args.dataset_id, fingerprint)
            print('적재 결과 검증 성공:', json.dumps(result, ensure_ascii=False), flush=True)
            print('같은 입력·dataset-id를 다시 실행할 때 중복 여부도 별도 검증하세요.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n중단됨: 이미 완료된 트랜잭션은 저장되었을 수 있습니다. 같은 설정으로 재실행할 수 있습니다.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f'실행 실패: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
