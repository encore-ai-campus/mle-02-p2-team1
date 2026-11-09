import unittest
from bulsae.graphrag.multihop_search import work_role_supported,event_supported,render_paths


class MultihopTests(unittest.TestCase):
    def test_job_evidence_keeps_company_and_role_distinct(self):
        self.assertTrue(work_role_supported('김승환','아모레퍼시픽','ceo','김승환 아모레퍼시픽 대표가 발언했다.'))
        self.assertFalse(work_role_supported('김승환','아모레퍼시픽','ceo','김승환 아모레퍼시픽그룹 대표가 발언했다.'))
        self.assertFalse(work_role_supported('김승환','아모레퍼시픽','chair','김승환 아모레퍼시픽 대표가 발언했다.'))

    def test_event_requires_explicit_event_year_and_participation(self):
        text='김승환이 2026 인베스터 데이에서 전략을 발표했다.'
        self.assertTrue(event_supported('김승환','2026 인베스터 데이',2026,text))
        self.assertFalse(event_supported('김승환','2026 인베스터 데이',2025,text))
        self.assertFalse(event_supported('김승환','2026 인베스터 데이',2026,'김승환과 2026 인베스터 데이'))

    def test_empty_paths_do_not_assert_attendance(self):
        self.assertIn('찾지 못했어요',render_paths([], 'ceo', 2026))


if __name__ == '__main__':
    unittest.main()
