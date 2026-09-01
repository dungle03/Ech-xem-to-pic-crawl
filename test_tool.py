import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from io import BytesIO

from PIL import Image as PILImage

from tool import (
    _fetch_image,
    _fetch_image_bytes,
    _preload_images,
    _IMG_CACHE,
    build_html,
    canonical_exam_code,
    link_matches_question,
    load_all,
    no_link_result,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    normalize_exam_code,
    parse_range,
    save_progress,
    SEARCH_BLOCKED,
    SEARCH_EMPTY,
    SEARCH_OK,
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

    def test_none_input(self):
        self.assertEqual(normalize_exam_code(None), "")

    def test_empty_input(self):
        self.assertEqual(normalize_exam_code(""), "")


class TestCanonicalExamCode(unittest.TestCase):
    def test_strips_separators(self):
        self.assertEqual(canonical_exam_code("SK0-005"), "sk0005")

    def test_fcss(self):
        self.assertEqual(canonical_exam_code("FCSS_NST_SE-7.6"), "fcssnstse76")

    def test_none_input(self):
        self.assertEqual(canonical_exam_code(None), "")


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

    def test_invalid_record(self):
        upsert(self.data, None)
        upsert(self.data, "not-a-dict")
        self.assertEqual(len(self.data), 2)


class TestUnwrapSearchHref(unittest.TestCase):
    def test_direct_link(self):
        url = "https://www.examtopics.com/discussions/a/view/1-exam-sk0-005-topic-1-question-1-discussion/"
        result = unwrap_search_href(url, "")
        self.assertIn(url, result)

    def test_ddg_redirect(self):
        raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.examtopics.com%2Fdiscussions%2Fa%2Fview%2F1-exam-sk0-005-topic-1-question-1-discussion%2F"
        result = unwrap_search_href(raw, "https://duckduckgo.com")
        self.assertTrue(any("examtopics.com" in u for u in result))


class TestNoLinkResult(unittest.TestCase):
    def test_google_blocked(self):
        self.assertIs(no_link_result(SEARCH_OK, SEARCH_BLOCKED), NO_DISCUSSION_BLOCKED)

    def test_really_missing(self):
        self.assertIs(no_link_result(SEARCH_OK, SEARCH_EMPTY), NO_DISCUSSION_MISSING)
        self.assertIs(no_link_result(SEARCH_EMPTY, SEARCH_EMPTY), NO_DISCUSSION_MISSING)


class TestImageCache(unittest.TestCase):
    def setUp(self):
        _IMG_CACHE.clear()

    def test_fetch_image_returns_fresh_stream(self):
        img = PILImage.new("RGB", (10, 10), color="blue")
        buf = BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        _IMG_CACHE["https://img.test/sample.png"] = raw

        stream1 = _fetch_image("https://img.test/sample.png")
        self.assertIsNotNone(stream1)
        self.assertEqual(stream1.tell(), 0)
        data1 = stream1.read()
        self.assertEqual(len(data1), len(raw))
        self.assertEqual(stream1.tell(), len(raw))

        # Subsequent call must return a new stream at position 0
        stream2 = _fetch_image("https://img.test/sample.png")
        self.assertIsNotNone(stream2)
        self.assertEqual(stream2.tell(), 0)
        data2 = stream2.read()
        self.assertEqual(len(data2), len(raw))

    def test_preload_images_handles_none_fields(self):
        # Must not raise exceptions with None or malformed values
        questions = [
            {
                "question": "Q1",
                "question_images": None,
                "options": None,
            },
            {
                "question": "Q2",
                "question_images": ["https://img.test/pic.png"],
                "options": [{"letter": "A", "images": None}, "not-a-dict"],
            },
        ]
        _IMG_CACHE["https://img.test/pic.png"] = b"cached"
        _preload_images(questions)
        self.assertIn("https://img.test/pic.png", _IMG_CACHE)


class TestStorageAndAtomicSave(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_progress_atomic(self):
        with patch("tool.OUTPUT_DIR", self.temp_dir):
            data = [{"topic": 1, "question_num": 1, "question": "Test question"}]
            success = save_progress(data, "test_out.json")
            self.assertTrue(success)

            loaded = load_all(os.path.join(self.temp_dir, "test_out.json"))
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["question"], "Test question")

    def test_load_all_invalid_files(self):
        # Non-existent
        self.assertEqual(load_all(os.path.join(self.temp_dir, "nonexistent.json")), [])

        # Invalid JSON
        bad_json_path = os.path.join(self.temp_dir, "bad.json")
        with open(bad_json_path, "w") as f:
            f.write("{invalid json...")
        self.assertEqual(load_all(bad_json_path), [])

        # Non-list JSON
        dict_json_path = os.path.join(self.temp_dir, "dict.json")
        with open(dict_json_path, "w") as f:
            f.write('{"key": "value"}')
        self.assertEqual(load_all(dict_json_path), [])


class TestBuildHtml(unittest.TestCase):
    def test_build_html_with_none_fields(self):
        questions = [
            {
                "exam_code": "test-exam",
                "topic": 1,
                "question_num": 1,
                "question": "What is <script>alert(1)</script>?",
                "question_images": None,
                "options": None,
                "suggested_answers": None,
                "answers": None,
            },
            {
                "exam_code": "test-exam",
                "topic": 1,
                "question_num": 2,
                "question": "Normal question",
                "question_images": ["https://img.test/q2.png"],
                "options": [
                    {"letter": "A", "text": "Option A", "images": None, "is_correct": True},
                    {"letter": "B", "text": "Option B", "images": ["https://img.test/b.png"], "is_correct": False},
                ],
                "suggested_answers": ["A"],
                "answers": ["Comment 1"],
            },
        ]
        html_str = build_html(questions, "test-exam")
        self.assertIn("<!DOCTYPE html>", html_str)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_str)
        self.assertIn("Option A", html_str)


if __name__ == "__main__":
    unittest.main()


class TestParseArgs(unittest.TestCase):
    def test_parse_args_defaults(self):
        with patch("sys.argv", ["tool.py"]):
            from tool import parse_args
            args = parse_args()
            self.assertIsNone(args.exam)
            self.assertIsNone(args.topic)
            self.assertIsNone(args.range)
            self.assertFalse(args.yes)
            self.assertIsNone(args.convert_only)

    def test_parse_args_custom(self):
        with patch("sys.argv", ["tool.py", "-e", "az-104", "-t", "2", "-r", "1-20", "-y"]):
            from tool import parse_args
            args = parse_args()
            self.assertEqual(args.exam, "az-104")
            self.assertEqual(args.topic, 2)
            self.assertEqual(args.range, "1-20")
            self.assertTrue(args.yes)
