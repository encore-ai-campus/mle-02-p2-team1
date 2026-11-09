import unittest
from types import SimpleNamespace

from bulsae.graphrag.document_graph import (
    EntityCandidate, ExtractionResult, RelationCandidate, make_rows, numbered_lines,
    resolve_id, validate_document, verify_semantics, ambiguous_company_mention,
)


class DocumentGraphTests(unittest.TestCase):
    def setUp(self):
        self.doc = {'document_id':'NEWS-1', 'content':'광고\n\n김승환 아모레퍼시픽 대표가 참석했다.\n',
                    'published_at':'2026-01-01'}
        self.companies = [{'company_id':'COMPANY-AMOREPACIFIC','name':'아모레퍼시픽',
                           'legal_name':'주식회사 아모레퍼시픽'}]
        self.lines = numbered_lines(self.doc['content'])
        self.person = EntityCandidate(local_id='N1',node_type='Person',name='김승환',
            description=None,evidence_line_ids=['L0003'],financial_details=None)
        self.company = EntityCandidate(local_id='N2',node_type='Company',name='아모레퍼시픽',
            description=None,evidence_line_ids=['L0003'],financial_details=None)
        self.relation = RelationCandidate(source_local_id='N1',relation_type='WORKS_AT',
            target_local_id='N2',detail='대표',date_text=None,reported_status='발생',
            evidence_line_ids=['L0003'],relevance_line_ids=[])

    def test_lines_reference_stored_document_with_blank_lines(self):
        record=self.lines['L0003']
        self.assertEqual(self.doc['content'][record['start']:record['end']],record['text'])
        self.assertNotIn('L0002',self.lines)

    def test_direct_company_fallback_and_evidence_offsets(self):
        result=ExtractionResult(nodes=[self.person,self.company],relations=[self.relation])
        accepted,issues=validate_document(self.doc,result,self.lines,self.companies)
        self.assertEqual(len(accepted),1)
        self.assertEqual(issues,[])
        rows=make_rows(self.doc,accepted,self.lines,self.companies,'model')
        self.assertEqual(rows[0]['target_id'],'COMPANY-AMOREPACIFIC')
        self.assertEqual(rows[0]['relevance_line_ids'],['L0003'])
        ev=rows[0]['evidence'][0]
        self.assertEqual(self.doc['content'][ev['start']:ev['end']],ev['text'])

    def test_missing_evidence_and_wrong_direction_are_quarantined(self):
        r=self.relation.model_copy(update={'source_local_id':'N2','target_local_id':'N1',
                                           'evidence_line_ids':['L9999']})
        accepted,issues=validate_document(self.doc,ExtractionResult(nodes=[self.person,self.company],relations=[r]),
                                           self.lines,self.companies)
        self.assertEqual(accepted,[])
        reasons=issues[-1]['reasons']
        self.assertIn('invalid_relation_pattern',reasons)
        self.assertIn('invalid_relation_evidence',reasons)

    def test_ambiguous_person_identity_is_document_scoped(self):
        first,_=resolve_id(self.doc,self.person.model_dump(),self.companies)
        second,_=resolve_id({**self.doc,'document_id':'NEWS-2'},self.person.model_dump(),self.companies)
        self.assertNotEqual(first,second)

    def test_semantic_review_rejects_incomplete_results(self):
        result=ExtractionResult(nodes=[self.person,self.company],relations=[self.relation])
        accepted,_=validate_document(self.doc,result,self.lines,self.companies)
        class Responses:
            def parse(self, **kwargs):
                return SimpleNamespace(status='completed', output_parsed=SimpleNamespace(checks=[]), usage=None)
        with self.assertRaisesRegex(ValueError,'semantic_review_missing_or_duplicate'):
            verify_semantics(self.doc,accepted,self.lines,SimpleNamespace(responses=Responses()),'model')

    def test_work_date_is_not_promoted_to_employment_date(self):
        r=self.relation.model_copy(update={'date_text':'2026년'})
        accepted,issues=validate_document(self.doc,ExtractionResult(nodes=[self.person,self.company],relations=[r]),
                                           self.lines,self.companies)
        self.assertEqual(len(accepted),1)
        self.assertIsNone(accepted[0]['relation']['date_text'])
        self.assertEqual(accepted[0]['relation']['unassigned_date_text'],'2026년')

    def test_endpoint_repair_requires_unique_exact_type_and_name(self):
        brand=EntityCandidate(local_id='Company_아모레퍼시픽',node_type='Brand',name='아모레퍼시픽',
            description=None,evidence_line_ids=['L0003'],financial_details=None)
        r=self.relation.model_copy(update={'source_local_id':'N2','relation_type':'OPERATES_BRAND',
                                          'target_local_id':'Brand_아모레퍼시픽'})
        accepted,issues=validate_document(self.doc,ExtractionResult(nodes=[self.company,brand],relations=[r]),
                                           self.lines,self.companies)
        self.assertEqual(len(accepted),1)
        self.assertEqual(accepted[0]['relation']['target_local_id'],'Company_아모레퍼시픽')
        self.assertTrue(any('unambiguous_endpoint_id_resolved' in item['reasons'] for item in issues))

    def test_indirect_relation_requires_target_company_relevance(self):
        person=self.person.model_copy(update={'name':'홍길동'})
        company=self.company.model_copy(update={'name':'다른회사'})
        doc={**self.doc,'content':'홍길동 다른회사 대표다.'}
        lines=numbered_lines(doc['content'])
        person=person.model_copy(update={'evidence_line_ids':['L0001']})
        company=company.model_copy(update={'evidence_line_ids':['L0001']})
        relation=self.relation.model_copy(update={'evidence_line_ids':['L0001']})
        accepted,issues=validate_document(doc,ExtractionResult(nodes=[person,company],relations=[relation]),
                                           lines,self.companies)
        self.assertEqual(accepted,[])
        self.assertIn('target_company_relevance_unproven',issues[-1]['reasons'])

    def test_same_article_observation_id_is_stable_when_detail_changes(self):
        result=ExtractionResult(nodes=[self.person,self.company],relations=[self.relation])
        accepted,_=validate_document(self.doc,result,self.lines,self.companies)
        first=make_rows(self.doc,accepted,self.lines,self.companies,'model')[0]
        accepted[0]['relation']['detail']='대표이사 보도'
        second=make_rows(self.doc,accepted,self.lines,self.companies,'model')[0]
        self.assertEqual(first['observation_id'],second['observation_id'])

    def test_corporate_name_ambiguity_flags_only_compound_only_evidence(self):
        self.assertTrue(ambiguous_company_mention('COMPANY-AMOREPACIFIC','아모레퍼시픽그룹의 매출'))
        self.assertTrue(ambiguous_company_mention('COMPANY-INNISFREE','이니스프리 모음재단 행사'))
        self.assertFalse(ambiguous_company_mention('COMPANY-AMOREPACIFIC','아모레퍼시픽의 매출'))
        self.assertFalse(ambiguous_company_mention('COMPANY-AMOREPACIFIC','아모레퍼시픽그룹과 아모레퍼시픽'))


if __name__ == '__main__':
    unittest.main()
