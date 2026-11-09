import unittest
from unittest.mock import Mock
from bulsae.graphrag.document_search import business_path_rows, BUSINESS_PATH_QUERY
from bulsae.graphrag.related_analysis import missing_financial_facets, select_related_evidence
from bulsae.graphrag.graphs import QueryDeps, build_query_graph
from bulsae.graphrag.web_server import present_response


def edge(a, b, relation, kinds, doc, content):
    return dict(from_id=a, to_id=b, from_name=a, to_name=b,
        from_labels=['Bulsae'+kinds[0]], to_labels=['Bulsae'+kinds[1]], relation=relation,
        observation_id=a+relation+b, document_id=doc, title='가온 2025년 실적',
        url='https://example.org/'+doc, evidence=content, content=content)


def rows():
    return business_path_rows([{'representative_name':'가온', 'edges':[
        edge('가온','해외 성장','ANNOUNCED_STRATEGY',('Company','Strategy'),'D1',
             '가온은 2025년 매출과 영업이익 실적을 발표했다. 원가 개선과 해외 판매 확대가 요인이라고 설명했다.'),
        edge('해외 성장','뷰티','FOCUSES_ON',('Strategy','Business'),'D2',
             '가온의 2025년 사업 전략은 뷰티 중심이다. 회사는 판관비 효율화와 채널별 판매 구조가 수익성 개선의 배경이라고 밝혔다.')
    ]}], '가온 2025년 매출과 영업이익', '가온')


class BusinessPathsTests(unittest.TestCase):
    def test_real_two_hop_path_and_each_edges_own_document(self):
        result=rows()
        self.assertEqual(len(result),2)
        self.assertTrue(all(r['path_hops']==2 for r in result))
        self.assertEqual([e['document_id'] for e in result[0]['graph_path']],['D1','D2'])
        self.assertTrue(all(r['source_kind']=='graph' for r in result))

    def test_missing_edge_evidence_rejects_entire_path(self):
        edges=[edge('가온','전략','ANNOUNCED_STRATEGY',('Company','Strategy'),'D1','가온 전략 발표'),
               edge('전략','사업','FOCUSES_ON',('Strategy','Business'),'D2','사업 계획')]
        edges[1]['content']='다른 내용'
        self.assertEqual(business_path_rows([{'representative_name':'가온','edges':edges}], '가온 사업','가온'), [])

    def test_query_excludes_team_data_and_requires_owned_relationships(self):
        self.assertIn("r.pipeline_version='document-kg-v1'", BUSINESS_PATH_QUERY)
        self.assertIn("all(n IN nodes(p) WHERE none(label IN labels(n) WHERE label STARTS WITH 'B_'))", BUSINESS_PATH_QUERY)
        self.assertNotIn('MERGE ',BUSINESS_PATH_QUERY)
        self.assertNotIn('SET ',BUSINESS_PATH_QUERY)

    def test_complete_graph_coverage_does_not_search_original_corpus(self):
        evidence=rows()
        docs=Mock(side_effect=AssertionError('should not search'))
        related=Mock(return_value=[{'kind':'reported_fact','heading':'사업','text':'가온의 사업 배경이에요.','citations':[]}])
        finance=dict(name='가온',year=2025,period='연간',scope='개별',revenue=123,operating_profit=45,
                     financial_id='F1',source_json='[{"original_url":"https://example.org/finance"}]')
        deps=QueryDeps(Mock(),Mock(),Mock(),financial=lambda *_:[finance],documents=docs,
                       business_paths=lambda *_:evidence,related=related)
        result=build_query_graph(deps).invoke({'question':'가온 2025년 매출과 영업이익','name':'가온','kind':'company'})
        docs.assert_not_called()
        self.assertEqual(result['related_diagnostics']['fallback_reasons'],[])
        self.assertTrue(result['related_graph_paths'])
        related.assert_called_once()

    def test_semantic_failure_triggers_only_one_bounded_fallback(self):
        evidence=rows()
        docs=Mock(return_value=[])
        related=Mock(return_value=[])
        finance=dict(name='가온',year=2025,period='연간',scope='개별',revenue=123,
            financial_id='F',source_json='[{"original_url":"https://example.org/f"}]')
        deps=QueryDeps(Mock(),Mock(),Mock(),financial=lambda *_:[finance],documents=docs,
            business_paths=lambda *_:evidence,related=related)
        result=build_query_graph(deps).invoke({'question':'가온 2025년 매출','name':'가온','kind':'company'})
        self.assertEqual(docs.call_count,3)
        self.assertEqual(related.call_count,2)
        self.assertEqual(result['related_diagnostics']['semantic_fallback_attempts'],1)
        self.assertIn('인용·의미',result['related_diagnostics']['fallback_reasons'][0]['reason'])

    def test_business_fact_alone_supplements_causes_and_preserves_passed_fact(self):
        evidence=rows()
        fact={'kind':'reported_fact','heading':'사업','text':'가온은 판매 채널을 확대했어요.',
              'citations':[{'evidence_index':0,'exact_quote':evidence[0]['evidence']}]}
        related=Mock(side_effect=[[fact], []])
        docs=Mock(return_value=[])
        finance=dict(name='가온',year=2025,period='연간',scope='개별',revenue=123,
            financial_id='F',source_json='[{"original_url":"https://example.org/f"}]')
        deps=QueryDeps(Mock(),Mock(),Mock(),financial=lambda *_:[finance],documents=docs,
            business_paths=lambda *_:evidence,related=related)
        result=build_query_graph(deps).invoke({'question':'가온 2025년 매출 원인 분석','name':'가온','kind':'company'})
        self.assertEqual(docs.call_count,2)
        self.assertEqual(result['related_points'],[fact])
        self.assertEqual(result['related_evidence'][0]['document_id'],evidence[0]['document_id'])

    def test_finance_strategy_route_uses_same_graph_first_enrichment(self):
        finance=dict(name='가온',year=2025,period='연간',scope='개별',revenue=123,
            financial_id='F',source_json='[{"original_url":"https://example.org/f"}]')
        docs=Mock(side_effect=AssertionError('graph is sufficient'))
        paths=Mock(return_value=rows())
        related=Mock(return_value=[{'kind':'reported_fact','heading':'사업','text':'사업 전략을 확인했어요.','citations':[]}])
        deps=QueryDeps(Mock(),Mock(),Mock(),financial=lambda *_:[finance],documents=docs,
            business_paths=paths,related=related)
        result=build_query_graph(deps).invoke({'question':'가온 2025년 매출과 성장 전략','name':'가온','kind':'company'})
        paths.assert_called_once()
        docs.assert_not_called()
        self.assertIn('123',result['answer'])

    def test_only_missing_cost_facet_needs_fallback(self):
        evidence=rows()
        evidence[0]['evidence']='가온은 2025년 매출 실적을 발표했다. 해외 판매가 확장됐다고 설명했다.'
        evidence[1]['evidence']='가온은 2025년 사업에서 새 채널을 확보했다고 밝혔다.'
        missing=missing_financial_facets('가온 2025년 매출과 영업이익',['가온'],evidence)
        self.assertEqual([m['facet'] for m in missing],['비용과 수익성'])

    def test_wrong_period_graph_does_not_prevent_fallback(self):
        evidence=rows()
        for r in evidence:
            r['evidence']=r['evidence'].replace('2025','2026')
            r['title']='가온 2026년 실적'
        chosen=select_related_evidence('가온 2025년 매출',['가온'],evidence,True)
        self.assertEqual(chosen,[])
        self.assertEqual(len(missing_financial_facets('가온 2025년 매출',['가온'],chosen)),3)

    def test_trace_distinguishes_traversed_and_used_paths(self):
        evidence=rows()
        base={'status':'answered','answer':'기본 답변','related_evidence':evidence,
              'related_graph_paths':[{'path':evidence[0]['graph_path'],'document_id':'D1'}]}
        unused=present_response(base)
        self.assertEqual(unused['trace']['hops'],0)
        self.assertEqual(unused['trace']['retrieved_graph_hops'],2)
        self.assertFalse(unused['trace']['graph_paths'][0]['used_in_answer'])
        used=present_response({**base,'related_points':[{'kind':'reported_fact','heading':'사업','text':'사업 설명',
                  'citations':[{'evidence_index':0,'exact_quote':evidence[0]['evidence']}]}]})
        self.assertEqual(used['trace']['hops'],2)
        self.assertEqual(len(used['trace']['connections']),2)
        self.assertTrue(used['trace']['graph_paths'][0]['used_in_answer'])
        self.assertFalse(any(c['relation']=='DOCUMENT_EVIDENCE' for c in used['trace']['connections']))

if __name__=='__main__': unittest.main()
