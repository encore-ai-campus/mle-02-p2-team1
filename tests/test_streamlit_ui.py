import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'streamlit_app.py'


class StreamlitUITest(unittest.TestCase):
    def test_failure_logs_error_type_without_exception_message(self):
        with patch('bulsae.graphrag.streamlit_ui.run_question', side_effect=RuntimeError('sensitive details')):
            with self.assertLogs('bulsae.graphrag.streamlit_ui', level='ERROR') as logged:
                app = AppTest.from_file(str(APP)).run()
                app.text_area[0].set_value('시험 질문')
                app.button(key='submit_question').click().run()
        self.assertIn('RuntimeError', logged.output[0])
        self.assertNotIn('sensitive details', logged.output[0])
        self.assertFalse(app.exception)

    def test_company_overview_order_and_bounded_news(self):
        result={'question':'회사 소개','status':'answered','answer':'회사 소개','sources':[],'trace':{},
            'company_profiles':[{'name':'가온','fields':[{'label':'업종','value':'화장품'}],
                'business':'화장품 제조','recent_status':'found',
                'news':[{'heading':f'소식 {i}','text':f'기사 내용 {i}','published_at':'2026-11-05'} for i in range(4)]}],
            'sections':[{'heading':'의미','text':'자료에 기반한 해석','kind':'interpretation','section_type':'additional'}]}
        with patch('bulsae.graphrag.streamlit_ui.run_question',return_value=result):
            app=AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(result['question'])
            app.button(key='submit_question').click().run()
            headings=[s.value for s in app.subheader]
            self.assertEqual(headings[:3],['기업 한눈에 보기','주요 사업','최근 소식'])
            self.assertIn('소식 2',headings)
            self.assertNotIn('소식 3',headings)
            self.assertIn('✦ AI 통합분석',headings)
            self.assertFalse(app.exception)

    def test_combined_financial_and_event_answer_displays_both(self):
        result = {'question':'복합 질문','status':'partial_evidence','answer':'재무 및 행사 결과',
                  'sources':[],'trace':{},
                  'financial_cards':[{'company':'가온','label':'매출액','value':100,
                                      'year':2025,'period':'연간','scope':'개별'}],
                  'event_cards':[{'name':'투자자 행사','year':2025,'participants':['홍길동'],
                                  'description':'투자자 행사입니다.','activity':'전략을 발표했어요.','sources':[]}],
                  'sections':[{'heading':'확인하지 못한 항목','text':'추가 근거가 부족해요.', 'section_type':'basic'}]}
        with patch('bulsae.graphrag.streamlit_ui.run_question',return_value=result):
            app=AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(result['question'])
            app.button(key='submit_question').click().run()
            self.assertFalse(app.exception)
            self.assertIn('투자자 행사',[s.value for s in app.subheader])
            self.assertTrue(any('100원' in m.value for m in app.markdown))
            self.assertTrue(any('추가 근거가 부족해요' in m.value for m in app.markdown))

    def test_session_cache_reuses_only_exact_questions_without_mutating_sources(self):
        from bulsae.graphrag.streamlit_ui import run_question
        state = {}
        response = {'status': 'answered', 'answer': '답변', 'trace': {}, 'sources': [{'number': 1}]}
        with patch('bulsae.graphrag.streamlit_ui.st.session_state', state), \
             patch('bulsae.graphrag.web_server.answer_question', return_value=response) as backend, \
             patch('bulsae.graphrag.streamlit_ui.time.monotonic', return_value=100):
            run_question('가온 매출')
            cached = run_question('가온 매출')
            self.assertEqual(backend.call_count, 1)
            self.assertTrue(cached['trace']['session_cache']['hit'])
            cached['sources'].clear()
            self.assertEqual(len(run_question('가온 매출')['sources']), 1)
            run_question('가온 영업이익')
            self.assertEqual(backend.call_count, 2)
            self.assertNotIn('session_cache', response['trace'])

    def test_session_cache_expires_and_does_not_store_failed_answers(self):
        from bulsae.graphrag.streamlit_ui import run_question
        with patch('bulsae.graphrag.streamlit_ui.st.session_state', {}), \
             patch('bulsae.graphrag.web_server.answer_question', return_value={'status': 'answered'}) as backend, \
             patch('bulsae.graphrag.streamlit_ui.time.monotonic', side_effect=[0, 0, 301, 301]):
            run_question('가온 매출')
            run_question('가온 매출')
            self.assertEqual(backend.call_count, 2)
        with patch('bulsae.graphrag.streamlit_ui.st.session_state', {}), \
             patch('bulsae.graphrag.web_server.answer_question', return_value={'status': 'error'}) as backend:
            run_question('가온 매출')
            run_question('가온 매출')
            self.assertEqual(backend.call_count, 2)

    def test_financial_report_is_vertical_facts_then_ai_analysis(self):
        result={'question':'가온 2025년 매출 분석','status':'answered','answer':'저장할 답변','sources':[], 'trace':{},
            'financial_cards':[{'company':'가온','label':'매출액','value':123456789,'year':2025,'period':'연간','scope':'개별'}],
            'sections':[
                {'heading':'2025년 매출','text':'가온의 2025년 연간 개별 기준 매출은 1억 원이에요.','kind':'reported_fact'},
                {'heading':'연결 사업 · 브랜드 성장','text':'- 회사는 해외 판매가 늘었다고 밝혔어요.\n- 신규 채널을 확보했어요.','kind':'company_explanation'},
                {'heading':'매출 성장의 배경','text':'판매 접점 확대가 기여했을 가능성이 있어요.','kind':'interpretation','section_type':'additional'}]}
        with patch('bulsae.graphrag.streamlit_ui.run_question',return_value=result):
            app=AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(result['question'])
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual([s.value for s in app.subheader][:3],['재무 한눈에 보기','매출 주요 요인','✦ AI 통합분석'])
            texts=[m.value for m in app.markdown]
            self.assertIn('#### 브랜드 성장 (연결 사업 기준)',texts)
            self.assertIn('- 회사는 해외 판매가 늘었다고 밝혔어요.\n- 신규 채널을 확보했어요.',texts)
            self.assertIn('- 판매 접점 확대가 기여했을 가능성이 있어요.',texts)
            self.assertNotIn('#### 2025년 매출',texts)
            self.assertNotIn('LLM 분석',[s.value for s in app.subheader])
            self.assertFalse(any((b.key or '').startswith(('answer_card_', 'analysis_card_')) for b in app.get('flex_container')))

    def test_financial_amount_dedup_preserves_different_scope_and_comparisons(self):
        from bulsae.graphrag.streamlit_ui import repeats_financial_amount
        cards=[dict(company='가온',year=2025,period='연간',scope='개별',label='매출액')]
        self.assertTrue(repeats_financial_amount({'text':'가온의 2025년 연간 개별 기준 매출은 2조 6,537억 원이에요.'},cards))
        for text in ('가온의 2025년 연간 연결 기준 매출은 2조 원이에요.',
                     '가온의 2024년 연간 개별 기준 매출은 2조 원이에요.',
                     '가온의 2025년 연간 개별 기준 매출은 2조 원이에요. 전년보다 증가했어요.'):
            self.assertFalse(repeats_financial_amount({'text':text},cards))

    def test_final_analysis_has_one_notice_and_separate_cards(self):
        from bulsae.graphrag.related_analysis import INFERENCE_NOTICE
        result={'question':'기업 분석','status':'answered','answer':'요약과 분석','sources':[],'trace':{},
            'final_composed':True,'analysis_notice':INFERENCE_NOTICE,
            'sections':[{'heading':'핵심 요약','text':'확인한 사실','section_type':'basic'},
                        {'heading':'사업 의미','text':'사실을 바탕으로 한 해석','section_type':'additional'}]}
        with patch('bulsae.graphrag.streamlit_ui.run_question',return_value=result):
            app=AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(result['question'])
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual([x.value for x in app.caption].count(INFERENCE_NOTICE),1)
            self.assertIn('LLM 분석',[x.value for x in app.subheader])

    def test_korean_amount_preserves_every_digit(self):
        from bulsae.graphrag.streamlit_ui import korean_won
        for value, expected in ((2653725793231, '2조 6,537억 2,579만 3,231원'),
                                (100000000, '1억원'), (0, '0원'), (-12345, '−1만 2,345원')):
            with self.subTest(value=value):
                self.assertEqual(korean_won(value), expected)

    def test_financial_dashboard_shows_exact_sourced_values(self):
        result = {'question':'2025년 매출은?', 'status':'answered', 'answer':'매출 정보',
                  'sections':[{'text':'매출 정보'}], 'sources':[], 'trace':{},
                  'financial_cards':[{'company':'가온', 'label':'매출액', 'value':123456789,
                                      'year':2025, 'period':'연간', 'scope':'개별'}]}
        with patch('bulsae.graphrag.streamlit_ui.run_question', return_value=result):
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(result['question'])
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any('123,456,789원' in x.value and '1억 2,345만 6,789원' in x.value for x in app.markdown))
            self.assertIn('2025년 · 연간 · 개별', [x.value for x in app.caption])

    def test_loading_state_clears_after_failure_and_allows_retry(self):
        import streamlit as st
        states = []
        def fail(question):
            states.append(st.session_state['is_loading'])
            raise RuntimeError('test failure')
        with patch('bulsae.graphrag.streamlit_ui.run_question', side_effect=fail) as run:
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value('시험 질문')
            app.button[0].click().run()
            self.assertEqual(states, [True])
            self.assertFalse(app.session_state['is_loading'])
            self.assertFalse(app.button(key='retry_question').disabled)
            self.assertEqual(app.session_state['result']['status'], 'error')
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.text_area), 0)
            app.button(key='retry_question').click().run()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args, ('시험 질문',))

    def test_rejected_paragraphs_are_not_appended_to_report(self):
        from bulsae.graphrag.streamlit_ui import report_text
        result = {'status': 'answered', 'answer': '참석했어요.',
                  'trace': {'mode': 'executive_events', 'accepted_paragraphs': 0},
                  'sources': [{'number': 1, 'title': '기사', 'url': 'https://example.org',
                               'quotes': ['김 대표가 성장 전략을 발표했다.']}]}
        self.assertNotIn('김 대표가 성장 전략을 발표했다.', report_text(result))
        self.assertIn('https://example.org', report_text(result))

    def test_question_becomes_heading_and_result_survives_rerun_without_search(self):
        result = {
            'question': '기업 질문', 'status': 'answered', 'answer': '기업 설명입니다.',
            'sections': [{'heading': '기업의 주요 사업', 'text': '기업 설명입니다.', 'sources': [1]}],
            'sources': [{'number': 1, 'document_id': 'DOC-TEST', 'title': '근거 자료',
                         'url': 'https://example.com/source', 'quotes': ['확인된 근거']}],
            'trace': {'connections': [], 'hops': 0, 'mode': 'company_info'},
            'run_id': 'test',
        }
        with patch('bulsae.graphrag.streamlit_ui.run_question', return_value=result) as run:
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value('기업 질문')
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            run.assert_called_once_with('기업 질문')
            self.assertEqual(app.expander[0].label, '검색 과정과 근거 · 품질 확인')
            self.assertIn('기업의 주요 사업', [s.value for s in app.subheader])
            self.assertFalse(any(b.key.startswith('example_') for b in app.button if b.key))
            self.assertEqual(len(app.text_area), 0)
            self.assertTrue(any('<h1 class="question-title">기업 질문</h1>' in x.value and 'class="question-mark"' in x.value for x in app.markdown))
            self.assertFalse(any('기업 정보는 한눈에, 분석은 더 깊게' in x.value for x in app.markdown))
            self.assertFalse(any('흩어진 뉴스와 재무, 기업 간 관계를 연결해' in x.value for x in app.markdown))
            self.assertNotIn('이런 질문도 살펴보세요', [s.value for s in app.subheader])
            app.run()
            run.assert_called_once_with('기업 질문')
            self.assertIn('기업의 주요 사업', [s.value for s in app.subheader])

    def test_blank_question_does_not_search(self):
        with patch('bulsae.graphrag.streamlit_ui.run_question') as run:
            app = AppTest.from_file(str(APP)).run()
            app.button[0].click().run()
            run.assert_not_called()
            self.assertEqual(len(app.warning), 1)

    def test_basic_and_analysis_render_together_without_followups(self):
        result={'question':'가온은 어떤 회사야?', 'status':'answered', 'answer':'기본과 분석',
            'sections':[{'text':'가온은 제조 회사예요.','section_type':'basic'},
                {'heading':'회사가 밝힌 원인 · 유통 확대','text':'회사 측은 유통 확대가 성장 배경이라고 설명했어요.','section_type':'additional'},
                {'heading':'자료를 종합한 해석 · 사업 방향','text':'해외 기반을 넓히는 방향으로 해석할 수 있어요.','section_type':'additional'}],
            'trace':{},'sources':[]}
        with patch('bulsae.graphrag.streamlit_ui.run_question',return_value=result):
            app=AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value(result['question'])
            app.button[0].click().run()
            self.assertEqual(len(app.exception),0)
            self.assertEqual(sum(s.value == '관련 분석' for s in app.subheader), 1)
            self.assertEqual(len(app.text_area), 0)
            self.assertIn('가온은 제조 회사예요.', [x.value for x in app.markdown])
            self.assertFalse(any(b.key.startswith('example_') for b in app.button if b.key))
            self.assertIn('회사가 밝힌 원인 · 유통 확대',[s.value for s in app.subheader])
            self.assertIn('자료를 종합한 해석 · 사업 방향',[s.value for s in app.subheader])

    def test_new_question_resets_dashboard_and_searches_only_on_submit(self):
        result = {'status': 'answered', 'answer': '시험 답변', 'sections': [], 'sources': [], 'trace': {}}
        with patch('bulsae.graphrag.streamlit_ui.run_question', return_value=result) as run:
            app = AppTest.from_file(str(APP)).run()
            app.text_area[0].set_value('첫 질문')
            app.button[0].click().run()
            app.button(key='new_question').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_area[0].value, '')
            self.assertFalse(any('question-title">첫 질문' in x.value for x in app.markdown))
            self.assertFalse(any(x.value == '시험 답변' for x in app.markdown))
            self.assertTrue(any('기업 정보는 한눈에, 분석은 더 깊게' in x.value for x in app.markdown))
            run.assert_called_once_with('첫 질문')
            app.text_area[0].set_value('두 번째 질문')
            app.button[0].click().run()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args, ('두 번째 질문',))
            self.assertEqual(app.session_state['result']['question'], '두 번째 질문')
            self.assertEqual(len(app.exception), 0)

    def test_question_heading_is_escaped_and_shown_before_search(self):
        import streamlit as st
        question = '<img src=x onerror=alert(1)> 기업 정보'
        result = {'status': 'answered', 'answer': '시험 답변', 'sections': [], 'sources': [], 'trace': {}}
        with patch('bulsae.graphrag.streamlit_ui.run_question') as run:
            app = AppTest.from_file(str(APP)).run()
            with patch('bulsae.graphrag.streamlit_ui.st.markdown', wraps=st.markdown) as markdown:
                def answer(text):
                    values = [call.args[0] for call in markdown.call_args_list]
                    self.assertTrue(any('class="question-title"' in value and '&lt;img' in value for value in values))
                    self.assertTrue(any('답변을 준비하고 있어요' in value for value in values))
                    self.assertFalse(any('기업 정보는 한눈에, 분석은 더 깊게' in value for value in values))
                    return result
                run.side_effect = answer
                app.text_area[0].set_value(question)
                app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state['result']['status'], 'answered')
            self.assertFalse(any('<img src=x' in x.value for x in app.markdown))
            self.assertEqual(len(app.text_area), 0)


if __name__ == '__main__':
    unittest.main()
