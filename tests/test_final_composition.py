import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from bulsae.graphrag.related_analysis import (compose_final_answer, final_answer_facts,
    FinalDraft, FinalParagraph, FinalChecks, FinalCheck, INFERENCE_NOTICE)
from bulsae.graphrag.web_server import present_response
from bulsae.graphrag.graphs import QueryDeps, build_query_graph


def response():
    return {'sources':[{'number':1,'document_id':'D1','title':'가온 사업','url':'https://example.org/1',
                        'quotes':['온라인 판매가 늘었다. 매장을 확대했다.']}],
            'sections':[{'heading':'사업','text':'온라인 판매가 늘었고 매장을 확대했어요.',
                         'kind':'reported_fact','sources':[1]}]}


class FinalCompositionTests(unittest.TestCase):
    def test_single_metric_cannot_support_business_strength_inference(self):
        r={'sources':[{'number':1,'source_file':'financials.jsonl','title':'가온 재무'}],
           'financial_cards':[{'company':'가온','year':2025,'period':'연간','scope':'개별',
                               'label':'매출액','value':123}], 'sections':[]}
        client=Mock()
        client.responses.parse.return_value=SimpleNamespace(output_parsed=FinalDraft(paragraphs=[
            FinalParagraph(kind='analysis',heading='경쟁력',text='브랜드 경쟁력이 높아요.',fact_ids=[0])]))
        self.assertEqual(compose_final_answer(client,'model','매출 분석',r)['sections'],[])
        client.responses.parse.assert_called_once()

    def test_one_article_can_support_reasoning_from_multiple_accepted_facts(self):
        p=FinalParagraph(kind='analysis',heading='판매 접점 확대',
            text='온라인 판매와 매장 확대를 함께 보면 고객과 만나는 접점이 다양해지는 흐름으로 해석할 수 있어요.',fact_ids=[0])
        client=Mock()
        client.responses.parse.side_effect=[SimpleNamespace(output_parsed=FinalDraft(paragraphs=[p])),
            SimpleNamespace(output_parsed=FinalChecks(checks=[FinalCheck(index=0,premises_supported=True,
                scope_preserved=True,appropriate_inference=True,relevant=True,errors=[])]))]
        r=compose_final_answer(client,'model','가온 사업을 분석해줘',response())
        self.assertEqual(r['sections'][0]['sources'],[1])
        self.assertEqual(r['sections'][0]['kind'],'interpretation')
        self.assertEqual(client.responses.parse.call_count,2)

    def test_old_interpretation_is_not_a_factual_premise(self):
        r=response()
        r['sections'].append({'text':'수익성이 개선될 것이다','kind':'interpretation','sources':[1]})
        self.assertEqual(len(final_answer_facts(r)),1)

    def test_group_facts_cannot_be_recast_as_company_analysis(self):
        r=response()
        r['sections'][0]['heading']='가온그룹 판매 활동'
        client=Mock()
        client.responses.parse.return_value=SimpleNamespace(output_parsed=FinalDraft(paragraphs=[
            FinalParagraph(kind='analysis',heading='시장 확대',text='가온 법인의 이익이 개선될 수 있어요.',fact_ids=[0])]))
        self.assertFalse(compose_final_answer(client,'model','질문',r)['sections'])
        client.responses.parse.assert_called_once()

    def test_invalid_fact_reference_is_not_repaired_or_accepted(self):
        client=Mock()
        client.responses.parse.return_value=SimpleNamespace(output_parsed=FinalDraft(paragraphs=[
            FinalParagraph(kind='analysis',heading='예상',text='새로운 결론',fact_ids=[99])]))
        r=compose_final_answer(client,'model','질문',response())
        self.assertEqual(r['sections'],[])
        client.responses.parse.assert_called_once()

    def test_reviewer_rejects_invented_cost_premise(self):
        client=Mock()
        client.responses.parse.side_effect=[SimpleNamespace(output_parsed=FinalDraft(paragraphs=[
            FinalParagraph(kind='analysis',heading='수익성',text='비용 절감으로 이익이 개선됐어요.',fact_ids=[0])])),
            SimpleNamespace(output_parsed=FinalChecks(checks=[FinalCheck(index=0,premises_supported=False,
                scope_preserved=True,appropriate_inference=False,relevant=True,errors=['없는 비용 절감 전제'])]))]
        self.assertFalse(compose_final_answer(client,'model','질문',response())['sections'])

    def test_final_presentation_keeps_amount_and_notice_once(self):
        state={'status':'answered','answer':'기존 답변','trace_kind':'financial',
            'structured_sources':[{'document_id':'F','title':'가온 재무','from_name':'가온','url':'https://example.org/f',
              'source_file':'financials.jsonl','evidence':'매출액: 123원',
              'financial_metrics':{'revenue':123},'year':2025,'period':'연간','scope':'개별'}],
            'final_output':{'sections':[{'heading':'핵심 요약','text':'확인된 사업이에요.','section_type':'basic','sources':[1]},
                {'heading':'사업 의미','text':'자료를 바탕으로 한 해석이에요.','kind':'interpretation',
                 'section_type':'additional','sources':[1]}]}}
        r=present_response(state)
        self.assertEqual(r['analysis_notice'],INFERENCE_NOTICE)
        self.assertEqual(r['answer'].count(INFERENCE_NOTICE),1)
        self.assertIn('123원',r['answer'])
        self.assertNotIn('기존 답변',r['answer'])
        self.assertEqual(r['financial_cards'][0]['value'],123)

    def test_final_prose_keeps_consolidated_source_scope_visible(self):
        state={'status':'answered','answer':'사업 설명','structured_sources':[
            {'document_id':'D','title':'연결 실적','url':'https://example.org/d',
             'evidence':'가온은 2025년 연결 기준 실적을 발표했다.'}],
            'final_output':{'sections':[{'heading':'사업 의미','text':'확인된 활동을 해석했어요.',
                'kind':'interpretation','section_type':'additional','sources':[1]}]}}
        r=present_response(state)
        self.assertTrue(r['sections'][-1]['heading'].startswith('연결 사업'))

    def test_composition_failure_preserves_basic_answer(self):
        finance=dict(name='가온',year=2025,period='연간',scope='개별',revenue=123,
                     financial_id='F',source_json='[{"original_url":"https://example.org/f"}]')
        deps=QueryDeps(Mock(),Mock(),Mock(),financial=lambda *_:[finance],
                       compose=Mock(side_effect=RuntimeError('unavailable')))
        r=build_query_graph(deps).invoke({'question':'가온 2025년 매출','name':'가온','kind':'company'})
        self.assertIn('123',r['answer'])
        self.assertEqual(r['final_output']['diagnostics']['status'],'error')


if __name__ == '__main__': unittest.main()
