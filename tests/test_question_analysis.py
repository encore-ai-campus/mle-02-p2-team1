import unittest
from types import SimpleNamespace

from bulsae.graphrag.question_analysis import QuestionAnalysis, analyze_question, is_executive_event_question


class QuestionAnalysisTests(unittest.TestCase):
    def client(self, result):
        return SimpleNamespace(responses=SimpleNamespace(parse=lambda **_:SimpleNamespace(output_parsed=result)))

    def test_direct_executive_event_query(self):
        q='가온 대표이사가 2026년에 참석한 행사는?'
        plan=QuestionAnalysis(intent='executive_events',role='ceo',year=2026)
        self.assertTrue(is_executive_event_question(q))
        self.assertEqual(analyze_question(self.client(plan),'test',q,'가온')['year'],2026)

    def test_model_cannot_invent_a_year_or_role(self):
        q='가온 대표가 참석한 행사는?'
        plan=QuestionAnalysis(intent='executive_events',role='ceo',year=2026)
        self.assertEqual(analyze_question(self.client(plan),'test',q,'가온')['status'],'unsupported')
        plan=QuestionAnalysis(intent='executive_events',role='chair',year=None)
        self.assertEqual(analyze_question(self.client(plan),'test',q,'가온')['status'],'unsupported')


if __name__ == '__main__':
    unittest.main()
