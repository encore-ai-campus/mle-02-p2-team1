"""Real UI → service → LangGraph with only external boundaries replaced."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from bulsae.graphrag.financial_comparison import compare_financials
from bulsae.graphrag.web_server import present_response

APP = Path(__file__).resolve().parents[1] / 'streamlit_app.py'


class UnifiedServiceTests(unittest.TestCase):
    def test_company_legal_representative_is_not_event_attendance(self):
        from bulsae.graphrag.graphs import executive_context_supported
        self.assertFalse(executive_context_supported('가온(대표 김승환)이 학술대회에서 연구를 발표했다.'))
        self.assertTrue(executive_context_supported('가온(대표 김승환)의 김승환 대표가 행사에서 발언했다.'))
        self.assertTrue(executive_context_supported('김승환 가온 대표가 행사에서 전략을 발표했다.'))

    def test_similar_paragraphs_with_distinct_information_are_not_dropped(self):
        from bulsae.graphrag.web_server import merge_repeated_sections
        first = {'text':'가온은 해외 사업 전략을 발표했어요.', 'section_type':'basic', 'sources':[1]}
        second = {**first, 'text':first['text']+' 유통 채널 확대 계획도 설명했어요.', 'sources':[2]}
        shown = merge_repeated_sections([first, second, {**first, 'sources':[3]}])
        self.assertEqual(len(shown), 2)
        self.assertEqual(shown[0]['sources'], [1,3])
        self.assertIn('유통 채널', shown[1]['text'])

    def test_ui_calls_shared_service_and_actual_langgraph(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch('bulsae.graphrag.web_server.ROOT', Path(directory)))
            driver = stack.enter_context(patch('bulsae.graphrag.pipeline.driver'))
            stack.enter_context(patch('bulsae.graphrag.entity_resolution.resolve_question',
                return_value={'status':'resolved', 'name':'가온', 'kind':'company'}))
            company = stack.enter_context(patch('bulsae.graphrag.company_information.fetch_company_business',
                return_value=[{'name':'가온', 'company_id':'TEST', 'business':'가온은 화장품을 제조해요.',
                              'sources':json.dumps({'main_business':[{'original_url':'https://example.org'}]})}]))
            stack.enter_context(patch('bulsae.graphrag.document_search.fetch_evidence', return_value=[]))
            stack.enter_context(patch('bulsae.graphrag.document_fallback.fetch_document_evidence', return_value=[]))
            api = stack.enter_context(patch('openai.OpenAI'))
            compose = stack.enter_context(patch('bulsae.graphrag.related_analysis.compose_final_answer',
                return_value={'sections':[], 'diagnostics':{'status':'no_summary'}}))
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value('가온은 어떤 사업을 하는 회사야?')
            app.button(key='submit_question').click().run()
            self.assertFalse(app.exception)
            response = app.session_state['result']
            self.assertEqual(response['status'], 'answered')
            self.assertEqual(response['trace']['executed_nodes'], ['identify','company_info','enrich','finalize'])
            self.assertEqual(response['lead'], '가온은 화장품을 제조해요.')
            self.assertEqual(sum(m.value == response['lead'] for m in app.markdown), 1)
            self.assertEqual(response['sections'], [])
            self.assertTrue(response['record_saved'])
            company.assert_called_once_with(driver.return_value.__enter__.return_value, '가온')
            compose.assert_called_once()
            self.assertEqual(compose.call_args.args[2], '가온은 어떤 사업을 하는 회사야?')
            api.return_value.responses.parse.assert_not_called()
            for key in ('question','status','answer','lead','sections','financial_cards','sources','trace'):
                self.assertIn(key, response)

    def test_metric_cards_remove_only_duplicate_amount_lines_keep_comparison(self):
        rows = [dict(name=name, financial_id='F-'+name, year=2025, period='연간', scope='개별',
                     revenue=value, operating_profit=-10, source_json=json.dumps([{'original_url':'https://example.org/'+name}]))
                for name,value in [('가온', 1234), ('나래', 234)]]
        result = compare_financials('가온과 나래의 2025년 매출과 영업이익 비교', ['가온','나래'], rows)
        shown = present_response(result)
        self.assertEqual(len(shown['financial_cards']),4)
        visible = shown['lead'] + '\n'.join(s['text'] for s in shown['sections'])
        self.assertNotIn('매출액: 1,234원',visible)
        self.assertIn('1,000원',visible)
        self.assertIn('영업이익은 두 기업이 같습니다',visible)
        self.assertIn('매출액: 1,234원',shown['answer'])
        self.assertEqual(shown['financial_cards'][1]['value'],-10)
        for card in shown['financial_cards']:
            self.assertEqual((card['year'],card['period'],card['scope']), (2025,'연간','개별'))
            self.assertIn(card['source_number'], [s['number'] for s in shown['sources']])
        self.assertTrue(all(s['section_type'] == 'basic' for s in shown['sections']))

    def test_missing_financial_value_does_not_create_card(self):
        shown=present_response({'status':'answered','answer':'확인한 사업 정보', 'structured_sources':[
            {'document_id':'F', 'url':'https://example.org', 'evidence':'값 없음',
             'financial_metrics':{'revenue':None,'operating_profit':True}}]})
        self.assertEqual(shown['financial_cards'],[])
