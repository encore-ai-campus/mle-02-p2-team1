import unittest

from bulsae.graphrag.entity_resolution import choose_entity, mention_spans


class EntityResolutionTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {'name':'김승환', 'kind':'person', 'legal_name':None},
            {'name':'서경배', 'kind':'person', 'legal_name':None},
            {'name':'아모레퍼시픽', 'kind':'company', 'legal_name':'주식회사 아모레퍼시픽'},
            {'name':'이니스프리', 'kind':'company', 'legal_name':'주식회사 이니스프리'},
        ]

    def test_person_and_company_context_for_event(self):
        result = choose_entity('김승환 아모레퍼시픽 대표가 참석한 행사는?', self.records)
        self.assertEqual((result['name'], result['kind'], result['company_context']),
                         ('김승환','person','아모레퍼시픽'))

    def test_company_and_legal_name(self):
        result = choose_entity('주식회사 아모레퍼시픽의 관계를 알려줘', self.records)
        self.assertEqual((result['name'],result['kind']), ('아모레퍼시픽','company'))

    def test_two_people_require_clarification(self):
        result = choose_entity('김승환과 서경배를 비교해줘', self.records)
        self.assertEqual(result['status'], 'ambiguous')

    def test_does_not_match_prefix_of_different_company(self):
        self.assertEqual(mention_spans('아모레퍼시픽그룹은?', '아모레퍼시픽'), [])
        self.assertEqual(choose_entity('아모레퍼시픽그룹은?', self.records)['status'], 'not_found')

    def test_missing_entity_requires_clarification(self):
        self.assertEqual(choose_entity('대표가 누구야?', self.records)['status'], 'not_found')

    def test_two_companies_are_selected_for_comparison(self):
        result = choose_entity('아모레퍼시픽과 이니스프리의 매출을 비교해줘', self.records)
        self.assertEqual(result['status'], 'resolved_compare')
        self.assertEqual([e['name'] for e in result['entities']], ['아모레퍼시픽','이니스프리'])
        result = choose_entity('이니스프리랑 아모레퍼시픽 중 매출이 더 높은 회사는?', self.records)
        self.assertEqual(result['status'], 'resolved_compare')

    def test_comparison_without_second_company_does_not_answer_one(self):
        result = choose_entity('아모레퍼시픽과 다른 기업을 비교해줘', self.records)
        self.assertEqual(result['status'], 'comparison_needs_names')


if __name__ == '__main__':
    unittest.main()
