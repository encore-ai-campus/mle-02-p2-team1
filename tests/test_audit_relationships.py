import hashlib
import json
import unittest
from bulsae.graphrag.audit_relationships import flags


def sample():
    content='가온과 나오는 협약을 체결했다.'
    return {'content':content, 'hash':hashlib.sha256(content.encode()).hexdigest(),
            'evidence':json.dumps([{'text':content,'start':0,'end':len(content)}]),
            'source_type':'Company','target_type':'Company','relation':'PARTNERS_WITH'}


class RelationshipAuditTests(unittest.TestCase):
    def test_valid_source_and_pattern(self):
        self.assertEqual(flags(sample()),[])

    def test_changed_source_and_invalid_offsets_flagged(self):
        row=sample();row['content']='다른 본문'
        self.assertIn('source_content_changed',flags(row))
        self.assertIn('evidence_offset_mismatch',flags(row))

    def test_keyword_absence_is_review_not_rejection(self):
        row=sample();content='가온과 나오는 행사에 있다.'
        row.update(content=content,hash=hashlib.sha256(content.encode()).hexdigest(),
                   evidence=json.dumps([{'text':content,'start':0,'end':len(content)}]))
        self.assertEqual(flags(row),['relation_word_not_obvious'])


if __name__ == '__main__':
    unittest.main()
