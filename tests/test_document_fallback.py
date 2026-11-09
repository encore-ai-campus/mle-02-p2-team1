import json
import unittest
from bulsae.graphrag.document_fallback import rank_documents, merge_evidence
from bulsae.graphrag.entity_resolution import choose_entity
from bulsae.graphrag.document_search import AnswerClaim, validate_answer_claims, quote_units, hydrate_citations, CitedParagraph
from bulsae.graphrag.graphs import QueryDeps, build_query_graph, financial_background_supported
from bulsae.graphrag.multihop_search import event_year_candidate, work_role_supported
from bulsae.graphrag.web_server import present_response

class FallbackTests(unittest.TestCase):
    def test_profit_cost_facet_retrieves_cost_only_article(self):
        from bulsae.graphrag.document_fallback import topic_terms
        question = '가온 2025년 영업이익은?\n분석 초점: 원가 판관비 일회성 비용'
        self.assertIn('판관비', topic_terms(question))
        docs = [{'document_id':'NEWS-cost','title':'가온 2025년 비용 구조',
                 'url':'https://example.org/cost',
                 'content':'가온은 2025년 사업에서 판관비와 일회성 비용을 인식했다.'}]
        self.assertEqual(rank_documents(question,['가온'],docs)[0]['document_id'],'NEWS-cost')

    def test_financial_search_prioritizes_entity_filing_and_deduplicates_releases(self):
        docs = [{'document_id':'NEWS-filing','title':'가온, 2025년 영업이익 발표',
                 'url':'https://example.org/filing',
                 'content':'가온은 2025년 연결 기준 실적을 공시했다. 회사는 해외 사업 성장을 설명했다. 별도 매출도 함께 공시했다.'}]
        release = '가온그룹이 2025년 매출을 발표했다. 가온은 브랜드 판매 확대와 해외 시장 성장으로 수익성이 개선됐다. '
        docs += [{'document_id':f'NEWS-copy{i}','title':'가온그룹 2025년 매출 발표',
                  'url':f'https://example.org/copy{i}', 'content':release + f'기자 {i} 보도.'} for i in range(4)]
        rows = rank_documents('가온 2025년 매출 배경', ['가온'], docs)
        self.assertEqual(rows[0]['document_id'], 'NEWS-filing')
        self.assertEqual(len(rows), 2)
        for r in rows:
            original = next(d['content'] for d in docs if d['document_id']==r['document_id'])
            self.assertEqual(original[r['excerpt_start']:r['excerpt_end']], r['evidence'])

    def test_financial_context_cannot_override_standalone_amount(self):
        quote='아모레퍼시픽 매출은 4조 2528억 원이다. 해외 사업이 성장했다.'
        for text, heading in [('매출은 4조 2528억 원이에요.', '실적'),
                              ('매출은 9.5% 증가했어요.', '실적'),
                              ('해외 사업이 성장했어요.', '개별 매출의 배경')]:
            claim=AnswerClaim(text=text,heading=heading,exact_quote=quote,evidence_index=0)
            self.assertFalse(financial_background_supported(claim))
        claim=AnswerClaim(text='해외 사업이 성장했어요.',heading='사업 배경',exact_quote=quote,evidence_index=0)
        self.assertTrue(financial_background_supported(claim))

    def test_citation_ids_copy_exact_original_and_reject_missing_ids(self):
        text='첫 문단이다.\n\n김 대표는 포럼에서 환영인사를 했다.\n'
        rows=[{'evidence':text}];units={0:quote_units(text)}
        claim=CitedParagraph(text='김 대표가 포럼에서 환영인사를 했어요.',heading='포럼',evidence_index=0,quote_ids=[1])
        hydrated=hydrate_citations([claim],rows,units)
        self.assertEqual(hydrated[0].exact_quote,'김 대표는 포럼에서 환영인사를 했다.')
        self.assertEqual(hydrate_citations([claim.model_copy(update={'quote_ids':[99]})],rows,units),[])

    def test_whitespace_entity_preserves_group_boundary(self):
        records=[{'name':'아모레퍼시픽','kind':'company'}]
        self.assertEqual(choose_entity('아모레 퍼시픽 2025년 매출은?',records)['name'],'아모레퍼시픽')
        self.assertEqual(choose_entity('아모레 퍼시픽그룹 매출은?',records)['status'],'not_found')

    def test_literal_excerpts_and_topic_diversity(self):
        docs=[{'document_id':f'NEWS-{i}','url':'https://example.org/'+str(i),'content':text}
              for i,text in enumerate(['가온 대표가 전략을 발표하는 행사다.']*4+['가온 대표가 총회에서 발언했다.','가온 대표가 Summit에 참가했다.'])]
        rows=rank_documents('가온 대표 참석 행사는?',['가온'],docs,5)
        self.assertEqual(len(rows),3)
        self.assertTrue(any('Summit' in r['evidence'] for r in rows))
        for row in rows:
            doc=next(d for d in docs if d['document_id']==row['document_id'])
            self.assertEqual(doc['content'][row['excerpt_start']:row['excerpt_end']],row['evidence'])

    def test_raw_evidence_without_graph_produces_no_fake_edges(self):
        text='가온은 나온과 공동 연구 협약을 맺었다.'
        row={'document_id':'NEWS-x','url':'https://example.org/x','evidence':text,'source_verified':True,'source_kind':'document','relation':'DOCUMENT_EVIDENCE'}
        deps=QueryDeps(lambda *_:[],lambda *_:[AnswerClaim(text=text,evidence_index=0,exact_quote=text)],lambda *_:{0},documents=lambda *_:[row])
        result=build_query_graph(deps).invoke({'question':'가온 협력은?','name':'가온','kind':'company'})
        self.assertEqual(result['status'],'answered')
        response=present_response(result)
        self.assertEqual(response['trace']['connections'],[])
        self.assertEqual(response['sources'][0]['source_kind'],'document')

    def test_partial_graph_is_also_supplemented(self):
        graph={'document_id':'NEWS-a','relation':'PARTNERS_WITH','evidence':'가온과 나온의 협력이다.'}
        raw={'document_id':'NEWS-b','relation':'DOCUMENT_EVIDENCE','evidence':'가온과 다온의 협력이다.'}
        self.assertEqual(len(merge_evidence([graph],[raw])),2)

    def test_event_year_is_not_publication_year_alone(self):
        self.assertIsNone(event_year_candidate('포럼','김 대표가 포럼에서 발언했다.','2026-09-14'))
        self.assertEqual(event_year_candidate('포럼','지난해 9월 5일 포럼에서 인사말을 했다.','2025-12-05'),2024)
        self.assertEqual(event_year_candidate('총회','26일 열린 총회에서 발언했다.','2026-03-27'),2026)
        self.assertTrue(work_role_supported('홍길동','가온','ceo','가온 홍길동 대표이사가 발표했다.'))

    def test_invented_date_does_not_pass_quote_check(self):
        text='홍길동 대표는 지난 11일 2026 행사에서 발언했다.'
        row={'document_id':'NEWS-x','url':'https://example.org','evidence':text,'source_verified':True}
        for explanation in ('2023년 11일 행사에 참석했다.','2023년 행사에 참석했다.','2026년 9월 11일 행사에 참석했다.'):
            self.assertEqual(validate_answer_claims([AnswerClaim(text=explanation,exact_quote=text,evidence_index=0)],[row]),[])

    def test_financial_background_keeps_amount_and_sources(self):
        text='가온의 2025년 해외 사업 매출이 성장했다.'
        raw={'document_id':'NEWS-x','url':'https://example.org/x','evidence':text,'source_verified':True,'source_kind':'document'}
        finance={'name':'가온','year':2025,'period':'연간','scope':'개별','revenue':100000000,'financial_id':'FIN-a','source_json':json.dumps([{'original_url':'https://example.org/financial'}])}
        deps=QueryDeps(lambda *_:[],lambda *_:[AnswerClaim(text=text,exact_quote=text,evidence_index=0)],lambda *_:{0},financial=lambda *_:[finance],documents=lambda *_:[raw])
        result=build_query_graph(deps).invoke({'question':'가온 2025년 매출과 발생 이유 분석해줘','name':'가온','kind':'company'})
        response=present_response(result)
        self.assertEqual(response['status'],'answered')
        self.assertIn('100,000,000',response['answer'])
        self.assertIn('단정',response['answer'])
        self.assertTrue(response['sections'][0]['sources'])
        self.assertEqual(len(response['sources']),2)

if __name__=='__main__': unittest.main()
