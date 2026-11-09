import unittest
from bulsae.graphrag.web_server import present_response


class PresentationTests(unittest.TestCase):
    def test_context_paragraphs_keep_actual_relationship_and_document_ids(self):
        quote = '가온 홍길동 대표가 미래 포럼에서 해외 진출 계획을 발표했다.'
        path = {'company':'가온', 'person':'홍길동', 'event':'미래 포럼', 'document_id':'TEST-DOC',
                'url':'https://example.org', 'title':'시험 기사', 'work_evidence':quote, 'event_evidence':quote,
                'work_observation_id':'TEST-WORK', 'event_observation_id':'TEST-EVENT'}
        result = {'status':'answered', 'paths':[path], 'analysis':{'role':'ceo'},
                  'evidence':[path], 'claims':[{'heading':'해외 진출 계획 발표', 'text':'홍길동 대표는 해외 진출 계획을 발표했어요.',
                      'exact_quote':quote, 'evidence_index':0}], 'supported':[0]}
        response = present_response(result)
        self.assertIn('홍길동', response['sections'][0]['text'])
        self.assertIn('미래 포럼', response['sections'][0]['text'])
        self.assertEqual(response['sections'][1]['heading'], '해외 진출 계획 발표')
        self.assertEqual(response['sources'][0]['document_id'], 'TEST-DOC')
        self.assertEqual({c['observation_id'] for c in response['trace']['connections']}, {'TEST-WORK','TEST-EVENT'})
        self.assertEqual(response['trace']['hops'], 2)

    def test_structured_record_does_not_invent_news_or_relationship(self):
        response = present_response({'status':'answered', 'answer':'기본 정보', 'trace_kind':'company_info',
            'structured_sources':[{'document_id':'COMPANY-TEST', 'url':'https://example.org', 'title':'기업정보',
                'evidence':'화장품 제조', 'source_file':'company_info.jsonl'}]})
        self.assertEqual(response['trace']['connections'], [])
        self.assertEqual(response['trace']['hops'], 0)
        self.assertEqual(response['sources'][0]['document_id'], 'COMPANY-TEST')

    def test_only_accepted_claims_are_presented_and_sources_deduplicated(self):
        result = {'status': 'answered', 'claims': [
            {'text': '가온이 나래에 공급했어요.', 'exact_quote': '가온이 나래에 공급했다.', 'evidence_index': 0},
            {'text': '가온이 나래에 공급했어요.', 'exact_quote': '가온이 나래에 공급했다.', 'evidence_index': 0},
            {'text': '검사에서 탈락한 주장', 'exact_quote': '없음', 'evidence_index': 0}],
            'supported': [0, 1], 'evidence': [{'document_id': 'TEST', 'url': 'https://example.org', 'title': '시험 기사'}]}
        response = present_response(result)
        self.assertEqual(len(response['sections']), 1)
        self.assertEqual(len(response['sources']), 1)
        self.assertEqual(len(response['sources'][0]['quotes']), 1)
        self.assertNotIn('탈락', response['answer'])

    def test_failure_never_displays_rejected_candidates(self):
        result = {'status': 'insufficient_evidence', 'answer': '근거가 부족해요.',
                  'supported': [0], 'claims': [{'text': '표시하면 안 됨'}]}
        self.assertEqual(present_response(result)['sections'], [])

    def test_repeated_caption_and_overlapping_lines_appear_once(self):
        quote = '홍길동 가온 대표가 시험 행사에 참석했다.'
        row = {'company': '가온', 'person': '홍길동', 'event': '시험 행사',
               'document_id': 'TEST', 'url': 'https://example.org',
               'work_evidence': f'![{quote}](https://example.org/photo.jpg)\n{quote}',
               'event_evidence': quote}
        response = present_response({'status': 'answered', 'paths': [row], 'analysis': {'role': 'ceo'}})
        self.assertEqual(response['sources'][0]['quotes'], [quote])

    def test_event_groups_and_identical_evidence_are_combined(self):
        row = {'company': '가온', 'person': '홍길동', 'event': '시험 행사',
               'document_id': 'TEST', 'url': 'https://example.org', 'title': '시험 기사',
               'work_evidence': '홍길동 가온 대표가 시험 행사에 참석했다.',
               'event_evidence': '홍길동 가온 대표가 시험 행사에 참석했다.'}
        response = present_response({'status': 'answered', 'paths': [row, row], 'analysis': {'role': 'ceo'}})
        self.assertEqual(len(response['sections']), 1)
        self.assertEqual(len(response['sources'][0]['quotes']), 1)
        self.assertEqual(response['trace']['hops'], 2)
        self.assertNotIn('검토 전', response['answer'])
