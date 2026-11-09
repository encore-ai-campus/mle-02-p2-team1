"""실제 검토 대상 M5 스냅샷의 행사 오병합 교정 결과를 독립 확인한다."""
import json
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'m8_inputs'/'M6_aura_complete'))
from mapper import build_graph

INPUT = ROOT/'m8_inputs'/'final_m5.zip'
OUTPUT = ROOT/'M8_working'/'m5_event_split_corrected.zip'
AUDIT = ROOT/'M8_working'/'m8_event_split_audit.json'
OLD = 'EVENT-RULE-c54dfcd323152a767b51'
E24 = 'EVENT-M8-2024-JEJU-GREEN-AWARDS'
E25 = 'EVENT-M8-2025-JEJU-GREEN-AWARDS'
E26 = 'EVENT-M8-2026-KAS-BRAND-AWARDS'


def read_rows(path, name):
    with zipfile.ZipFile(path) as z:
        with z.open('M5_remaining_quick/results/'+name+'.jsonl') as f:
            return [json.loads(line) for line in f if line.strip()]


def sources(graph):
    answer={}
    for rel in graph['relationships']:
        for raw in json.loads(rel['properties']['sources_json']):
            rid=raw['relation_id']
            if rid in answer: raise AssertionError('source relation ID duplicated')
            answer[rid]=raw
    return answer


class EventSplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=build_graph(INPUT)
        cls.after=build_graph(OUTPUT)
        cls.old=sources(cls.before);cls.new=sources(cls.after)
        cls.audit=json.loads(AUDIT.read_text(encoding='utf8'))

    def test_graph_full_counts_and_m2_schema(self):
        self.assertEqual((len(self.before['nodes']),len(self.before['relationships'])),(12247,13322))
        self.assertEqual((len(self.after['nodes']),len(self.after['relationships'])),(12249,13322))
        self.assertEqual(len(self.old),17726);self.assertEqual(len(self.new),17726)
        self.assertEqual(set(self.old),set(self.new))

    def test_all_source_records_unchanged_except_event_id_and_status(self):
        ids={x['relation_id'] for x in self.audit['relations']}
        self.assertEqual(len(ids),11)
        for rid in self.old:
            left=self.old[rid].copy();right=self.new[rid].copy()
            if rid in ids:
                for k in ('subject_id','object_id','subject_resolution','object_resolution'):
                    left.pop(k,None);right.pop(k,None)
            self.assertEqual(left,right,rid)

    def test_mentions_and_nodes_split_without_deletion(self):
        old=read_rows(INPUT,'nonperson_mention_mappings');new=read_rows(OUTPUT,'nonperson_mention_mappings')
        self.assertEqual(len(old),len(new))
        changes=[(a,b) for a,b in zip(old,new) if a!=b]
        self.assertEqual(len(changes),10)
        self.assertEqual({a['new_entity_id'] for a,b in changes},{OLD})
        self.assertEqual({b['new_entity_id'] for a,b in changes},{E24,E25,E26})
        self.assertEqual([sum(b['new_entity_id']==ident for a,b in changes) for ident in [E24,E25,E26]],[2,1,7])
        old_ids={n['id'] for n in self.before['nodes']};new_ids={n['id'] for n in self.after['nodes']}
        self.assertEqual(old_ids-new_ids,{OLD});self.assertEqual(new_ids-old_ids,{E24,E25,E26})

    def test_source_map_and_reviewed_event_no_false_bus_path(self):
        for group,identity in [('2024',E24),('2025',E25),('2026',E26)]:
            rows=[x for x in self.audit['relations'] if x['event_group']==group]
            self.assertEqual(len(rows),{'2024':3,'2025':1,'2026':7}[group])
            self.assertTrue(all(x['after_id']==identity for x in rows))
        false_a=('AUTO-01bc1ba56fc455cef2817011',OLD,'PARTICIPATES_IN')
        def has(graph,source,target,predicate):
            return any(r['start']==source and r['end']==target and r['type']==predicate for r in graph['relationships'])
        foundation='AUTO-01bc1ba56fc455cef2817011';busan='AUTO-9c150b9c080a626bcbaa5af7'
        self.assertTrue(has(self.before,foundation,OLD,'PARTICIPATES_IN'))
        self.assertTrue(has(self.before,OLD,busan,'EVENT_IN_PLACE'))
        self.assertTrue(has(self.after,foundation,E24,'PARTICIPATES_IN'))
        self.assertFalse(has(self.after,foundation,E26,'PARTICIPATES_IN'))
        self.assertTrue(has(self.after,E26,busan,'EVENT_IN_PLACE'))


if __name__=='__main__': unittest.main()
