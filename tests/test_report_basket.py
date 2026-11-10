import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from bulsae.graphrag import report_basket
from bulsae.graphrag.streamlit_ui import basket_report


class ReportBasketTest(unittest.TestCase):
    def test_saved_answers_survive_reload_keep_sources_and_remove_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'basket.sqlite'
            first = {'run_id': 'first', 'question': '첫 질문', 'answer': '첫 답변',
                     'sources': [{'number': 1, 'title': '근거', 'url': 'https://example.com'}]}
            second = {'run_id': 'second', 'question': '두 번째 질문', 'answer': '두 번째 답변', 'sources': []}
            self.assertEqual(report_basket.list_answers(path), [])
            self.assertFalse(path.exists())
            self.assertTrue(report_basket.save_answer(first, path))
            self.assertFalse(report_basket.save_answer(first, path))
            self.assertTrue(report_basket.save_answer(second, path))
            items = report_basket.list_answers(path)
            self.assertEqual([x['id'] for x in items], ['second', 'first'])
            report = basket_report(items)
            self.assertIn('첫 질문', report)
            self.assertIn('두 번째 답변', report)
            self.assertIn('https://example.com', report)
            report_basket.remove_answer('first', path)
            self.assertEqual([x['id'] for x in report_basket.list_answers(path)], ['second'])

    def test_user_saves_opens_and_removes_an_answer(self):
        app_path = Path(__file__).resolve().parents[1] / 'streamlit_app.py'
        result = {'run_id': 'ui-test', 'status': 'answered', 'answer': '자료에 근거한 답변',
                  'sections': [], 'sources': [], 'trace': {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'basket.sqlite'
            original_list, original_save, original_remove = (report_basket.list_answers,
                report_basket.save_answer, report_basket.remove_answer)
            with patch.object(report_basket, 'list_answers', side_effect=lambda: original_list(path)), \
                 patch.object(report_basket, 'save_answer', side_effect=lambda answer: original_save(answer, path)), \
                 patch.object(report_basket, 'remove_answer', side_effect=lambda item_id: original_remove(item_id, path)), \
                 patch.dict(os.environ, {'BULSAE_LOCAL_BASKET': '1'}), \
                 patch('bulsae.graphrag.streamlit_ui.run_question', return_value=result):
                app = AppTest.from_file(str(app_path)).run()
                app.text_area[0].set_value('가온의 사업은?')
                app.button(key='submit_question').click().run()
                self.assertEqual(app.button(key='save_to_basket').label, '장바구니 담기')
                app.button(key='save_to_basket').click().run()
                self.assertEqual(len(original_list(path)), 1)
                self.assertTrue(any('content:"1"' in x.value and 'border-radius:999px' in x.value
                                    for x in app.markdown))
                self.assertTrue(any('basket-toast' in x.value and '장바구니에 담았어요' in x.value
                                    for x in app.markdown))
                app.button(key='save_to_basket').click().run()
                self.assertEqual(len(original_list(path)), 1)
                self.assertTrue(any('basket-toast' in x.value and '이미 장바구니에 담긴 답변' in x.value
                                    for x in app.markdown))
                app.button(key='nav_basket').click().run()
                self.assertIn('가온의 사업은?', [h.value for h in app.subheader])
                self.assertFalse(app.exception)
                app.button(key='basket_remove_ui-test').click().run()
                self.assertEqual(original_list(path), [])
                self.assertTrue(any('아직 담아둔 답변이 없어요' in x.value for x in app.markdown))

    def test_default_baskets_are_isolated_between_browser_sessions(self):
        app_path = Path(__file__).resolve().parents[1] / 'streamlit_app.py'
        result = {'run_id': 'private-answer', 'status': 'answered', 'answer': '개별 답변',
                  'sections': [], 'sources': [], 'trace': {}}
        with patch.dict(os.environ, {'BULSAE_LOCAL_BASKET': '0'}), \
             patch('bulsae.graphrag.streamlit_ui.run_question', return_value=result):
            first = AppTest.from_file(str(app_path)).run()
            first.text_area[0].set_value('첫 사용자 질문')
            first.button(key='submit_question').click().run()
            first.button(key='save_to_basket').click().run()
            first.button(key='nav_basket').click().run()
            self.assertIn('첫 사용자 질문', [h.value for h in first.subheader])

            second = AppTest.from_file(str(app_path)).run()
            second.button(key='nav_basket').click().run()
            self.assertNotIn('첫 사용자 질문', [h.value for h in second.subheader])
            self.assertTrue(any('아직 담아둔 답변이 없어요' in x.value for x in second.markdown))


if __name__ == '__main__':
    unittest.main()
