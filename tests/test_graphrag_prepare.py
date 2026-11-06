import json
import tempfile
import unittest
from pathlib import Path

from bulsae.graphrag.prepare import chunks, prepare


class PrepareTests(unittest.TestCase):
    def test_chunks_keep_exact_offsets_and_cover_text(self):
        text = "가나다라마바사\n아자차카타파하\n" * 5
        result = list(chunks(text, 12, 3))
        self.assertEqual(result[0][0], 0)
        self.assertEqual(result[-1][1], len(text))
        for start, end, chunk in result:
            self.assertEqual(chunk, text[start:end])
        for left, right in zip(result, result[1:]):
            self.assertEqual(right[0], left[1] - 3)

    def test_stable_ids_and_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / "news.jsonl"
            src.write_text(json.dumps({"document_id": "N1", "content": "한글 기사 내용", "original_url": "https://example.com"}, ensure_ascii=False) + "\n")
            a, b = root / "a", root / "b"
            self.assertEqual(prepare(src, a, 5, 2), (1, 2))
            prepare(src, b, 5, 2)
            self.assertEqual(a.read_text(), b.read_text())
            self.assertEqual(json.loads(a.read_text().splitlines()[0])["original_url"], "https://example.com")
            with self.assertRaises(FileExistsError):
                prepare(src, a, 5, 2)

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            list(chunks("text", 3, 3))


if __name__ == "__main__":
    unittest.main()
