"""M6 매핑의 출처 보존·시점 분리·스키마 거부를 검사한다."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mapper import build_graph


def write_zip(path, nodes, news, structured, chunks=None):
    with zipfile.ZipFile(path, 'w') as z:
        for name, rows in [('nodes_in_scope.jsonl', nodes), ('news_relations_in_scope.jsonl', news),
                           ('structured_disclosure_relations.jsonl', structured), ('disclosure_chunks.jsonl', chunks or [])]:
            z.writestr('results/' + name, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
        z.writestr('results/summary.json', json.dumps({'in_scope_nodes': len(nodes),
                   'in_scope_news_relations': len(news), 'structured_and_disclosure_relations': len(structured)}))


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / 'source.zip'
        self.nodes = [{'entity_id': 'a', 'type': 'Company', 'name': '가'},
                      {'entity_id': 'b', 'type': 'Company', 'name': '나'}]
        self.rows = [self.rel('r1', '2025-12-31'), self.rel('r2', '2025-12-31'),
                     self.rel('r3', '2026-03-31')]

    def tearDown(self):
        self.tmp.cleanup()

    def rel(self, rid, date):
        return {'relation_id': rid, 'subject_id': 'a', 'object_id': 'b', 'predicate': 'OWNS_STAKE',
                'attributes': {'as_of_date': date, 'value_number': 38.1, 'unit': '%'},
                'source_kind': 'news', 'review_status': '검토필요',
                'evidence': {'document_id': 'doc-' + rid, 'chunk_id': 'chunk-' + rid,
                             'quote': '근거 ' + rid, 'source_metadata': {'source_url': 'https://example.com/' + rid}}}

    def test_duplicate_evidence_is_kept_and_distinct_dates_split(self):
        write_zip(self.file, self.nodes, self.rows, [])
        result = build_graph(self.file)
        self.assertEqual(len(result['relationships']), 2)
        combined = next(x for x in result['relationships'] if x['properties']['source_count'] == 2)
        self.assertEqual({x['relation_id'] for x in json.loads(combined['properties']['sources_json'])}, {'r1', 'r2'})
        self.assertEqual(len(combined['properties']['source_urls']), 2)
        self.assertEqual(result['summary']['evidence_records'], 3)
        self.assertEqual(result, build_graph(self.file))

    def test_invalid_direction_fails_before_load(self):
        self.rows[0]['predicate'] = 'HOLDS_POSITION'
        write_zip(self.file, self.nodes, self.rows, [])
        with self.assertRaisesRegex(ValueError, 'M2에 맞지 않는 연결'):
            build_graph(self.file)

    def test_attribute_conflicts_never_chosen(self):
        self.nodes[0]['attribute_variants'] = [{'value_number': 1, 'unit': '원'}, {'value_number': 2, 'unit': '원'}]
        write_zip(self.file, self.nodes, [], [])
        props = build_graph(self.file)['nodes'][0]['properties']
        self.assertNotIn('value_number', props)
        self.assertEqual(props['unit'], '원')
        self.assertIn('value_number', props['conflicting_attribute_keys'])
        self.assertEqual(len(json.loads(props['m5_record_json'])['attribute_variants']), 2)

    def test_disclosure_footnote_and_source_are_preserved(self):
        row = self.rows[0].copy()
        row['source_kind'] = 'disclosure'
        row['evidence'] = {'document': {'id': 'report', 'url': 'https://example.com/report'},
                           'quote': '표 행', 'related_note_chunk_ids': ['note1']}
        write_zip(self.file, self.nodes, [], [row], [{'chunk_id': 'note1', 'text': '원문 주석'}])
        props = build_graph(self.file)['relationships'][0]['properties']
        self.assertEqual(json.loads(props['disclosure_notes_json'])['note1']['text'], '원문 주석')
        self.assertEqual(json.loads(props['sources_json'])[0]['evidence']['quote'], '표 행')

    def test_missing_footnote_causes_failure(self):
        row = self.rows[0].copy()
        row['source_kind'] = 'disclosure'
        row['evidence'] = {'related_note_chunk_ids': ['missing']}
        write_zip(self.file, self.nodes, [], [row])
        with self.assertRaisesRegex(ValueError, '주석 청크'):
            build_graph(self.file)


if __name__ == '__main__':
    unittest.main()
