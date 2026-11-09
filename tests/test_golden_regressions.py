import json
import unittest
from bulsae.graphrag.entity_resolution import choose_entity
from bulsae.graphrag.company_information import is_business_question
from bulsae.graphrag.graphs import QueryDeps, build_query_graph
from bulsae.graphrag.document_search import AnswerClaim, CitedParagraph, hydrate_citations, quote_units
from bulsae.graphrag.document_fallback import rank_documents, topic_terms
from bulsae.graphrag.related_analysis import novel_points
from bulsae.graphrag.web_server import present_response

class GoldenRegressions(unittest.TestCase):
    def test_joint_relationship_is_not_ambiguous_or_separate_comparison(self):
        records=[{'name':n,'kind':'company'} for n in ['가온','가온그룹','나온']]
        for q in ['가온과 나온의 공동 공급사는?', '가온 매출과 가온그룹 전략은?']:
            self.assertEqual(choose_entity(q,records)['status'],'resolved_multi')
        self.assertEqual(choose_entity('가온이 협력한 곳들의 역할 차이는?', records)['status'],'resolved')
        self.assertEqual(choose_entity('가온과 다른 기업을 비교해줘', records)['status'],'comparison_needs_names')

    def test_future_business_does_not_return_company_profile(self):
        self.assertFalse(is_business_question('가온은 어떤 사업을 앞으로 키우려고 해?'))
        self.assertTrue(is_business_question('가온은 주로 어떤 사업을 하는 회사야?'))

    def test_group_news_and_company_finance_are_separate_sources(self):
        text='가온그룹은 2025년 해외 성장 전략을 발표했다.'
        row={'document_id':'NEWS-test','url':'https://example.org/n','source_verified':True,'evidence':text,'source_kind':'document','relation':'DOCUMENT_EVIDENCE'}
        fin={'name':'가온','year':2025,'period':'연간','scope':'개별','revenue':123,'operating_profit':12,'financial_id':'FIN-test','source_json':json.dumps([{'original_url':'https://example.org/f'}])}
        requested=[]
        def finance(names): requested.extend(names); return [fin]
        deps=QueryDeps(lambda *_:[],lambda *_:[AnswerClaim(text=text,exact_quote=text,evidence_index=0)],lambda *_:{0},
            identify=lambda _: {'status':'resolved_multi','entities':[{'name':n,'kind':'company'} for n in ['가온','가온그룹']]},financial=finance,documents=lambda *_:[row])
        q='가온의 2025년 매출과 가온그룹 성장 전략은?'
        result=build_query_graph(deps).invoke({'question':q})
        self.assertEqual(result['status'],'answered')
        self.assertEqual(result['question'],q)
        self.assertEqual(requested,['가온'])
        response=present_response(result)
        self.assertIn('123',response['answer']); self.assertIn('가온그룹',response['answer'])
        self.assertEqual({s['document_id'] for s in response['sources']},{'FIN-test','NEWS-test'})

    def test_quarterly_news_not_replaced_with_annual_financial(self):
        text='가온그룹의 2025년 1분기 영업이익은 12억원이다.'
        row={'document_id':'NEWS-t','url':'https://example.org','source_verified':True,'evidence':text,'relation':'DOCUMENT_EVIDENCE'}
        def fail(*_): raise AssertionError('annual finance must not run')
        deps=QueryDeps(lambda *_:[],lambda *_:[AnswerClaim(text=text,exact_quote=text,evidence_index=0)],lambda *_:{0},financial=fail,documents=lambda *_:[row])
        result=build_query_graph(deps).invoke({'name':'가온그룹','kind':'company','question':'가온그룹의 2025년 분기 영업이익은?'})
        self.assertEqual(result['status'],'answered'); self.assertIn('12억원',result['answer'])

    def test_issue_retrieval_and_specific_subject_priority(self):
        self.assertIn('가맹점',topic_terms('가온 주요 이슈는?'))
        from bulsae.graphrag.related_analysis import related_query
        self.assertNotIn('제품', related_query('가온 주요 이슈는?'))
        from bulsae.graphrag.related_analysis import relevant_points
        points=[{'text':'가온의 홀리데이 제품 출시'}, {'text':'가온의 가맹점 분쟁과 회사 해명'}]
        self.assertEqual(relevant_points('가온 주요 이슈는?',points),points[1:])
        issue_docs=[{'document_id':'NEWS-issue','url':'https://example.org','content':'가온 가맹점 갈등이 보도됐다.'},
                    {'document_id':'NEWS-ad','url':'https://example.org','content':'가온 신제품이 출시됐다.'}]
        self.assertEqual([r['document_id'] for r in rank_documents('가온 주요 이슈는?', ['가온'], issue_docs)], ['NEWS-issue'])
        docs=[{'document_id':'NEWS-'+str(i),'url':'https://example.org','content':s,'title':s}
              for i,s in enumerate(['가온은 신제품을 출시했다.','가온과 나온은 제주 정원을 공동 조성했다.'])]
        rows=rank_documents('가온 제주 정원은 누가 조성했어?',['가온'],docs)
        self.assertEqual(rows[0]['document_id'],'NEWS-1')

    def test_cause_category_survives_hydration_and_presentation(self):
        text='가온은 유통 확대가 성장의 원인이라고 설명했다.'
        row={'document_id':'NEWS-c','url':'https://example.org','evidence':text,'source_kind':'document'}
        claim=CitedParagraph(text=text,heading='성장 배경',kind='company_explanation',evidence_index=0,quote_ids=[0])
        hydrated=hydrate_citations([claim],[row],{0:quote_units(text)})
        shown=present_response({'status':'answered','answer':text,'claims':[hydrated[0].model_dump()],'evidence':[row],'supported':[0]})
        self.assertTrue(shown['sections'][0]['heading'].startswith('회사가 밝힌 원인'))
        self.assertEqual(shown['sections'][0]['section_type'],'basic')

    def test_paraphrased_supplement_is_removed(self):
        basic='가온은 신제품 밀크 에센스를 출시하여 제품 포트폴리오를 강화하고 운영 효율성 개선으로 수익성을 높였어요.'
        points=[{'text':'가온은 신제품 밀크 에센스를 출시해 제품 포트폴리오를 강화하고 운영 효율성 개선으로 수익성을 개선했어요.'}, {'text':'나온과 공동 연구 계약을 체결했어요.'}]
        self.assertEqual(novel_points(points,basic),points[1:])

class CauseBoundaryTests(unittest.TestCase):
    def test_plan_is_not_a_company_cause_and_real_cause_can_pass(self):
        from bulsae.graphrag.document_search import company_cause_supported
        self.assertFalse(company_cause_supported('가온은 해외 확대 계획이라고 밝혔어요.', '가온은 해외 확대 계획이라고 밝혔다.'))
        self.assertTrue(company_cause_supported('가온은 유통 개선이 매출 성장의 원인이라고 설명했어요.', '가온은 유통 개선이 매출 성장의 원인이라고 설명했다.'))
        self.assertFalse(company_cause_supported('기자는 유통 개선이 원인이라고 분석했어요.', '기자는 유통 개선이 원인이라고 분석했다.'))

class CitationBoundaryTests(unittest.TestCase):
    def test_product_and_company_attribution_need_their_own_quotes(self):
        from bulsae.graphrag.document_search import named_details_supported, attribution_supported
        self.assertFalse(named_details_supported("'다른 세럼'이 수상했어요.", "'원래 크림'이 수상했다."))
        self.assertFalse(named_details_supported('NMPA 허가를 받았어요.', '제품은 보습제로 출시됐다.'))
        self.assertFalse(attribution_supported('실적 개선이라고 회사가 설명했어요.', '기사에서는 영업이익이 늘었다.'))
        self.assertTrue(attribution_supported('유통 개선이 원인이라고 회사가 설명했어요.', '회사 측은 유통 개선이 원인이라고 설명했다.'))
