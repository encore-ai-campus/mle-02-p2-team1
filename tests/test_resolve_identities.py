import json
import unittest

from bulsae.graphrag.resolve_identities import backed_texts
from bulsae.graphrag.resolve_more import person_key, legal_key


class EvidenceTests(unittest.TestCase):
    def test_only_evidence_in_the_source_document_is_used(self):
        row = {'content': '김승환 아모레퍼시픽 대표', 'evidence': json.dumps([
            {'text': '김승환 아모레퍼시픽 대표'}, {'text': '다른 기사 내용'}
        ], ensure_ascii=False)}
        self.assertEqual(backed_texts(row), ['김승환 아모레퍼시픽 대표'])

    def test_invalid_evidence_is_not_accepted(self):
        self.assertEqual(backed_texts({'content': '본문', 'evidence': '{'}), [])

    def test_person_requires_source_name_company_and_role(self):
        row = {'name': '홍길동', 'company': '가온회사', 'content': '홍길동 가온회사 대표가 말했다.',
               'evidence': json.dumps([{'text': '홍길동 가온회사 대표가 말했다.'}], ensure_ascii=False)}
        self.assertEqual(person_key(row), ('홍길동', '가온회사', '대표'))
        row['content'] = '근거 없는 내용'
        self.assertIsNone(person_key(row))

    def test_company_does_not_resolve_ambiguous_brand_name(self):
        row = {'name': '오설록', 'content': '오설록 브랜드',
               'evidence': json.dumps([{'text': '오설록 브랜드'}], ensure_ascii=False)}
        self.assertIsNone(legal_key(row))


if __name__ == '__main__':
    unittest.main()
