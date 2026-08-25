import unittest
from unittest.mock import MagicMock

from tool import (
    canonical_exam_code,
    link_matches_question,
    normalize_exam_code,
    parse_range,
    upsert,
    unwrap_search_href,
)


class TestParseRange(unittest.TestCase):
    def test_range(self):
        self.assertEqual(parse_range("1-10"), (1, 10))

    def test_single(self):
        self.assertEqual(parse_range("5"), (5, 5))

    def test_invalid_text(self):
        self.assertIsNone(parse_range("abc"))

    def test_empty(self):
        self.assertIsNone(parse_range(""))

    def test_reversed(self):
        self.assertEqual(parse_range("10-1"), (10, 1))


class TestNormalizeExamCode(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(normalize_exam_code("SK0-005"), "sk0-005")

    def test_underscore_dot(self):
        self.assertEqual(normalize_exam_code("FCSS_NST_SE-7.6"), "fcss_nst_se-7.6")

    def test_spaces_to_dash(self):
        self.assertEqual(normalize_exam_code("H12 711 V4.0"), "h12-711-v4.0")

    def test_strip_special(self):
        self.assertEqual(normalize_exam_code("  EX-200!@# "), "ex-200")


class TestCanonicalExamCode(unittest.TestCase):
    def test_strips_separators(self):
        self.assertEqual(canonical_exam_code("SK0-005"), "sk0005")

    def test_fcss(self):
        self.assertEqual(canonical_exam_code("FCSS_NST_SE-7.6"), "fcssnstse76")


class TestLinkMatchesQuestion(unittest.TestCase):
    url = "https://www.examtopics.com/discussions/some/view/61482-exam-sk0-005-topic-1-question-57-discussion/"

    def test_match_exact(self):
        self.assertTrue(link_matches_question(self.url, "sk0-005", 1, 57))

    def test_match_dotted_variant(self):
        url = "https://www.examtopics.com/discussions/x/view/99-exam-h12-711-v40-topic-2-question-10-discussion/"
        self.assertTrue(link_matches_question(url, "h12-711_v4.0", 2, 10))

    def test_wrong_question(self):
        self.assertFalse(link_matches_question(self.url, "sk0-005", 1, 58))

    def test_not_discussion_url(self):
        self.assertFalse(link_matches_question("https://example.com/page", "sk0-005", 1, 57))

    def test_empty_href(self):
        self.assertFalse(link_matches_question("", "sk0-005", 1, 57))


class TestUpsert(unittest.TestCase):
    def setUp(self):
        self.data = [
            {"topic": 1, "question_num": 1, "question": "Q1"},
            {"topic": 1, "question_num": 2, "question": "Q2"},
        ]

    def test_insert_new(self):
        upsert(self.data, {"topic": 1, "question_num": 3, "question": "Q3"})
        self.assertEqual(len(self.data), 3)

    def test_update_existing(self):
        upsert(self.data, {"topic": 1, "question_num": 2, "question": "Updated"})
        self.assertEqual(len(self.data), 2)
        self.assertEqual(self.data[1]["question"], "Updated")


class TestUnwrapSearchHref(unittest.TestCase):
    def test_direct_link(self):
        url = "https://www.examtopics.com/discussions/a/view/1-exam-sk0-005-topic-1-question-1-discussion/"
        result = unwrap_search_href(url, "")
        self.assertIn(url, result)

    def test_ddg_redirect(self):
        raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.examtopics.com%2Fdiscussions%2Fa%2Fview%2F1-exam-sk0-005-topic-1-question-1-discussion%2F"
        result = unwrap_search_href(raw, "https://duckduckgo.com")
        self.assertTrue(any("examtopics.com" in u for u in result))


if __name__ == "__main__":
    unittest.main()
