import unittest

from bulsae.graphrag.resolve_llm import Cluster, validate


def node(node_id):
    return {'node_id':node_id, 'candidate_id':node_id, 'name':'홍길동', 'kind':'Person',
            'source':{'document_id':'NEWS-1', 'observation_id':'OBS-1'}}


class IdentityReviewTests(unittest.TestCase):
    def test_uses_existing_representative_and_preserves_source(self):
        groups = [{'nodes':[node('a'),node('b'),node('c')]}]
        plan = validate(groups, [Cluster(group=0,members=[0,1,2],reason='same')], {'b'})
        self.assertEqual({p['source'] for p in plan}, {'a','c'})
        self.assertEqual({p['target'] for p in plan}, {'b'})
        self.assertEqual({p['document_id'] for p in plan}, {'NEWS-1'})

    def test_conflicting_anchors_and_invalid_ids_are_rejected(self):
        groups = [{'nodes':[node('a'),node('b')]}]
        self.assertEqual(validate(groups, [Cluster(group=0,members=[0,1],reason='')], {'a','b'}), [])
        self.assertEqual(validate(groups, [Cluster(group=0,members=[0,2],reason='')], set()), [])


if __name__ == '__main__':
    unittest.main()
