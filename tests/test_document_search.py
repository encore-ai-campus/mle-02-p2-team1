import unittest
from unittest.mock import patch
from types import SimpleNamespace

from bulsae.graphrag.document_search import fetch_evidence, SEARCH_QUERY, AnswerClaim, validate_answer_claims, source_matches_document, company_event_supported
from bulsae.graphrag.document_search import review_claims, ClaimDecision, ClaimDecisions


class DocumentSearchTests(unittest.TestCase):
    def test_search_passes_parameters_and_traverses_identity_links(self):
        class Record:
            def data(self):
                return {'document_id': 'NEWS-1', 'through_provisional_identity': True}
        with patch('bulsae.graphrag.document_search.query_readonly', return_value=[Record()]) as query:
            result = fetch_evidence(object(), ' 김승환 ', 'person', 10)
        self.assertEqual(result[0]['document_id'], 'NEWS-1')
        self.assertEqual(query.call_args.kwargs['name'], '김승환')
        self.assertIn('NORMALIZED_AS', SEARCH_QUERY)
        self.assertIn('document-kg-v1', SEARCH_QUERY)

    def test_invalid_input_is_rejected(self):
        for name, kind, limit in [('', 'person', 1), ('김승환', 'event', 1), ('김승환', 'person', 501)]:
            with self.assertRaises(ValueError):
                fetch_evidence(None, name, kind, limit)

    def test_answer_requires_verbatim_source_sentence(self):
        rows = [{'evidence':'김승환 대표가 전략을 발표했다.', 'document_id':'NEWS-1', 'url':'https://example.org', 'source_verified':True}]
        good = AnswerClaim(text='전략을 발표했다', evidence_index=0, exact_quote='전략을 발표했다')
        wrong_quote = AnswerClaim(text='확인되지 않은 내용', evidence_index=0, exact_quote='존재하지 않는 근거')
        wrong_index = AnswerClaim(text='전략을 발표했다', evidence_index=1, exact_quote='전략을 발표했다')
        validated = validate_answer_claims([good,wrong_quote,wrong_index], rows)
        self.assertEqual([claim.text for claim in validated], ['전략을 발표했다'])

    def test_source_is_verified_against_stored_document(self):
        self.assertTrue(source_matches_document({'evidence_json':'[{"text":"정확한 근거"}]'}, '기사의 정확한 근거입니다'))
        self.assertFalse(source_matches_document({'evidence_json':'[{"text":"다른 근거"}]'}, '기사 본문'))

    def test_event_year_must_not_be_combined_with_relative_day(self):
        quote = '김승환 대표는 지난 11일 2026 인베스터 데이에서 전략을 발표했다.'
        row = {'evidence': quote, 'document_id': 'TEST', 'url': 'https://example.org', 'source_verified': True}
        claim = AnswerClaim(text='김승환 대표는 2026년 11일 행사에서 전략을 발표했어요.', evidence_index=0, exact_quote=quote)
        self.assertEqual(validate_answer_claims([claim], [row]), [])

    def test_explanation_can_differ_but_quote_must_match(self):
        rows = [{'evidence': '가온은 나래에 원료를 공급했다.', 'document_id': 'NEWS-TEST',
                 'url': 'https://example.org', 'source_verified': True}]
        claim = AnswerClaim(text='가온이 나래에 원료를 공급했어요.', evidence_index=0,
                            exact_quote='가온은 나래에 원료를 공급했다.')
        self.assertEqual(validate_answer_claims([claim], rows)[0].text, claim.text)
        self.assertEqual(validate_answer_claims([claim.model_copy(update={'exact_quote': '나래가 가온에 원료를 공급했다.'})], rows), [])
        self.assertEqual(validate_answer_claims([claim], [{**rows[0], 'source_verified': False}]), [])

    def test_review_rejects_any_identified_unsupported_detail(self):
        decisions = ClaimDecisions(decisions=[
            ClaimDecision(claim_index=0, unsupported_details=['원문에 없는 인수 목적'], supported=True),
            ClaimDecision(claim_index=1, unsupported_details=[], supported=True)])
        client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **_: SimpleNamespace(output_parsed=decisions)))
        claims = [AnswerClaim(text='확대 목적으로 인수했어요.', evidence_index=0, exact_quote='가온이 나래를 인수했다.'),
                  AnswerClaim(text='가온이 나래를 인수했어요.', evidence_index=0, exact_quote='가온이 나래를 인수했다.')]
        self.assertEqual(review_claims(client, 'test', '인수 내용을 알려줘', claims, [{}]), {1})

    def test_announced_plan_cannot_become_ongoing_action(self):
        quote = '가온은 글로벌 사업을 재편하겠다고 밝혔다.'
        row = {'evidence': quote, 'source_verified': True, 'document_id': 'TEST', 'url': 'https://example.org'}
        bad = AnswerClaim(text='가온은 글로벌 사업을 재편하고 있다.', evidence_index=0, exact_quote=quote)
        good = bad.model_copy(update={'text': '가온은 글로벌 사업을 재편할 계획이다.'})
        result = validate_answer_claims([bad, good], [row])
        self.assertEqual([c.text for c in result], ['가온은 글로벌 사업을 재편할 계획이에요.'])

    def test_each_segment_target_cannot_become_combined_target(self):
        quote = '더마와 헤어 각 부문 매출 1조원을 목표로 한다.'
        row = {'evidence': quote, 'source_verified': True, 'document_id': 'TEST', 'url': 'https://example.org'}
        bad = AnswerClaim(text='더마와 헤어 매출 1조원을 목표로 해요.', evidence_index=0, exact_quote=quote)
        self.assertEqual(validate_answer_claims([bad], [row]), [])

    def test_company_event_needs_company_itself_to_participate(self):
        self.assertTrue(company_event_supported('가온', '박람회', '가온이 박람회에 참여했다.'))
        self.assertFalse(company_event_supported('가온', '박람회', '가온 회장이 박람회에 참석했다.'))
        self.assertFalse(company_event_supported('가온', '박람회', '가온그룹이 박람회에 참여했다.'))
        self.assertFalse(company_event_supported('가온', '박람회', '가온이 다른 행사에 참여했다.'))


if __name__ == '__main__':
    unittest.main()
