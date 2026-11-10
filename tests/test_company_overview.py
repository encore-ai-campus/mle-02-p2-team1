import json
import unittest
from datetime import datetime, timezone

from bulsae.graphrag.company_information import recent_candidates, render_company_business
from bulsae.graphrag.web_server import present_response


class CompanyOverviewTests(unittest.TestCase):
    def test_profile_omits_missing_values_and_preserves_source_availability(self):
        source = json.dumps({'main_business':[{'original_url':'https://example.org/business'}],
                             'established_date':[{'original_url':'https://example.org/date'}]})
        result = render_company_business('가온', [{'name':'가온','company_id':'C1','business':'화장품 제조',
            'legal_name':'가온 주식회사','established_date':'2000-01-01','employee_count':None,
            'industry':'화장품','listing_status':'', 'sources':source}])
        fields = {field['field']:field for field in result['company_profile']}
        self.assertEqual(set(fields), {'legal_name','industry','established_date'})
        self.assertIsNone(fields['industry']['source_url'])
        self.assertEqual(fields['established_date']['source_url'], 'https://example.org/date')

    def test_no_business_keeps_real_profile_without_inventing_business(self):
        result = render_company_business('가온', [{'name':'가온','company_id':'C1','business':None,
             'industry':'화장품','sources':'{}'}])
        self.assertEqual(result['status'],'answered')
        self.assertIsNone(result['company_business'])
        self.assertEqual(result['structured_sources'],[])

    def test_recent_candidates_exclude_future_unrelated_and_duplicates(self):
        now = datetime(2026, 11, 9, tzinfo=timezone.utc)
        def row(id, title, date, text='가온이 제품을 출시했다.'):
            return {'document_id':id,'title':title,'published_at':date,'content':text,'url':'https://example.org/'+id}
        rows = [row('A','가온 신제품 출시','2026-11-08T03:00:00Z'),
                row('B','가온 신제품 출시!','2026-11-07T03:00:00Z'),
                row('C','다른 회사 소식','2026-11-08T03:00:00Z'),
                row('D','가온 신규 전략','2026-11-10T03:00:00Z'),
                row('E','가온 협약 체결','2026-11-06T03:00:00Z')]
        self.assertEqual([r['document_id'] for r in recent_candidates(rows,'가온',now)], ['A','E'])

    def test_news_citations_survive_presentation(self):
        result = {'status':'answered','name':'가온','trace_kind':'company_info','answer':'사업 소개',
            'company_profile':[{'label':'업종','value':'화장품','source_url':None,'source_file':'company_info.jsonl'}],
            'company_business':'화장품 제조','structured_sources':[{'document_id':'C1','url':'https://example.org/info',
                'title':'기업 정보','evidence':'화장품 제조','source_file':'company_info.jsonl'}],
            'recent_status':'found','recent_news':[{'heading':'제품 출시','text':'가온이 제품을 출시했다.',
                'kind':'reported_fact','document_id':'N1','title':'가온 제품 출시','url':'https://example.org/news',
                'published_at':'2026-11-08T03:00:00Z','evidence':'가온이 제품을 출시했다.'}]}
        response = present_response(result)
        overview = response['company_overview']
        self.assertEqual(response['sources'][overview['news'][0]['source_number']-1]['document_id'], 'N1')
        self.assertEqual(response['sources'][overview['fields'][0]['source_number']-1]['url'], '')

    def test_business_analysis_uses_business_sources_only(self):
        from bulsae.graphrag.related_analysis import final_answer_facts
        response = {'lead':'화장품 제조','sections':[], 'financial_cards':[],
            'sources':[{'number':1,'source_file':'company_info.jsonl'}, {'number':2,'source_file':'companies.jsonl'}],
            'company_overview':{'business_sources':[1]}}
        self.assertEqual(final_answer_facts(response)[0]['sources'], [1])

    def test_publication_date_is_korean_time_and_does_not_guess_naive_time(self):
        from bulsae.graphrag.streamlit_ui import publication_day
        self.assertEqual(publication_day('2026-11-05T22:00:00Z'), '2026-11-06')
        self.assertEqual(publication_day('2026-11-05T22:00:00'), '')

    def test_similar_product_news_appears_once(self):
        from unittest.mock import patch
        from bulsae.graphrag.company_information import fetch_recent_company_news
        from bulsae.graphrag.document_search import AnswerClaim
        class Record:
            def __init__(self, data): self.row = data
            def data(self): return self.row
        titles = ['가온, 립밤 신제품 공개','가온, 새 립밤 출시 소식','가온, 팔레트 출시']
        rows = [Record({'document_id':str(i),'title':titles[i],
              'published_at':f'2026-11-0{8-i}T03:00:00Z','url':f'https://example.org/{i}',
              'content':text}) for i,text in enumerate(["가온은 '글로이 구미 밤' 제품을 출시했다.",
              "가온은 '글로이 구미 밤' 출시를 발표했다.","가온은 신규 팔레트를 출시했다."])]
        def generate(question, evidence):
            return [AnswerClaim(heading=row['title'], text=row['evidence'], exact_quote=row['evidence'],
                                evidence_index=i) for i,row in enumerate(evidence)]
        with patch('bulsae.graphrag.company_information.query_readonly',return_value=rows):
            items = fetch_recent_company_news(None, '가온', generate, lambda q,c,e: set(range(len(c))))
        self.assertEqual([i['document_id'] for i in items], ['0','2'])


if __name__ == '__main__':
    unittest.main()
