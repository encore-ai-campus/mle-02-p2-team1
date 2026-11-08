"""실제 AuraDB에 접속하지 않는 M7 조회 실행기 테스트."""
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from queries import get_queries
from run_m7 import STATS, run_query, write_summary


class FakeSession:
    def __init__(self, rows=None, fail=False):
        self.rows = rows or []
        self.fail = fail
        self.parameters = None
    def execute_read(self, function, query, params):
        self.parameters = params
        if self.fail:
            raise ValueError('조회 실패 예시')
        return self.rows


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.args = Namespace(dataset_id='test_dataset', sample_limit=2,
                              person='서경배', company_id='COMPANY-AMOREPACIFIC')
    def test_ten_queries_are_scoped_and_use_read_only_patterns(self):
        queries = get_queries()
        self.assertEqual([q['id'] for q in queries], [f'CQ{i:02}' for i in range(1, 11)])
        for query in STATS + queries:
            self.assertIn('$dataset_id', query['cypher'])
            for term in ('CREATE ', 'DELETE ', 'MERGE ', ' SET ', 'REMOVE '):
                self.assertNotIn(term, query['cypher'].upper())
        for query in queries:
            self.assertIn('$sample_limit', query['cypher'])
    def test_sample_limit_and_user_parameters(self):
        session = FakeSession([{'x': 1}, {'x': 2}, {'x': 3}])
        result = run_query(session, get_queries()[7], self.args)
        self.assertEqual(result['returned_rows'], 2)
        self.assertTrue(result['has_more_than_sample'])
        self.assertEqual(session.parameters['sample_limit'], 3)
        self.assertEqual(session.parameters['person_name'], '서경배')
    def test_empty_and_error_are_distinct(self):
        empty = run_query(FakeSession(), get_queries()[0], self.args)
        failed = run_query(FakeSession(fail=True), get_queries()[1], self.args)
        self.assertEqual(empty['status'], 'success')
        self.assertEqual(empty['returned_rows'], 0)
        self.assertEqual(failed['status'], 'error')
        with TemporaryDirectory() as path:
            write_summary(Path(path), [empty, failed], 'test')
            text = (Path(path)/'m7_summary.md').read_text(encoding='utf8')
            self.assertIn('조회 성공', text)
            self.assertIn('오류: ValueError', text)


if __name__ == '__main__': unittest.main()
