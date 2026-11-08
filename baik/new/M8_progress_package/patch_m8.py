"""시상식 오병합 1건을 세 행사로 수정하고 원문 근거를 보존한다.

기본 실행은 읽기 확인만 수행한다. --apply는 데이터셋을 실제 변경한다.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from mapper import build_graph
from load_m6 import graph_fingerprint, read_verify, verify_contents, validate_graph, write_nodes, write_relations

ROOT = Path(__file__).resolve().parent
DATASET = 'brian_m6_20261108_v1'
OLD_EVENT = 'EVENT-RULE-c54dfcd323152a767b51'
BEFORE = ROOT/'M5_before_M8.zip'
AFTER = ROOT/'M5_after_M8.zip'
EXPECTED_HASHES = {
    BEFORE: 'b5672d880c7a941fd02760f3c8cb48bbf036fb41fcd47d0b617549b816855f35',
    AFTER: '11eb07a76ee35002dfe33212479b2d6257699efcc2989107a2d639b0d871095c',
}
NEW_EVENTS = {'EVENT-M8-2024-JEJU-GREEN-AWARDS', 'EVENT-M8-2025-JEJU-GREEN-AWARDS',
              'EVENT-M8-2026-KAS-BRAND-AWARDS'}


def check_input_hashes():
    for path, expected in EXPECTED_HASHES.items():
        digest = hashlib.sha256()
        with path.open('rb') as file:
            for block in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f'검증된 입력 파일이 아닙니다: {path.name}')


def source_records(graph):
    """각 관계에서 원래 추출 기록을 꺼내 ID별로 보존한다."""
    result = {}
    for relation in graph['relationships']:
        for source in json.loads(relation['properties']['sources_json']):
            source_id = source['relation_id']
            if source_id in result:
                raise ValueError('원본 관계 ID가 중복됩니다: ' + source_id)
            result[source_id] = source
    return result


def make_plan(before, after):
    """변경 범위와 원문·속성 보존을 확인한 후 계획을 만든다."""
    validate_graph(before)
    validate_graph(after)
    before_nodes = {x['id']:x for x in before['nodes']}
    after_nodes = {x['id']:x for x in after['nodes']}
    before_rels = {x['id']:x for x in before['relationships']}
    after_rels = {x['id']:x for x in after['relationships']}
    removed_nodes = set(before_nodes)-set(after_nodes)
    added_nodes = set(after_nodes)-set(before_nodes)
    removed_rel_ids = set(before_rels)-set(after_rels)
    added_rel_ids = set(after_rels)-set(before_rels)
    if removed_nodes != {OLD_EVENT} or added_nodes != NEW_EVENTS:
        raise ValueError('예상한 시상식 1개 → 3개 변경 범위가 아닙니다.')
    if len(removed_rel_ids)!=5 or len(added_rel_ids)!=5:
        raise ValueError('예상한 직접 관계 5개 교체 범위가 아닙니다.')
    for nid in set(before_nodes)&set(after_nodes):
        if before_nodes[nid]!=after_nodes[nid]:
            raise ValueError('범위 밖 기존 노드가 변했습니다: '+nid)
    for rid in set(before_rels)&set(after_rels):
        if before_rels[rid]!=after_rels[rid]:
            raise ValueError('범위 밖 기존 관계가 변했습니다: '+rid)
    old_sources, new_sources = source_records(before), source_records(after)
    if set(old_sources)!=set(new_sources) or len(old_sources)!=17726:
        raise ValueError('원본 근거 관계의 ID나 건수가 달라졌습니다.')
    changed_sources = []
    for source_id in old_sources:
        old, new = old_sources[source_id], new_sources[source_id]
        if old == new:
            continue
        # 주어·목적어 ID와 검토 상태만 수정하고 원래 인용·수치·출처를 유지한다.
        permitted = {'subject_id', 'object_id', 'subject_resolution', 'object_resolution', 'review_status'}
        if {k:v for k,v in old.items() if k not in permitted} != {k:v for k,v in new.items() if k not in permitted}:
            raise ValueError('원문·출처 또는 그 외 속성이 달라졌습니다: '+source_id)
        changed_sources.append(source_id)
    if len(changed_sources) != 11:
        raise ValueError('수정 대상 근거 기록이 예상한 11건이 아닙니다.')
    for rid in removed_rel_ids:
        if OLD_EVENT not in (before_rels[rid]['start'], before_rels[rid]['end']):
            raise ValueError('수정 대상이 아닌 기존 관계가 제거됩니다.')
    for rid in added_rel_ids:
        r=after_rels[rid]
        if not ({r['start'],r['end']} & added_nodes):
            raise ValueError('새 시상식과 무관한 관계가 추가됩니다.')
    return {'before_fingerprint':graph_fingerprint(before), 'after_fingerprint':graph_fingerprint(after),
            'removed_nodes':[before_nodes[x] for x in sorted(removed_nodes)],
            'added_nodes':[after_nodes[x] for x in sorted(added_nodes)],
            'removed_relations':[before_rels[x] for x in sorted(removed_rel_ids)],
            'added_relations':[after_rels[x] for x in sorted(added_rel_ids)],
            'changed_source_ids':sorted(changed_sources), 'source_records':len(old_sources)}


def fetch_incident(tx, old_uid):
    """다른 데이터셋과 연결된 관계도 포함하여 시상식에 닿은 모든 관계를 검사한다."""
    rows = tx.run('MATCH (e:B_M6Entity {uid:$uid})-[r]-(other) '
                  'RETURN r.uid AS uid, r.dataset_id AS dataset_id', uid=old_uid)
    return [dict(row) for row in rows]


def assert_no_external_or_changed_incident(rows, plan, dataset):
    expected = {dataset+'|'+r['id'] for r in plan['removed_relations']}
    if len(rows)!=len(expected) or {x['uid'] for x in rows}!=expected or any(x['dataset_id']!=dataset for x in rows):
        raise ValueError('대상 시상식에 예상 밖 관계가 있습니다. 자동 수정을 중단합니다.')


def expected_db_properties(item, dataset, fingerprint):
    # Neo4j에는 None을 저장하지 않으므로 제외한다.
    return {**{k:v for k,v in item['properties'].items() if v is not None},
            'uid':dataset+'|'+item['id'], 'dataset_id':dataset, 'input_hash':fingerprint}


def assert_target_not_customized(actual_nodes, actual_relations, plan, dataset):
    """대상에 다른 작업자가 붙인 추가 속성·레이블이 있으면 자동 삭제하지 않는다."""
    old_hash=plan['before_fingerprint']
    nodes={x['uid']:x for x in actual_nodes}
    rels={x['uid']:x for x in actual_relations}
    for n in plan['removed_nodes']:
        actual=nodes[dataset+'|'+n['id']]
        if actual['properties'] != expected_db_properties(n,dataset,old_hash):
            raise ValueError('대상 노드에 예상과 다른 속성이 있어 자동 수정하지 않습니다.')
        if set(actual['labels']) != {'B_M6Entity','B_Event'}:
            raise ValueError('대상 노드에 예상과 다른 레이블이 있습니다.')
    for r in plan['removed_relations']:
        if rels[dataset+'|'+r['id']]['properties'] != expected_db_properties(r,dataset,old_hash):
            raise ValueError('대상 관계에 예상과 다른 속성이 있어 자동 수정하지 않습니다.')


def read_state(tx, before, after, plan, dataset):
    """전체 노드·관계·출처가 어느 버전과 일치하는지 확인한다."""
    nodes, rels = read_verify(tx,dataset)
    try:
        verify_contents(nodes,rels,before,dataset,plan['before_fingerprint'])
        return 'before', nodes, rels
    except ValueError as before_error:
        try:
            verify_contents(nodes,rels,after,dataset,plan['after_fingerprint'])
            return 'after', nodes, rels
        except ValueError:
            raise ValueError('현재 DB가 보정 전·후 예상 데이터와 다릅니다. 원인 확인 전 중단합니다. '
                             +str(before_error)) from before_error


def update_once(tx, before, after, plan, dataset):
    """모든 DB 변경과 수정 후 확인을 한 트랜잭션에서 수행한다."""
    state,nodes,rels=read_state(tx,before,after,plan,dataset)
    if state == 'after':
        return {'status':'already_corrected'}
    assert_target_not_customized(nodes,rels,plan,dataset)
    assert_no_external_or_changed_incident(fetch_incident(tx,dataset+'|'+OLD_EVENT),plan,dataset)
    new_node_uids=[dataset+'|'+n['id'] for n in plan['added_nodes']]
    check=tx.run('MATCH (n:B_M6Entity) WHERE n.uid IN $uids RETURN count(n) AS n',uids=new_node_uids).single()['n']
    if check: raise ValueError('새 시상식 노드 ID가 이미 있어 중단합니다.')
    new_edge_uids=[dataset+'|'+r['id'] for r in plan['added_relations']]
    edge_check=tx.run('MATCH ()-[r]->() WHERE r.uid IN $uids RETURN count(r) AS n',uids=new_edge_uids).single()['n']
    if edge_check: raise ValueError('새 관계 ID가 이미 있어 중단합니다.')
    new_hash=plan['after_fingerprint']
    node_rows=[{'uid':dataset+'|'+n['id'], 'properties':{k:v for k,v in n['properties'].items() if v is not None}}
               for n in plan['added_nodes']]
    if write_nodes(tx,'Event',node_rows,dataset,new_hash)!=3:
        raise ValueError('새 행사 노드 처리 건수가 맞지 않습니다.')
    for relation in plan['added_relations']:
        row={'uid':dataset+'|'+relation['id'], 'start_uid':dataset+'|'+relation['start'],
             'end_uid':dataset+'|'+relation['end'],
             'properties':{k:v for k,v in relation['properties'].items() if v is not None}}
        if write_relations(tx,relation['type'],[row],dataset,new_hash)!=1:
            raise ValueError('새 관계의 노드를 찾지 못했습니다.')
    old_uids=[dataset+'|'+r['id'] for r in plan['removed_relations']]
    count=tx.run('MATCH (s:B_M6Entity {dataset_id:$dataset})-[r]->(o:B_M6Entity {dataset_id:$dataset}) '
                 'WHERE r.uid IN $uids AND r.dataset_id=$dataset '
                 'WITH collect(r) AS rs FOREACH (r IN rs | DELETE r) RETURN size(rs) AS n',
                 dataset=dataset,uids=old_uids).single()['n']
    if count!=5: raise ValueError('기존 관계 제거 건수가 다릅니다. 트랜잭션을 취소합니다.')
    count=tx.run('MATCH (n:B_M6Entity {uid:$uid, dataset_id:$dataset}) '
                 'DELETE n RETURN count(*) AS removed_count', uid=dataset+'|'+OLD_EVENT,dataset=dataset).single()['removed_count']
    if count!=1: raise ValueError('기존 시상식 노드를 안전하게 제거하지 못했습니다.')
    # 새로운 M5 전체 데이터와의 일관성을 위해 이번 데이터셋에만 새 지문을 기록한다.
    nn=tx.run('MATCH (n:B_M6Entity {dataset_id:$dataset}) SET n.input_hash=$fingerprint RETURN count(n) AS n',
              dataset=dataset,fingerprint=new_hash).single()['n']
    nr=tx.run('MATCH (s:B_M6Entity {dataset_id:$dataset})-[r]->(o:B_M6Entity {dataset_id:$dataset}) '
              'WHERE r.dataset_id=$dataset SET r.input_hash=$fingerprint RETURN count(r) AS n',
              dataset=dataset,fingerprint=new_hash).single()['n']
    if nn!=len(after['nodes']) or nr!=len(after['relationships']):
        raise ValueError('갱신 범위의 노드·관계 건수가 다릅니다.')
    check_nodes,check_rels=read_verify(tx,dataset)
    result=verify_contents(check_nodes,check_rels,after,dataset,new_hash)
    return {'status':'corrected','verification':result}


def load_dotenv_and_driver():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError: pass
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError('Neo4j 드라이버를 찾을 수 없습니다. M6 실행 환경을 확인하세요.') from exc
    uri=os.getenv('NEO4J_URI','').strip(); user=os.getenv('NEO4J_USERNAME','').strip()
    password=os.getenv('NEO4J_PASSWORD',''); database=os.getenv('NEO4J_DATABASE','').strip() or None
    if not uri.startswith('neo4j+s://') or not user or not password:
        raise ValueError('NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD 설정을 확인하세요.')
    return GraphDatabase.driver(uri,auth=(user,password)),database


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true',help='실제 DB에 시상식 분리 적용')
    p.add_argument('--offline',action='store_true',help='DB에 접속하지 않고 패치 범위만 확인')
    args=p.parse_args()
    if args.apply and args.offline: raise ValueError('--offline과 --apply는 함께 쓸 수 없습니다.')
    check_input_hashes()
    before,after=build_graph(BEFORE),build_graph(AFTER)
    plan=make_plan(before,after)
    print('보정 범위: 시상식 노드 1개 → 3개, 관계 5개 재연결, 원본 근거 11건 보존',flush=True)
    print('변경 전:',len(before['nodes']),'노드 /',len(before['relationships']),'관계',flush=True)
    print('변경 후:',len(after['nodes']),'노드 /',len(after['relationships']),'관계',flush=True)
    print('전체 원본 근거:',plan['source_records'],'건 | 새 입력 지문:',plan['after_fingerprint'][:16],flush=True)
    if args.offline:
        print('DB에 접속하지 않았고 아무것도 변경하지 않았습니다.')
        return
    driver,database=load_dotenv_and_driver()
    with driver:
        driver.verify_connectivity(); print('AuraDB 연결 성공',flush=True)
        with driver.session(database=database) as session:
            state,nodes,rels=session.execute_read(read_state,before,after,plan,DATASET)
            print('현재 데이터셋:', '변경 전 상태' if state=='before' else '이미 변경 후 상태',flush=True)
            if state=='before':
                assert_target_not_customized(nodes,rels,plan,DATASET)
                incident=session.execute_read(fetch_incident,DATASET+'|'+OLD_EVENT)
                assert_no_external_or_changed_incident(incident,plan,DATASET)
            if not args.apply:
                print('읽기 확인만 했습니다. DB를 변경하지 않았습니다.')
                return
            if state=='after':
                print('이미 수정되어 추가 변경 없이 검증을 마쳤습니다.')
                return
            # 변경 전 대상의 원본을 로컬에 별도 보관한다. 같은 이름을 덮어쓰지 않는다.
            backup={'dataset_id':DATASET,'created_at_utc':datetime.now(timezone.utc).isoformat(),
                    'before_fingerprint':plan['before_fingerprint'], 'after_fingerprint':plan['after_fingerprint'],
                    'nodes':[x for x in nodes if x['uid']==DATASET+'|'+OLD_EVENT],
                    'relationships':[x for x in rels if x['uid'] in {DATASET+'|'+r['id'] for r in plan['removed_relations']}]}
            output=ROOT/('m8_backup_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
            with output.open('x',encoding='utf8') as f: json.dump(backup,f,ensure_ascii=False,indent=2)
            print('수정 전 백업 저장:',output,flush=True)
            result=session.execute_write(update_once,before,after,plan,DATASET)
            print('M8 보완 결과:',json.dumps(result,ensure_ascii=False),flush=True)
            print('수정 후 M5 결과와 기존 M6 코드로 검증하세요. 예전 M5 입력의 M6 로더는 더 이상 쓰지 마세요.',flush=True)


if __name__=='__main__':
    try: main()
    except KeyboardInterrupt:
        print('\n중단됨. 실행 결과가 불명확하면 기본 읽기 확인을 다시 실행하세요.',file=sys.stderr);raise SystemExit(130)
    except Exception as exc:
        print(f'실행 실패: {type(exc).__name__}: {exc}',file=sys.stderr);raise SystemExit(1)
