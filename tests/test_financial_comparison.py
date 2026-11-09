import json
import unittest

from bulsae.graphrag.financial_comparison import compare_financials, financial_request


def row(name, revenue, profit):
    return {'name':name, 'year':2025, 'period':'연간', 'scope':'개별',
            'revenue':revenue, 'operating_profit':profit,
            'source_json':json.dumps([{'source_name':'공시', 'original_url':'https://example.org'}])}


class FinancialComparisonTests(unittest.TestCase):
    def test_comparison_uses_same_period_scope_and_correct_difference(self):
        result = compare_financials('2025년 매출과 영업이익 비교', ['가온','나온'],
                                    [row('가온',100,20),row('나온',40,10)])
        self.assertEqual(result['status'],'answered')
        self.assertIn('60원으로, 가온 쪽이 더 커요',result['answer'])
        self.assertIn('연간 개별',result['answer'])

    def test_missing_or_incompatible_record_does_not_compare(self):
        a = row('가온',100,20)
        b = {**row('나온',40,10), 'scope':'연결'}
        self.assertEqual(compare_financials('매출 비교',['가온','나온'],[a,b])['status'], 'insufficient_evidence')

    def test_no_yearly_change_from_one_year(self):
        for question in ('2024년과 2025년 매출 비교', '2025년 전년 대비 매출 비교', '매출 변화와 전략 비교'):
            self.assertIsNotNone(financial_request(question)[1])

    def test_profit_margin_is_not_mistaken_for_profit(self):
        self.assertIsNotNone(financial_request('영업이익률을 비교해줘')[1])
        self.assertIsNotNone(financial_request('매출과 순이익을 비교해줘')[1])
        self.assertIsNotNone(financial_request('올해 매출 비교')[1])
        self.assertIsNotNone(financial_request('2025년 연결 매출 비교')[1])


if __name__ == '__main__':
    unittest.main()
