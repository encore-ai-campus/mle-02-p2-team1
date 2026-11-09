"""M8 패치의 범위·근거 보존과 모의 트랜잭션 동작을 검증한다."""
import copy
import json
import re
import unittest
from pathlib import Path

from mapper import build_graph
from load_m6 import graph_fingerprint
from patch_m8 import (DATASET, OLD_EVENT, assert_no_external_or_changed_incident,
                      expected_db_properties, make_plan, update_once)

ROOT=Path(__file__).resolve().parent


class FakeResult:
    def __init__(self, rows): self.rows=rows
    def __iter__(self): return iter(self.rows)
    def single(self): return self.rows[0]


class FakeTx:
    """Cypher 서버가 아닌 메모리 모의 객체. 실제 쿼리 문법 검증은 하지 못한다."""
    def __init__(self, graph, dataset, fingerprint):
        self.nodes={dataset+'|'+n['id']:{'uid':dataset+'|'+n['id'], 'input_hash':fingerprint,
            'labels':['B_M6Entity','B_'+n['labels'][0]],
            'properties':expected_db_properties(n,dataset,fingerprint)} for n in graph['nodes']}
        self.rels={dataset+'|'+r['id']:{'uid':dataset+'|'+r['id'], 'input_hash':fingerprint,
            'sources_json':r['properties']['sources_json'],'source_count':r['properties']['source_count'],
            'start_uid':dataset+'|'+r['start'],'end_uid':dataset+'|'+r['end'],
            'relation_type':'B_'+r['type'], 'properties':expected_db_properties(r,dataset,fingerprint)}
            for r in graph['relationships']}

    def run(self,query,**kw):
        if 'labels(n) AS labels' in query:
            return FakeResult(list(self.nodes.values()))
        if 'properties(r) AS properties' in query:
            return FakeResult(list(self.rels.values()))
        if 'MATCH (e:B_M6Entity' in query:
            return FakeResult([{'uid':r['uid'],'dataset_id':r['properties']['dataset_id']}
                for r in self.rels.values() if kw['uid'] in (r['start_uid'],r['end_uid'])])
        if 'MATCH (n:B_M6Entity) WHERE n.uid IN' in query:
            return FakeResult([{'n':sum(uid in self.nodes for uid in kw['uids'])}])
        if 'MATCH ()-[r]->() WHERE r.uid IN' in query:
            return FakeResult([{'n':sum(uid in self.rels for uid in kw['uids'])}])
        if 'MERGE (n:B_M6Entity' in query:
            typ=re.search(r'SET n:(B_\w+)',query).group(1)
            for row in kw['rows']:
                props={**row['properties'],'uid':row['uid'],'dataset_id':kw['dataset'],'input_hash':kw['fingerprint']}
                self.nodes[row['uid']]={'uid':row['uid'],'input_hash':kw['fingerprint'],
                    'labels':['B_M6Entity',typ],'properties':props}
            return FakeResult([{'count':len(kw['rows'])}])
        if 'MERGE (s)-[r:' in query:
            typ=re.search(r'MERGE \(s\)-\[r:(B_\w+)',query).group(1); count=0
            for row in kw['rows']:
                if row['start_uid'] not in self.nodes or row['end_uid'] not in self.nodes:continue
                props={**row['properties'],'uid':row['uid'],'dataset_id':kw['dataset'],'input_hash':kw['fingerprint']}
                self.rels[row['uid']]={'uid':row['uid'],'input_hash':kw['fingerprint'],
                    'sources_json':props['sources_json'],'source_count':props['source_count'],
                    'start_uid':row['start_uid'],'end_uid':row['end_uid'],'relation_type':typ,'properties':props}
                count+=1
            return FakeResult([{'count':count}])
        if 'FOREACH (r IN rs | DELETE r)' in query:
            count=0
            for uid in kw['uids']:
                if uid in self.rels:del self.rels[uid];count+=1
            return FakeResult([{'n':count}])
        if 'DELETE n RETURN count(*) AS removed_count' in query:
            if any(kw['uid'] in (r['start_uid'],r['end_uid']) for r in self.rels.values()):
                raise ValueError('노드에 연결된 관계가 남아 있습니다.')
            count=int(kw['uid'] in self.nodes)
            self.nodes.pop(kw['uid'],None)
            return FakeResult([{'removed_count':count}])
        if 'SET n.input_hash=$fingerprint' in query:
            for row in self.nodes.values():
                row['input_hash']=kw['fingerprint'];row['properties']['input_hash']=kw['fingerprint']
            return FakeResult([{'n':len(self.nodes)}])
        if 'SET r.input_hash=$fingerprint' in query:
            for row in self.rels.values():
                row['input_hash']=kw['fingerprint'];row['properties']['input_hash']=kw['fingerprint']
            return FakeResult([{'n':len(self.rels)}])
        raise AssertionError('지원하지 않는 테스트 쿼리: '+query[:100])


class PatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=build_graph(ROOT/'M5_before_M8.zip')
        cls.after=build_graph(ROOT/'M5_after_M8.zip')
        cls.plan=make_plan(cls.before,cls.after)

    def test_exact_scope_and_all_sources(self):
        self.assertEqual(self.plan['removed_nodes'][0]['id'],OLD_EVENT)
        self.assertEqual((len(self.plan['added_nodes']),len(self.plan['removed_relations']),
                          len(self.plan['added_relations']),len(self.plan['changed_source_ids'])),(3,5,5,11))
        self.assertEqual(self.plan['source_records'],17726)
        self.assertEqual(self.plan['before_fingerprint'][:16],'305f574aca152a61')
        self.assertEqual(len(self.after['nodes']),12249)
        self.assertEqual(len(self.after['relationships']),13322)

    def test_full_graph_fake_apply_and_second_run(self):
        tx=FakeTx(self.before,DATASET,self.plan['before_fingerprint'])
        result=update_once(tx,self.before,self.after,self.plan,DATASET)
        self.assertEqual(result['status'],'corrected')
        self.assertEqual(result['verification'],{'nodes':12249,'relationships':13322,'source_records':17726})
        self.assertEqual(update_once(tx,self.before,self.after,self.plan,DATASET)['status'],'already_corrected')
        self.assertNotIn(DATASET+'|'+OLD_EVENT,tx.nodes)

    def test_other_dataset_connection_aborts_before_write(self):
        tx=FakeTx(self.before,DATASET,self.plan['before_fingerprint'])
        tx.rels['external|R']={'uid':'external|R','input_hash':'foreign','sources_json':'[]',
            'source_count':0,'start_uid':'external|A','end_uid':DATASET+'|'+OLD_EVENT,
            'relation_type':'OTHER','properties':{'dataset_id':'external'}}
        # 직접 경계 검사로 다른 데이터셋의 연결을 확인한다.
        rows=[{'uid':DATASET+'|'+r['id'],'dataset_id':DATASET} for r in self.plan['removed_relations']]
        rows.append({'uid':'external|R','dataset_id':'external'})
        with self.assertRaises(ValueError): assert_no_external_or_changed_incident(rows,self.plan,DATASET)

    def test_unrelated_quote_change_invalidates_plan(self):
        altered=copy.deepcopy(self.after)
        altered['relationships'][0]['properties']['sources_json']='[]'
        with self.assertRaises(ValueError): make_plan(self.before,altered)


if __name__=='__main__':unittest.main()
