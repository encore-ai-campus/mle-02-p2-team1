import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from bulsae.graphrag.graphs import QueryDeps, build_query_graph
from bulsae.graphrag.related_analysis import (AnalysisPoint, AnalysisCitation, AnalysisResult,
    validate_points, select_related_evidence, generate_related_analysis, AnalysisDecisions, AnalysisDecision)
from bulsae.graphrag.web_server import present_response


def row(id, text):
    return {'document_id':id, 'evidence':text, 'source_verified':True,
            'url':'https://example.org/'+id, 'source_kind':'document'}


def point(kind='reported_fact', citations=None):
    return AnalysisPoint(kind=kind, heading='해외 사업', text='가온은 해외 채널을 확대했어요.',
                         citations=citations or [AnalysisCitation(evidence_index=0, quote_ids=[0])])


class RelatedTests(unittest.TestCase):
    def test_group_caveat_does_not_repair_company_profit_growth_claim(self):
        rows = [row('NEWS-g1', '가온그룹은 2025년 해외 채널을 확대했다.'),
                row('NEWS-g2', '가온그룹은 2025년 비용 효율화를 추진했다.')]
        candidate = point('interpretation', [AnalysisCitation(evidence_index=i, quote_ids=[0]) for i in (0,1)])
        candidate = candidate.model_copy(update={'heading':'사업 배경',
            'text':'가온의 영업이익 증가는 해외 확대와 비용 효율화의 영향으로 해석해요. 다만 그룹 연결 기준 해석이에요.'})
        self.assertEqual(validate_points([candidate], rows, True), [])

    def test_cost_period_context_is_eligible_without_sales_keyword(self):
        evidence = row('NEWS-cost-only', '가온은 2025년 비용 구조를 공개했다. 판관비 부담이 줄었다.')
        self.assertEqual(select_related_evidence('가온 2025년 영업이익', ['가온'], [evidence], True), [evidence])

    def test_group_financial_context_cannot_be_labelled_only_consolidated(self):
        rows = [row('NEWS-g', '가온그룹은 2025년 연결 실적을 발표했다. 해외 채널을 확대했다.')]
        candidate = point().model_copy(update={'heading':'연결 사업', 'text':'해외 채널을 확대했어요.'})
        self.assertEqual(validate_points([candidate], rows, True), [])
        candidate = candidate.model_copy(update={'heading':'가온그룹 연결 사업'})
        self.assertEqual(len(validate_points([candidate], rows, True)), 1)

    def test_financial_queries_cover_costs_and_keep_original_question(self):
        from bulsae.graphrag.related_analysis import related_queries
        question = '가온 2025년 영업이익은?'
        queries = related_queries(question, True)
        self.assertEqual(len(queries), 3)
        self.assertTrue(all(q.startswith(question) for q in queries))
        self.assertIn('판관비', queries[1])
        self.assertIn('일회성', queries[1])
        self.assertEqual(len(related_queries('가온은 어떤 회사야?')), 1)

    def test_cost_evidence_and_comparison_company_are_not_crowded_out(self):
        sales = [row(f'NEWS-{i}', f'가온은 2025년 매출 실적을 발표했다. 채널 판매 관련 자료 {i}.') for i in range(20)]
        costs = row('NEWS-cost', '가온은 2025년 영업이익 실적을 발표했다. 일회성 비용을 인식해 수익성이 낮아졌다고 회사는 설명했다.')
        other = row('NEWS-other', '나래는 2025년 영업이익을 공개했다. 원가 부담 축소와 공장 효율화가 이익 증가 요인이라고 밝혔다.')
        selected = select_related_evidence('가온과 나래 2025년 영업이익 비교', ['가온', '나래'], sales + [costs, other], True)
        ids = {r['document_id'] for r in selected}
        self.assertIn('NEWS-cost', ids)
        self.assertIn('NEWS-other', ids)
        self.assertLessEqual(len(selected), 16)
        self.assertNotIn('NEWS-wrong', {r['document_id'] for r in select_related_evidence(
            '가온 2025년 영업이익', ['가온'], [row('NEWS-wrong', '가온은 2026년 영업이익 실적을 발표했다.')], True)})

    def test_failed_facet_keeps_successful_search_results(self):
        question = '가온 2025년 영업이익은?'
        rows = [row('NEWS-cost', '가온은 2025년 영업이익 실적을 발표했다. 원가가 감소했다.')]
        def docs(query, names):
            if '판관비' in query:
                raise RuntimeError('unavailable')
            return rows
        finance = {'name':'가온','year':2025,'period':'연간','scope':'개별','operating_profit':123,
                   'financial_id':'FIN-x','source_json':json.dumps([{'original_url':'https://example.org/f'}])}
        related = Mock(return_value=[])
        deps = QueryDeps(lambda *_:[], Mock(), Mock(), financial=lambda *_:[finance], documents=docs, related=related)
        result = build_query_graph(deps).invoke({'question':question,'name':'가온','kind':'company'})
        self.assertIn('123', result['answer'])
        self.assertEqual(result['question'], question)
        self.assertEqual(len(result['related_diagnostics']['search_queries']), 3)
        self.assertEqual(result['related_diagnostics']['selected_documents'], 1)
        self.assertEqual(len(result['related_errors']), 1)
        self.assertEqual(related.call_count, 1)

    def test_scope_limit_is_not_an_assertion_of_standalone_causality(self):
        from bulsae.graphrag.graphs import financial_background_supported
        from bulsae.graphrag.document_search import AnswerClaim
        claim = AnswerClaim(heading='연결 사업 배경', text='판매 기반이 다양해진 흐름이에요. 다만 개별 매출 수치의 직접 인과관계나 기여액으로 확인되지는 않아요.',
            exact_quote='연결 사업에서 채널이 확대됐다.',evidence_index=0)
        self.assertTrue(financial_background_supported(claim))
        self.assertFalse(financial_background_supported(claim.model_copy(update={'heading':'개별 매출 성장 배경'})))
        self.assertFalse(financial_background_supported(claim.model_copy(update={'text':'개별 매출이 증가했어요. 다만 개별 매출의 직접 원인은 확인되지 않아요.'})))

    def test_financial_synthesis_attempt_is_bounded_and_still_reviewed(self):
        rows = [row('NEWS-a','가온은 2025년 연결 사업에서 해외 채널을 확대했다.'),
                row('NEWS-b','가온은 2025년 연결 사업에서 해외 제품을 출시했다.')]
        synthesis = point('interpretation', [AnalysisCitation(evidence_index=i,quote_ids=[0]) for i in (0,1)])
        client = Mock()
        client.responses.parse.side_effect = [
            SimpleNamespace(output_parsed=AnalysisResult(points=[point()])),
            SimpleNamespace(output_parsed=AnalysisResult(points=[synthesis])),
            SimpleNamespace(output_parsed=AnalysisDecisions(decisions=[AnalysisDecision(
                claim_index=i,source_supported=True,category_valid=True,adds_information=True,
                scope_valid=True,relevant_to_question=True,distinct_premises=True,errors=[])
                for i in range(2)]))]
        diagnostics = {}
        result = generate_related_analysis(client,'test','가온 2025년 매출은?','매출은 123원이에요.',rows,True,diagnostics=diagnostics)
        self.assertEqual(client.responses.parse.call_count,3)
        self.assertEqual(diagnostics['synthesis_attempts'],1)
        self.assertTrue(any(p['kind']=='interpretation' for p in result))

    def test_distant_period_and_business_excerpts_do_not_include_intervening_plans(self):
        text = '가온은 2025년 연결 실적을 발표했다.\n' + ('별개 계획을 검토할 예정이다.\n' * 110) + '가온은 해외 채널을 확대했다.'
        candidate = point().model_copy(update={'heading':'2025년 연결 사업', 'citations':[
            AnalysisCitation(evidence_index=0, quote_ids=[0,111])]})
        checked = validate_points([candidate], [row('NEWS-a',text)], financial=False)
        self.assertEqual(len(checked),1)
        self.assertTrue(all(c['exact_quote'] in text for c in checked[0]['citations']))
        self.assertFalse(any('예정' in c['exact_quote'] for c in checked[0]['citations']))

    def test_synthesis_is_not_dropped_for_reusing_its_fact_premises(self):
        from bulsae.graphrag.related_analysis import novel_points
        fact = {'kind':'reported_fact','text':'해외 채널을 확대하고 제품 구성을 다양하게 바꿨어요.'}
        synthesis = {'kind':'interpretation','text':'해외 채널을 확대하고 제품 구성을 다양하게 바꾼 점을 종합하면 판매 접점과 수요를 함께 넓힌 흐름으로 해석할 수 있어요.'}
        self.assertEqual(novel_points([fact,synthesis],'매출은 123원이에요.'),[fact,synthesis])

    def test_original_relative_date_is_not_rejected_as_generated_answer(self):
        rows = [row('NEWS-a', '가온은 지난해 해외 채널을 확대했다.')]
        self.assertEqual(len(validate_points([point()], rows)), 1)
        generated_relative_date = point().model_copy(update={'text':'가온은 지난해 해외 채널을 확대했어요.'})
        self.assertEqual(validate_points([generated_relative_date], rows), [])

    def test_later_grounded_candidate_survives_invalid_early_drafts(self):
        rows = [row('NEWS-a', '가온은 해외 채널을 확대했다.')]
        invalid = point().model_copy(update={'citations':[AnalysisCitation(evidence_index=9, quote_ids=[0])]})
        self.assertEqual(len(validate_points([invalid, invalid, invalid, point()], rows)), 1)

    def test_synthesis_can_cite_multiple_individually_bounded_excerpts(self):
        rows = [row('NEWS-a', '가온은 해외 채널을 확대했다. ' + '판매망 운영을 개선했다. '*90),
                row('NEWS-b', '가온은 해외 제품을 출시했다. ' + '제품 구성을 다양하게 바꿨다. '*90)]
        refs = [AnalysisCitation(evidence_index=i, quote_ids=[0]) for i in (0,1)]
        self.assertGreater(sum(len(r['evidence']) for r in rows), 2400)
        self.assertEqual(len(validate_points([point('interpretation', refs)], rows)), 1)

    def test_fiscal_period_in_intro_applies_to_following_results(self):
        rows = [row('NEWS-results', '가온은 2025년 연결 기준 당기순이익을 공시했다.\n\n같은 기간 매출이 증가했다. 회사는 해외 사업 성장을 설명했다.'),
                row('NEWS-award', '가온은 2025년 디자인상을 수상했다.\n\n해외 사업을 확대한다.')]
        selected = select_related_evidence('가온 2025년 매출은?', ['가온'], rows, True)
        self.assertEqual([r['document_id'] for r in selected], ['NEWS-results'])

    def test_later_results_cannot_borrow_year_from_historical_comparison(self):
        later = row('NEWS-later', '가온은 올해 3분기 해외 판매가 증가했다.\n새 제품 판매가 성장했다.\n온라인 채널을 늘렸다.\n2025년 실적은 감소한 바 있다.')
        self.assertEqual(select_related_evidence('가온 2025년 매출은?', ['가온'], [later], True), [])

    def test_explicit_analysis_failure_is_visible_not_silent_success(self):
        response = present_response({'status':'answered', 'answer':'매출은 123원이에요.',
            'question':'가온 2025년 매출 발생 이유 분석해줘', 'trace_kind':'financial',
            'related_status':'insufficient_evidence', 'related_points':[]})
        self.assertEqual(response['status'], 'partial_evidence')
        self.assertIn('123원', response['answer'])
        self.assertIn('충분히 확보하지 못했어요', response['answer'])

    def test_literal_company_attribution_is_accepted_but_reporter_is_not(self):
        from bulsae.graphrag.document_search import attribution_supported
        text = '회사는 해외 사업 성장 덕분에 영업이익이 늘었다고 설명했어요.'
        self.assertTrue(attribution_supported(text, '회사는 해외 사업 성장 덕분에 영업이익이 증가했다고 설명했다.'))
        self.assertFalse(attribution_supported(text, '해외 사업 성장 덕분에 영업이익이 증가했다.'))
        from bulsae.graphrag.document_search import company_cause_supported
        self.assertTrue(company_cause_supported(
            '회사는 해외 사업 성장과 수익성 개선으로 영업이익이 늘었다고 밝혔어요.',
            '회사는 해외 사업 성장과 수익성 개선으로 영업이익이 증가했다고 설명했다.'))

    def test_simple_finance_keeps_original_question_and_enriches(self):
        question='가온 2025년 매출은?'
        rows=[row('NEWS-a', '가온은 2025년 해외 채널을 확대했다.')]
        related=Mock(return_value=validate_points([point()], rows, True))
        docs=Mock(return_value=rows)
        finance={'name':'가온','year':2025,'period':'연간','scope':'개별','revenue':123,
                 'financial_id':'FIN-x','source_json':json.dumps([{'original_url':'https://example.org/f'}])}
        deps=QueryDeps(lambda *_:[],Mock(),Mock(),financial=lambda *_:[finance],documents=docs,related=related)
        result=build_query_graph(deps).invoke({'question':question,'name':'가온','kind':'company'})
        self.assertEqual(result['question'],question)
        self.assertEqual(related.call_args.args[0],question)
        self.assertIn('123',related.call_args.args[1])
        self.assertTrue(docs.call_args.args[0].startswith(question))
        shown=present_response(result)
        self.assertIn('123',shown['answer'])
        self.assertIn('관련 자료에서 확인한 사실',shown['answer'])
        self.assertEqual(len(shown['sources']),2)
        related.side_effect=RuntimeError('unavailable')
        failed=build_query_graph(deps).invoke({'question':question,'name':'가온','kind':'company'})
        self.assertEqual(failed['status'],'answered')
        self.assertIn('123',present_response(failed)['answer'])
        self.assertEqual(failed['related_points'],[])

    def test_synthesis_requires_two_distinct_documents_and_all_citations(self):
        rows=[row('NEWS-a','가온은 해외 채널을 확대했다.'), row('NEWS-b','가온은 해외 제품을 출시했다.')]
        self.assertEqual(validate_points([point('interpretation')],rows),[])
        refs=[AnalysisCitation(evidence_index=i,quote_ids=[0]) for i in (0,1)]
        accepted=validate_points([point('interpretation',refs)],rows)
        self.assertEqual(len(accepted[0]['citations']),2)
        rows[1]['document_id']='NEWS-a'
        self.assertEqual(validate_points([point('interpretation',refs)],rows),[])
        refs[1].quote_ids=[99]
        self.assertEqual(validate_points([point('interpretation',refs)],rows),[])

    def test_scope_and_invented_finance_or_followups_are_filtered(self):
        rows=[row('NEWS-a','가온은 2025년 해외 채널을 확대했다.'),
              row('NEWS-b','가온은 2026년 해외 채널을 확대했다.')]
        self.assertEqual(len(select_related_evidence('가온 2025년 매출은?', ['가온'], rows, True)),1)
        bad=point().model_copy(update={'text':'가온 매출은 4조 원이에요.'})
        self.assertEqual(validate_points([bad],rows,True),[])
        bad=point().model_copy(update={'text':'해외 채널도 살펴볼까요?'})
        self.assertEqual(validate_points([bad],rows),[])
        bad=point().model_copy(update={'text':'가온은 지난해 해외 채널을 확대했어요.'})
        self.assertEqual(validate_points([bad],rows),[])
        grouped=[row('NEWS-g','가온은 그룹 매출 15조원을 목표로 한다.')]
        bad=point().model_copy(update={'text':'가온은 매출 15조원을 목표로 해요.'})
        self.assertEqual(validate_points([bad],grouped),[])

    def test_company_explanation_rejected_by_semantic_review(self):
        rows=[row('NEWS-a','회사는 해외 채널 확대가 영업이익 증가의 원인이라고 설명했다.')]
        candidate=point('company_explanation').model_copy(update={
            'text':'회사는 해외 채널 확대가 매출 증가의 원인이라고 설명했어요.'})
        client=Mock()
        client.responses.parse.side_effect=[SimpleNamespace(output_parsed=AnalysisResult(points=[candidate])),
            SimpleNamespace(output_parsed=AnalysisDecisions(decisions=[AnalysisDecision(claim_index=0,
                source_supported=True, category_valid=False, adds_information=True,scope_valid=True,
                errors=['영업이익 원인을 매출 원인으로 바꿈'])]))]
        self.assertEqual(generate_related_analysis(client,'test','가온은 어떤 회사야?','기본 답변',rows),[])

    def test_failed_citations_retry_once_without_bypassing_validation(self):
        client=Mock()
        invalid=point().model_copy(update={'citations':[AnalysisCitation(evidence_index=9,quote_ids=[0])]})
        client.responses.parse.return_value=SimpleNamespace(output_parsed=AnalysisResult(points=[invalid]))
        diagnostics={}
        self.assertEqual(generate_related_analysis(client,'test','가온은 어떤 회사야?','기본',
            [row('NEWS-a','가온은 해외 채널을 확대했다.')],diagnostics=diagnostics),[])
        self.assertEqual(client.responses.parse.call_count,2)
        self.assertEqual(diagnostics['citation_retry_valid_points'],0)

    def test_company_cause_cannot_combine_multiple_speakers(self):
        rows=[row('NEWS-a','회사는 해외 사업이 매출 증가의 원인이라고 설명했다.'),
              row('NEWS-b','그룹은 다른 브랜드가 매출 증가의 원인이라고 설명했다.')]
        candidate=point('company_explanation',[AnalysisCitation(evidence_index=i,quote_ids=[0]) for i in (0,1)])
        candidate=candidate.model_copy(update={'text':'회사는 해외 사업이 매출 증가의 원인이라고 설명했어요.'})
        self.assertEqual(validate_points([candidate],rows),[])

    def test_source_numbers_include_all_synthesis_premises(self):
        rows=[row('NEWS-a','가온은 해외 채널을 확대했다.'),row('NEWS-b','가온은 해외 제품을 출시했다.')]
        refs=[AnalysisCitation(evidence_index=i,quote_ids=[0]) for i in (0,1)]
        points=validate_points([point('interpretation',refs)],rows)
        shown=present_response({'status':'answered','answer':'가온은 제조 회사예요.',
            'related_points':points,'related_evidence':rows,'related_status':'supported'})
        self.assertEqual(shown['sections'][0]['heading'],'기본 답변')
        self.assertEqual(shown['sections'][1]['sources'],[1,2])
        self.assertTrue(shown['sections'][1]['heading'].startswith('자료를 종합한 해석'))
        self.assertEqual(shown['trace']['connections'],[])

    def test_repeated_or_wrong_scope_analysis_is_not_returned(self):
        rows=[row('NEWS-a','가온은 해외 채널을 확대했다.')]
        for field in ('source_supported','category_valid','adds_information','scope_valid','relevant_to_question'):
            flags=dict(source_supported=True,category_valid=True,adds_information=True,scope_valid=True,relevant_to_question=True)
            flags[field]=False
            client=Mock()
            client.responses.parse.side_effect=[SimpleNamespace(output_parsed=AnalysisResult(points=[point()])),
                SimpleNamespace(output_parsed=AnalysisDecisions(decisions=[AnalysisDecision(claim_index=0,errors=[],**flags)]))]
            self.assertEqual(generate_related_analysis(client,'test','가온 사업은?','기본 답변',rows),[])

    def test_company_cause_and_synthesis_keep_separate_labels(self):
        cases = [
            (AnalysisPoint(kind='company_explanation', heading='성장 배경',
                text='회사 측은 해외 유통망 확대가 성장의 원인이라고 설명했어요.',
                citations=[AnalysisCitation(evidence_index=0,quote_ids=[0])]),
             [row('NEWS-c','회사 측은 해외 유통망 확대가 성장의 원인이라고 설명했다.')],
             '회사가 밝힌 원인'),
            (AnalysisPoint(kind='interpretation', heading='해외 사업 방향',
                text='자료를 종합하면 해외에서 판매와 제품 구성을 함께 넓히는 움직임으로 해석할 수 있어요.',
                citations=[AnalysisCitation(evidence_index=i,quote_ids=[0]) for i in (0,1)]),
             [row('NEWS-a','가온은 해외 채널을 확대했다.'),row('NEWS-b','가온은 해외 제품을 출시했다.')],
             '자료를 종합한 해석')]
        for candidate,rows,label in cases:
            client=Mock()
            client.responses.parse.side_effect=[SimpleNamespace(output_parsed=AnalysisResult(points=[candidate])),
                SimpleNamespace(output_parsed=AnalysisDecisions(decisions=[AnalysisDecision(claim_index=0,
                    source_supported=True,category_valid=True,adds_information=True,scope_valid=True,
                    relevant_to_question=True,distinct_premises=True,errors=[])]))]
            accepted=generate_related_analysis(client,'test','가온 사업은?','가온은 제조 회사예요.',rows)
            self.assertEqual(len(accepted),1)
            self.assertEqual(accepted[0]['kind'],candidate.kind)
            shown=present_response({'status':'answered','answer':'가온은 제조 회사예요.',
                'related_points':accepted,'related_evidence':rows})
            self.assertTrue(shown['sections'][-1]['heading'].startswith(label))
            self.assertEqual(shown['sections'][-1]['section_type'],'additional')

    def test_duplicate_reporting_is_not_two_synthesis_premises(self):
        refs=[AnalysisCitation(evidence_index=i,quote_ids=[0]) for i in (0,1)]
        rows=[row('NEWS-a','가온은 해외 채널을 확대했다.'),row('NEWS-b','가온은 해외 채널을 확대했다. ')]
        self.assertEqual(validate_points([point('interpretation',refs)],rows),[])
        rows[1]['evidence']='가온은 해외 제품을 출시했다.'
        rows[1]['url']=rows[0]['url']+'#copy'
        self.assertEqual(validate_points([point('interpretation',refs)],rows),[])

    def test_no_evidence_skips_analysis_without_losing_basic_answer(self):
        related=Mock()
        finance={'name':'가온','year':2025,'period':'연간','scope':'개별','revenue':123,
                 'financial_id':'FIN-x','source_json':json.dumps([{'original_url':'https://example.org/f'}])}
        deps=QueryDeps(lambda *_:[],Mock(),Mock(),financial=lambda *_:[finance],documents=lambda *_:[],related=related)
        question='가온 2025년 매출은?'
        result=build_query_graph(deps).invoke({'question':question,'name':'가온','kind':'company'})
        related.assert_not_called()
        self.assertEqual(result['question'],question)
        self.assertEqual(result['related_status'],'insufficient_evidence')
        self.assertIn('123',present_response(result)['answer'])

    def test_failed_additional_search_can_use_already_checked_evidence(self):
        from bulsae.graphrag.document_search import AnswerClaim
        rows=[row('NEWS-a','가온은 해외 채널을 확대했다.')]
        search=Mock(side_effect=[rows, RuntimeError('do not expose details')])
        docs=Mock(side_effect=[rows, RuntimeError('do not expose details')])
        related=Mock(return_value=[])
        deps=QueryDeps(search,lambda *_:[AnswerClaim(text='가온은 해외 채널을 확대했어요.',
            exact_quote=rows[0]['evidence'],evidence_index=0)],lambda *_:{0},documents=docs,related=related)
        result=build_query_graph(deps).invoke({'question':'가온의 해외 활동은?', 'name':'가온','kind':'company'})
        self.assertTrue(related.called)
        self.assertEqual(result['status'],'answered')
        self.assertEqual(result['related_errors'],[{'stage':'related_graph_search','type':'RuntimeError'},
                                                 {'stage':'related_document_search','type':'RuntimeError'}])
        self.assertNotIn('do not expose',json.dumps(result))

if __name__=='__main__': unittest.main()
