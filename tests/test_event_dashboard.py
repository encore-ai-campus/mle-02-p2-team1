import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
from streamlit.testing.v1 import AppTest
from bulsae.graphrag.related_analysis import (FinalDraft, FinalEvent, FinalChecks, FinalCheck,
    compose_final_answer, merge_event_cards)
from bulsae.graphrag.web_server import present_response


def card(name='2026 투자자 행사', year=2026, **kwargs):
    return dict(name=name, year=year, participants=['김가온'], description='투자자 대상 행사예요.',
                activity='해외 전략을 발표했어요.', fact_ids=[0], sources=[1], **kwargs)


class EventDashboardTests(unittest.TestCase):
    def test_repeated_articles_count_one_event_but_editions_stay_separate(self):
        a=card()
        b={**card('투자자 행사'), 'sources':[2], 'fact_ids':[1]}
        c=card('2025 투자자 행사', 2025)
        merged=merge_event_cards([a,b,c])
        self.assertEqual(len(merged),2)
        self.assertEqual(merged[0]['sources'],[1,2])
        self.assertEqual(merged[0]['activity'],a['activity'])
        self.assertEqual(len(merge_event_cards([card(year=None),c])),2)

    def test_reviewed_event_card_keeps_sources_without_inventing_details(self):
        client=Mock()
        event=FinalEvent(name='2026 투자자 행사',year=2026,participants=['김가온'],
                         description='',activity='',fact_ids=[0])
        client.responses.parse.side_effect=[SimpleNamespace(output_parsed=FinalDraft(paragraphs=[],events=[event])),
            SimpleNamespace(output_parsed=FinalChecks(checks=[FinalCheck(index=0,premises_supported=True,
                scope_preserved=True,appropriate_inference=True,relevant=True,errors=[])]))]
        result=compose_final_answer(client,'model','김가온이 참여한 행사 알려줘',{
            'sources':[{'number':1,'document_id':'D1','quotes':['2026 투자자 행사에 김가온이 참석했다.']}],
            'sections':[{'text':'김가온이 2026 투자자 행사에 참석했어요.','sources':[1]}]})
        self.assertEqual(result['event_cards'][0]['sources'],[1])
        self.assertEqual(result['event_cards'][0]['description'],'')
        self.assertEqual(result['sections'],[])

    def test_planned_only_event_fails_review_and_is_not_counted(self):
        client=Mock()
        event=FinalEvent(name='투자자 행사',year=2026,participants=['김가온'],description='',activity='',fact_ids=[0])
        client.responses.parse.side_effect=[SimpleNamespace(output_parsed=FinalDraft(paragraphs=[],events=[event])),
            SimpleNamespace(output_parsed=FinalChecks(checks=[FinalCheck(index=0,premises_supported=False,
                scope_preserved=True,appropriate_inference=False,relevant=True,errors=['참석 예정만 확인됨'])]))]
        r=compose_final_answer(client,'model','김가온이 참여한 행사 알려줘',{
            'sources':[{'number':1,'document_id':'D1','quotes':[]}],
            'sections':[{'text':'참석할 예정이에요.','sources':[1]}]})
        self.assertEqual(r['event_cards'],[])

    def test_dashboard_counts_cards_not_articles_and_export_keeps_events(self):
        r=present_response({'status':'answered','answer':'이전 목록','structured_sources':[
            {'document_id':'D1','url':'https://example.org/1','evidence':'참석 사실'},
            {'document_id':'D2','url':'https://example.org/2','evidence':'동일 행사 기사'}],
            'final_output':{'sections':[], 'event_cards':[card(),{**card('투자자 행사'),'sources':[2]}]}})
        self.assertEqual(r['event_dashboard'],{'attended_count':1,'activity_count':1,'source_count':2})
        self.assertIn('해외 전략을 발표했어요.',r['answer'])
        self.assertNotIn('이전 목록',r['answer'])
        self.assertFalse(r['sections'])

    def test_streamlit_renders_dashboard_then_event_cards_and_analysis(self):
        result={'question':'참석 행사 알려줘','status':'answered','answer':'답변','sources':[],'trace':{},
            'event_cards':[card(),{**card('산업 포럼'),'description':'','activity':''}],
            'event_dashboard':{'attended_count':2,'activity_count':1,'source_count':3},
            'final_composed':True,'sections':[{'heading':'사업 방향','text':'근거를 해석한 내용',
                                              'section_type':'additional','kind':'interpretation'}]}
        with patch('bulsae.graphrag.streamlit_ui.run_question',return_value=result):
            app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'streamlit_app.py')).run()
            app.text_area[0].set_value(result['question'])
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertNotIn('발표·활동 확인',[m.label for m in app.metric])
            self.assertNotIn('근거 기사',[m.label for m in app.metric])
            headings=[x.value for x in app.subheader]
            self.assertLess(headings.index('확인된 참석 행사 2건'),headings.index('2026 투자자 행사'))
            self.assertLess(headings.index('산업 포럼'),headings.index('✦ AI 통합분석'))
            self.assertEqual(sum(x.value=='해외 전략을 발표했어요.' for x in app.markdown),1)

if __name__=='__main__': unittest.main()
