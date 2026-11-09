"""AuraDB에서 M7 확인용 질의만 실행하고 결과를 로컬 파일로 저장한다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

from queries import get_queries

ROOT = Path(__file__).resolve().parent
DATASET = 'brian_m6_20261108_v1'
STATS = [
    {'id': 'STATS_NODES', 'question': '데이터셋의 유형별 노드 수', 'cypher': '''
MATCH (n:B_M6Entity {dataset_id:$dataset_id})
RETURN n.entity_type AS node_type, count(n) AS node_count
ORDER BY node_count DESC, node_type''', 'parameters': {}},
    {'id': 'STATS_RELATIONS', 'question': '데이터셋의 유형별 관계 수', 'cypher': '''
MATCH (a:B_M6Entity {dataset_id:$dataset_id})-[r]->(b:B_M6Entity {dataset_id:$dataset_id})
WHERE r.dataset_id = $dataset_id
RETURN type(r) AS relationship_type, count(r) AS relationship_count,
       sum(coalesce(r.source_count, 0)) AS source_record_count
ORDER BY relationship_count DESC, relationship_type''', 'parameters': {}},
    {'id': 'STATS_ISOLATED', 'question': '데이터셋 안에서 관계가 없는 노드 수', 'cypher': '''
MATCH (n:B_M6Entity {dataset_id:$dataset_id})
WHERE NOT EXISTS {
  MATCH (n)-[r]-(m:B_M6Entity {dataset_id:$dataset_id})
  WHERE r.dataset_id = $dataset_id
}
RETURN count(n) AS isolated_node_count''', 'parameters': {}},
]


def read_rows(tx, cypher, params):
    """한 읽기 트랜잭션에서 질의 결과를 모두 가져온다."""
    return [record.data() for record in tx.run(cypher, **params)]


def run_query(session, definition, args):
    params = dict(definition.get('parameters', {}))
    params.update({'dataset_id': args.dataset_id, 'sample_limit': args.sample_limit + 1,
                   'person_name': args.person, 'company_id': args.company_id})
    try:
        rows = session.execute_read(read_rows, definition['cypher'], params)
        capped = definition['id'].startswith('CQ')
        more = capped and len(rows) > args.sample_limit
        if more:
            rows = rows[:args.sample_limit]
        return {'id': definition['id'], 'question': definition['question'], 'status': 'success',
                'returned_rows': len(rows), 'has_more_than_sample': more if capped else None,
                'sample_limit': args.sample_limit if capped else None,
                'parameters': params, 'cypher': definition['cypher'], 'rows': rows}
    except Exception as exc:
        return {'id': definition['id'], 'question': definition['question'], 'status': 'error',
                'error_type': type(exc).__name__, 'error_message': str(exc),
                'parameters': params, 'cypher': definition['cypher'], 'rows': []}


def write_summary(output, results, dataset_id):
    lines = ['# M7 조회 결과 요약', '', f'- 데이터셋: `{dataset_id}`',
             '- 각 CQ는 결과 일부를 최대 지정 건수만큼 보여 주는 표본 조회다.',
             '- 조회된 경로는 원문 사실이나 모든 데이터의 정확성이 검증되었다는 뜻이 아니다.',
             '- 결과 0건은 설정한 조건·현재 데이터에서 경로가 없다는 뜻이며 실제 사실이 없다는 뜻이 아니다.', '',
             '| 조회 | 설명 | 상태 | 표시 건수 | 추가 결과 |',
             '| --- | --- | --- | ---: | --- |']
    for item in results:
        if item['status'] == 'error':
            lines.append(f"| {item['id']} | {item['question']} | 오류: {item['error_type']} | - | - |")
        else:
            more = item.get('has_more_than_sample')
            more_text = '있음' if more is True else ('표본 한도 초과 없음' if more is False else '-')
            lines.append(f"| {item['id']} | {item['question']} | 조회 성공 | {item['returned_rows']} | {more_text} |")
    lines += ['', '> 자세한 노드·관계·출처·오류와 실제 질의는 `m7_results.json`을 확인한다.', '']
    (output/'m7_summary.md').write_text('\n'.join(lines), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'m7_output', help='새 결과 폴더')
    p.add_argument('--dataset-id', default=DATASET)
    p.add_argument('--sample-limit', type=int, default=10, help='CQ별 표시할 최대 결과 수 (1~100)')
    p.add_argument('--person', default='서경배', help='CQ08에 사용할 정확한 인물 이름')
    p.add_argument('--company-id', default='COMPANY-AMOREPACIFIC', help='CQ05에 사용할 회사 ID')
    args = p.parse_args()
    if not 1 <= args.sample_limit <= 100:
        raise ValueError('sample-limit은 1~100이어야 합니다.')
    if not args.dataset_id.strip():
        raise ValueError('dataset-id가 비어 있습니다.')
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError(f'결과를 보존하기 위해 비어 있지 않은 폴더는 사용하지 않습니다: {args.output}')
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError('neo4j 패키지를 찾을 수 없습니다. 기존 M6 환경을 확인하세요.') from exc
    uri, username, password = (os.getenv('NEO4J_URI', '').strip(),
                                os.getenv('NEO4J_USERNAME', '').strip(),
                                os.getenv('NEO4J_PASSWORD', ''))
    database = os.getenv('NEO4J_DATABASE', '').strip() or None
    if not uri.startswith('neo4j+s://') or not username or not password:
        raise ValueError('NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD 설정을 확인하세요.')
    definitions = STATS + get_queries()
    ids = [q['id'] for q in definitions]
    if len(ids) != len(set(ids)):
        raise ValueError('조회 ID가 중복됩니다.')
    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        print('AuraDB 연결 성공. 조회만 수행합니다.', flush=True)
        with driver.session(database=database) as session:
            results = []
            for definition in definitions:
                print(f"조회 중: {definition['id']} · {definition['question']}", flush=True)
                result = run_query(session, definition, args)
                results.append(result)
                if result['status'] == 'error':
                    print(f"  오류: {result['error_type']} — 나머지 조회를 계속합니다.", flush=True)
                else:
                    extra = ' (추가 결과 있음)' if result.get('has_more_than_sample') else ''
                    print(f"  표시 결과: {result['returned_rows']}건{extra}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {'dataset_id': args.dataset_id, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
               'person': args.person, 'company_id': args.company_id, 'sample_limit': args.sample_limit,
               'interpretation': '표본 조회이며 원문 정확성 검증 전', 'queries': results}
    (args.output/'m7_results.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    write_summary(args.output, results, args.dataset_id)
    failures = sum(q['status']=='error' for q in results)
    print(f'저장 완료: {args.output} | 전체 {len(results)}개 조회 중 오류 {failures}개', flush=True)
    print('다른 사람과 결과 공유 시 원문 근거와 기사 출처가 포함되어 있음을 확인하세요.', flush=True)
    if failures:
        print('일부 조회가 실패했습니다. m7_results.json에서 오류 내용을 확인하세요.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\n조회가 중단되었습니다. AuraDB 데이터를 변경하지 않았습니다.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f'실행 실패: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
