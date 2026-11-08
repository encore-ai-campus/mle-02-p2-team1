"""DB를 흉내 내며 재실행과 출처 검증 로직을 확인한다. 실제 Neo4j 시험은 아니다."""
import json
import re
import unittest

import load_m6


class Result:
    def __init__(self, row): self.row = row
    def single(self): return self.row


class FakeTransaction:
    def __init__(self):
        self.nodes = {}
        self.relationships = {}

    def run(self, query, **kw):
        if 'MERGE (n:B_M6Entity' in query:
            label = re.search(r'SET n:(B_\w+)', query).group(1)
            for row in kw['rows']:
                props = dict(row['properties'])
                props.update(uid=row['uid'], dataset_id=kw['dataset'], input_hash=kw['fingerprint'])
                self.nodes[row['uid']] = {'uid': row['uid'], 'input_hash': kw['fingerprint'],
                                          'labels': ['B_M6Entity', label], 'properties': props}
            return Result({'count': len(kw['rows'])})
        if 'MERGE (s)-[r:' in query:
            typ = re.search(r'MERGE \(s\)-\[r:(B_\w+)', query).group(1)
            count = 0
            for row in kw['rows']:
                if row['start_uid'] not in self.nodes or row['end_uid'] not in self.nodes:
                    continue
                props = dict(row['properties'])
                props.update(uid=row['uid'], dataset_id=kw['dataset'], input_hash=kw['fingerprint'])
                self.relationships[row['uid']] = {'uid': row['uid'], 'input_hash': kw['fingerprint'],
                    'sources_json': props['sources_json'], 'source_count': props['source_count'],
                    'start_uid': row['start_uid'], 'end_uid': row['end_uid'],
                    'relation_type': typ, 'properties': props}
                count += 1
            return Result({'count': count})
        raise AssertionError('unexpected query')


def make_graph():
    return {'nodes': [
        {'id': 'A', 'labels': ['Company'], 'properties': {'name': 'A'}},
        {'id': 'B', 'labels': ['Company'], 'properties': {'name': 'B'}}],
        'relationships': [{'id': 'R', 'start': 'A', 'end': 'B', 'type': 'OWNS_STAKE',
            'properties': {'sources_json': json.dumps([{'id': 'article-a'}, {'id': 'article-b'}]),
                           'source_count': 2, 'as_of_date': '2026-03-31'}}]}


def simulate_write(tx, graph, dataset, fingerprint):
    for node in graph['nodes']:
        load_m6.write_nodes(tx, node['labels'][0], [{'uid':dataset+'|'+node['id'],
            'properties':node['properties']}], dataset, fingerprint)
    for rel in graph['relationships']:
        load_m6.write_relations(tx, rel['type'], [{'uid':dataset+'|'+rel['id'],
            'start_uid':dataset+'|'+rel['start'], 'end_uid':dataset+'|'+rel['end'],
            'properties':rel['properties']}], dataset, fingerprint)


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.graph = make_graph()
        self.fingerprint = load_m6.graph_fingerprint(self.graph)
        self.tx = FakeTransaction()

    def verify(self):
        return load_m6.verify_contents(list(self.tx.nodes.values()),
            list(self.tx.relationships.values()), self.graph, 'test', self.fingerprint)

    def test_two_runs_do_not_duplicate_or_lose_sources_in_fake_db(self):
        load_m6.validate_graph(self.graph)
        simulate_write(self.tx, self.graph, 'test', self.fingerprint)
        first = self.verify()
        simulate_write(self.tx, self.graph, 'test', self.fingerprint)
        self.assertEqual(first, self.verify())
        self.assertEqual(first, {'nodes': 2, 'relationships': 1, 'source_records': 2})

    def test_tampered_source_is_rejected(self):
        simulate_write(self.tx, self.graph, 'test', self.fingerprint)
        self.tx.relationships['test|R']['sources_json'] = '[]'
        with self.assertRaises(ValueError): self.verify()

    def test_reversed_relationship_is_rejected(self):
        simulate_write(self.tx, self.graph, 'test', self.fingerprint)
        self.tx.relationships['test|R']['end_uid'] = 'test|A'
        with self.assertRaises(ValueError): self.verify()

    def test_unknown_type_and_missing_endpoint_are_rejected(self):
        self.graph['relationships'][0]['type'] = 'UNKNOWN'
        with self.assertRaises(ValueError): load_m6.validate_graph(self.graph)
        self.graph['relationships'][0]['type'] = 'OWNS_STAKE'
        self.graph['relationships'][0]['end'] = 'MISSING'
        with self.assertRaises(ValueError): load_m6.validate_graph(self.graph)


if __name__ == '__main__': unittest.main()
