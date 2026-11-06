import unittest
from unittest.mock import patch
from bulsae.graphrag import pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.chunk = {'chunk_id': 'c1', 'document_id': 'd1', 'start_char': 10,
                      'text': '아모레퍼시픽이 회사와 협력했다.'}
        self.claim = {'subject': '아모레퍼시픽', 'subject_type': 'Company', 'relation': 'PARTNERS_WITH',
                      'object': '회사', 'object_type': 'Company', 'evidence': '회사와 협력했다',
                      'time': '', 'status': 'reported'}

    def test_exact_evidence_and_location(self):
        good, bad = pipeline.validate_claims(self.chunk, [self.claim, {**self.claim, 'evidence': '존재하지 않음'}])
        self.assertEqual(len(good), 1)
        self.assertEqual(len(bad), 1)
        row = pipeline.graph_rows({'chunk': self.chunk, 'claims': good})[0]
        self.assertEqual(row['subject_id'], 'COMPANY-AMOREPACIFIC')
        self.assertEqual(row['evidence_start'], 10 + self.chunk['text'].index(self.claim['evidence']))
        self.assertEqual(row['evidence_end'] - row['evidence_start'], len(self.claim['evidence']))
        with self.assertRaises(ValueError):
            pipeline.graph_rows({'chunk': self.chunk, 'claims': [bad[0]['claim']]})

    def test_ambiguous_entities_scoped_by_document(self):
        self.assertNotEqual(pipeline.entity_id('a', 'Person', '김씨'), pipeline.entity_id('b', 'Person', '김씨'))
        self.assertEqual(pipeline.entity_id('a', 'Company', '아모레퍼시픽'), pipeline.entity_id('b', 'Company', '아모레퍼시픽'))

    def test_response_failure_does_not_silently_accept_partial(self):
        with patch.object(pipeline, 'api', return_value={'status': 'incomplete', 'output': []}):
            with self.assertRaises(ValueError):
                pipeline.response_text({})


if __name__ == '__main__':
    unittest.main()
