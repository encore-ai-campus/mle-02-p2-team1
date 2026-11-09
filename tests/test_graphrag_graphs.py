import unittest

from bulsae.graphrag.document_search import AnswerClaim
from bulsae.graphrag.graphs import ABSTAIN, FAILURE, QueryDeps, build_query_graph


def evidence(**overrides):
    row = {'document_id':'NEWS-a1', 'url':'https://example.org/a',
           'evidence':'홍길동이 행사에 참석했다.', 'source_verified':True,
           'relation':'PARTICIPATED_IN', 'representative_id':'p1'}
    return {**row, **overrides}


class QueryGraphTests(unittest.TestCase):
    def test_strategy_question_uses_announced_strategy_evidence(self):
        calls = []
        row = evidence(evidence='가온은 해외 사업 확대 전략을 발표했다.', relation='ANNOUNCED_STRATEGY')
        def strategy(name, year):
            calls.append((name, year))
            return [row]
        def unexpected(*args):
            raise AssertionError('Unrelated general news search must not run')
        deps = QueryDeps(unexpected,
                        lambda *_: [AnswerClaim(text='가온은 해외 사업을 확대할 계획이에요.', evidence_index=0, exact_quote=row['evidence'])],
                        lambda *_: {0}, strategy=strategy)
        result = build_query_graph(deps).invoke({'name': '가온', 'kind': 'company', 'question': '가온의 성장 전략을 알려줘'})
        self.assertEqual(calls, [('가온', None)])
        self.assertEqual(result['status'], 'answered')

    def run_graph(self, search, generate, review, question='홍길동이 참석한 행사는?'):
        return build_query_graph(QueryDeps(search, generate, review)).invoke(
            {'name':'홍길동', 'kind':'person', 'question':question})

    def test_verified_evidence_produces_cited_answer(self):
        result = self.run_graph(lambda *_:[evidence()],
            lambda *_:[AnswerClaim(text='홍길동이 행사에 참석했다.', evidence_index=0, exact_quote='홍길동이 행사에 참석했다.')],
            lambda *_:{0})
        self.assertEqual(result['status'], 'answered')
        self.assertIn('NEWS-a1', result['answer'])
        self.assertIn('https://example.org/a', result['answer'])

    def test_no_verified_source_never_calls_model(self):
        def unexpected(*_):
            raise AssertionError('model must not run')
        result = self.run_graph(lambda *_:[evidence(source_verified=False)], unexpected, unexpected)
        self.assertEqual(result['answer'], ABSTAIN)

    def test_unrelated_event_relation_is_excluded(self):
        result = self.run_graph(lambda *_:[evidence(relation='WORKS_AT')], lambda *_:[], lambda *_:set())
        self.assertEqual(result['answer'], ABSTAIN)

    def test_company_relationship_question_ignores_brand_and_events(self):
        rows = [evidence(relation='OPERATES_BRAND', other_labels=['BulsaeBrand']),
                evidence(relation='PARTNERS_WITH', other_labels=['BulsaeOrganization'])]
        valid = AnswerClaim(text='홍길동이 행사에 참석했다.', evidence_index=0, exact_quote='홍길동이 행사에 참석했다.')
        result = self.run_graph(lambda *_:rows, lambda *_:[valid], lambda *_:{0},
                                question='가온회사의 기업 관계는?')
        self.assertEqual(len(result['evidence']), 1)
        self.assertEqual(result['evidence'][0]['relation'], 'PARTNERS_WITH')

    def test_invalid_citation_and_rejected_claim_abstain(self):
        bad = AnswerClaim(text='허위', evidence_index=10, exact_quote='홍길동이 행사에 참석했다.')
        result = self.run_graph(lambda *_:[evidence()], lambda *_:[bad], lambda *_:{0})
        self.assertEqual(result['answer'], ABSTAIN)
        valid = AnswerClaim(text='홍길동이 행사에 참석했다.', evidence_index=0, exact_quote='홍길동이 행사에 참석했다.')
        result = self.run_graph(lambda *_:[evidence()], lambda *_:[valid], lambda *_:set())
        self.assertEqual(result['answer'], ABSTAIN)

    def test_failed_database_does_not_generate_an_answer(self):
        def fails(*_):
            raise RuntimeError('database unavailable')
        result = self.run_graph(fails, lambda *_:[], lambda *_:set())
        self.assertEqual(result['status'], 'search_error')
        self.assertEqual(result['answer'], FAILURE)

    def test_failed_review_does_not_generate_an_answer(self):
        def fails(*_):
            raise RuntimeError('review unavailable')
        valid = AnswerClaim(text='홍길동이 행사에 참석했다.', evidence_index=0, exact_quote='홍길동이 행사에 참석했다.')
        result = self.run_graph(lambda *_:[evidence()], lambda *_:[valid], fails)
        self.assertEqual(result['status'], 'review_error')
        self.assertEqual(result['answer'], FAILURE)

    def test_question_only_identifies_and_searches(self):
        captured = []
        def search(name, kind, limit):
            captured.append((name, kind))
            return [evidence()]
        deps = QueryDeps(search, lambda *_:[AnswerClaim(text='홍길동이 행사에 참석했다.',evidence_index=0,exact_quote='홍길동이 행사에 참석했다.')],
                         lambda *_:{0}, lambda _: {'status':'resolved','name':'홍길동','kind':'person'})
        result = build_query_graph(deps).invoke({'question':'홍길동이 참석한 행사는?'})
        self.assertEqual(captured, [('홍길동','person')])
        self.assertEqual(result['status'], 'answered')

    def test_ambiguous_target_does_not_call_search_or_models(self):
        def unexpected(*_):
            raise AssertionError('must not call')
        deps = QueryDeps(unexpected, unexpected, unexpected,
                         lambda _: {'status':'ambiguous','candidates':[{'name':'홍길동','kind':'person'},{'name':'김철수','kind':'person'}]})
        result = build_query_graph(deps).invoke({'question':'두 사람을 비교해줘'})
        self.assertEqual(result['status'], 'ambiguous_entity')
        self.assertIn('홍길동',result['answer'])

    def test_company_context_requires_backed_employment(self):
        rows = [evidence(representative_id='wrong'),
                evidence(representative_id='right'),
                evidence(representative_id='right',relation='WORKS_AT', other_name='가온회사')]
        deps = QueryDeps(lambda *_:rows,
                         lambda _, items:[AnswerClaim(text='홍길동이 행사에 참석했다.',evidence_index=0,exact_quote='홍길동이 행사에 참석했다.')],
                         lambda *_:{0}, lambda _: {'status':'resolved','name':'홍길동','kind':'person','company_context':'가온회사'})
        result = build_query_graph(deps).invoke({'question':'홍길동 가온회사 대표가 참석한 행사'})
        self.assertEqual([r['representative_id'] for r in result['evidence']], ['right'])

    def test_company_comparison_keeps_each_source_separate(self):
        companies = [{'name':'가온','kind':'company'},{'name':'나온','kind':'company'}]
        def search(name, *_):
            return [evidence(evidence=f'{name} 회사가 파트너와 협력했다.', relation='PARTNERS_WITH')]
        def generate(_, rows):
            return [AnswerClaim(text=rows[0]['evidence'], evidence_index=0, exact_quote=rows[0]['evidence'])]
        deps = QueryDeps(search, generate, lambda *_:{0,1},
                         lambda _: {'status':'resolved_compare','entities':companies})
        result = build_query_graph(deps).invoke({'question':'가온과 나온의 협력 사례를 비교해줘'})
        self.assertEqual(result['status'],'answered')
        self.assertIn('[가온]',result['answer'])
        self.assertIn('[나온]',result['answer'])

    def test_company_comparison_abstains_when_one_side_missing(self):
        companies = [{'name':'가온','kind':'company'},{'name':'나온','kind':'company'}]
        def search(name, *_):
            return [evidence(evidence='가온 회사의 협력 사례입니다.')] if name == '가온' else []
        def must_not_call(*_):
            raise AssertionError('Do not generate partial comparison')
        deps = QueryDeps(search, must_not_call, must_not_call,
                         lambda _: {'status':'resolved_compare','entities':companies})
        result = build_query_graph(deps).invoke({'question':'가온과 나온 협력을 비교해줘'})
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertIn('나온',result['answer'])

    def test_comparison_rejects_one_sided_model_answer(self):
        companies = [{'name':'가온','kind':'company'},{'name':'나온','kind':'company'}]
        def search(name, *_):
            return [evidence(evidence=f'{name} 회사가 파트너와 협력했다.', relation='PARTNERS_WITH')]
        deps = QueryDeps(search, lambda _,rows:([AnswerClaim(text=rows[0]['evidence'],evidence_index=0,exact_quote=rows[0]['evidence'])]
                                               if rows[0]['comparison_company']=='가온' else []),
                         lambda *_:{0}, lambda _: {'status':'resolved_compare','entities':companies})
        result = build_query_graph(deps).invoke({'question':'가온과 나온 협력을 비교해줘'})
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertIn('나온',result['answer'])

    def test_financial_comparison_uses_no_llm(self):
        import json
        companies = [{'name':'가온','kind':'company'},{'name':'나온','kind':'company'}]
        def must_not_call(*_):
            raise AssertionError('financial comparison should not call LLM')
        def financial(_):
            source = json.dumps([{'original_url':'https://example.org','source_name':'공시'}])
            return [{'name':name,'year':2025,'period':'연간','scope':'개별','revenue':value,'source_json':source}
                    for name,value in [('가온',100),('나온',40)]]
        deps = QueryDeps(must_not_call, must_not_call, must_not_call,
                         lambda _: {'status':'resolved_compare','entities':companies}, financial)
        result = build_query_graph(deps).invoke({'question':'가온과 나온의 2025년 매출 비교'})
        self.assertEqual(result['status'],'answered')
        self.assertIn('60원',result['answer'])

    def test_single_company_financial_query(self):
        import json
        row = {'name':'가온','year':2025,'period':'연간','scope':'개별','revenue':100,
               'source_json':json.dumps([{'original_url':'https://example.org'}])}
        deps = QueryDeps(lambda *_:[], lambda *_:[], lambda *_:set(),
                         lambda _: {'status':'resolved','name':'가온','kind':'company'}, lambda _: [row])
        result = build_query_graph(deps).invoke({'question':'가온의 2025년 매출은?'})
        self.assertEqual(result['status'], 'answered')
        self.assertIn('100원',result['answer'])

    def test_basic_company_business_has_collected_source(self):
        import json
        source = json.dumps({'main_business':[{'original_url':'https://example.org','title':'사업보고서'}]})
        deps = QueryDeps(lambda *_:[], lambda *_:[], lambda *_:set(),
                         lambda _: {'status':'resolved','name':'가온','kind':'company'},
                         company_info=lambda _: [{'name':'가온','business':'가온은 화장품을 판매한다.','sources':source}])
        result = build_query_graph(deps).invoke({'question':'가온은 어떤 사업을 하는 회사야?'})
        self.assertEqual(result['status'],'answered')
        self.assertIn('화장품',result['answer'])
        self.assertIn('https://example.org',result['answer'])

    def test_mixed_financial_and_strategy_combines_verified_sources(self):
        import json
        row = {'name':'가온','year':2025,'period':'연간','scope':'개별','revenue':100,
               'source_json':json.dumps([{'original_url':'https://example.org'}])}
        news = evidence(evidence='가온은 해외 성장 전략을 발표했다.', relation='ANNOUNCED_STRATEGY')
        deps = QueryDeps(lambda *_:[],
                         lambda _,rows:[AnswerClaim(text=rows[0]['evidence'], evidence_index=0,exact_quote=rows[0]['evidence'])],
                         lambda *_:{0}, lambda _: {'status':'resolved','name':'가온','kind':'company'},
                         lambda _: [row], lambda *_:[news])
        result = build_query_graph(deps).invoke({'question':'가온의 2025년 매출과 성장 전략을 알려줘'})
        self.assertEqual(result['status'], 'answered')
        self.assertIn('100원',result['answer'])
        self.assertIn('NEWS-a1',result['answer'])
        self.assertIn('인과관계',result['answer'])

    def test_mixed_query_never_guesses_a_change_from_one_year(self):
        deps = QueryDeps(lambda *_:[], lambda *_:[], lambda *_:set(),
                         lambda _: {'status':'resolved','name':'가온','kind':'company'})
        result = build_query_graph(deps).invoke({'question':'가온의 2025년 매출이 변할 때 성장 전략은?'})
        self.assertEqual(result['status'], 'unsupported_comparison')
        result = build_query_graph(deps).invoke({'question':'가온 매출이 2025년 변한 시기 성장 전략은?'})
        self.assertEqual(result['status'], 'unsupported_comparison')

    def test_document_context_retries_once_with_existing_source_id(self):
        calls = []
        first = evidence(evidence='홍길동이 행사에 참석했다.')
        def generate(_, rows):
            calls.append('generate')
            if len(calls) == 1:
                return []
            return [AnswerClaim(text='홍길동이 행사에 참석했다.',evidence_index=0,exact_quote='홍길동이 행사에 참석했다.')]
        def context(ids):
            self.assertEqual(ids, ['NEWS-a1'])
            return [{'document_id':'NEWS-a1','url':'https://example.org/a',
                     'content':'본문: 홍길동이 행사에 참석했다.'}]
        deps = QueryDeps(lambda *_:[first], generate, lambda *_:{0}, context=context)
        result = build_query_graph(deps).invoke({'name':'홍길동','kind':'person','question':'홍길동이 참석한 행사는?'})
        self.assertEqual(result['status'],'answered')
        self.assertEqual(len(calls),2)
        self.assertEqual(result['context_attempts'],1)

    def test_document_context_never_retries_more_than_once(self):
        calls = []
        def generate(*_):
            calls.append('generate')
            return []
        deps = QueryDeps(lambda *_:[evidence()], generate, lambda *_:set(),
                         context=lambda ids:[{'document_id':'NEWS-a1','url':'https://example.org','content':'본문입니다.'}])
        result = build_query_graph(deps).invoke({'name':'홍길동','kind':'person','question':'홍길동이 참석한 행사는?'})
        self.assertEqual(len(calls),2)
        self.assertEqual(result['status'],'insufficient_evidence')

    def test_llm_plan_routes_to_bounded_two_hop_path(self):
        def search(*_):
            raise AssertionError('single-hop retrieval must not be used')
        def paths(name, role, year):
            self.assertEqual((name,role,year),('가온','ceo',2026))
            return [{'company':'가온','person':'홍길동','event':'2026 박람회',
                     'document_id':'NEWS-a1','url':'https://example.org',
                     'work_evidence':'홍길동 가온 대표','event_evidence':'홍길동이 2026 박람회에 참석했다.'}]
        deps = QueryDeps(search, lambda *_:[],lambda *_:set(),
                         lambda _: {'status':'resolved','name':'가온','kind':'company'},
                         analyze=lambda *_:{'status':'executive_events','role':'ceo','year':2026},
                         multihop=paths)
        result=build_query_graph(deps).invoke({'question':'가온 대표가 2026년에 참석한 행사는?'})
        self.assertEqual(result['status'],'answered')
        self.assertIn('2026 박람회',result['answer'])

    def test_hallucinated_plan_year_is_not_executed(self):
        def never(*_):
            raise AssertionError('unexpected query')
        deps=QueryDeps(never,never,never,lambda _: {'status':'resolved','name':'가온','kind':'company'},
                       analyze=lambda *_:{'status':'executive_events','role':'ceo','year':2025},multihop=never)
        result=build_query_graph(deps).invoke({'question':'가온 대표가 2026년에 참석한 행사는?'})
        self.assertEqual(result['status'],'insufficient_evidence')


if __name__ == '__main__':
    unittest.main()
