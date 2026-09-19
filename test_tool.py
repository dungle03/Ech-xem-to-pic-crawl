import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from io import BytesIO
from PIL import Image as PILImage
from docx import Document

from tool import (
    _add_answer_key_table,
    _set_default_font,
    _add_picture_fitted,
    _add_question_docx,
    _fetch_image_bytes,
    _IMG_CACHE,
    _IMG_HEADERS,
    _SESSION_COOKIES,
    _HARVESTED_LINKS,
    _PROXY,
    set_proxy,
    extract_discussion_info,
    find_discussion_link,
    build_html,
    canonical_exam_code,
    convert_to_docx,
    convert_to_html,
    is_examtopics_discussion_url,
    link_matches_question,
    load_all,
    has_good_data,
    no_link_result,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    normalize_exam_code,
    parse_range,
    save_progress,
    SEARCH_BLOCKED,
    SEARCH_EMPTY,
    SEARCH_ERROR,
    SEARCH_OK,
    sync_browser_session,
    upsert,
    unwrap_search_href,
    as_int,
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


class TestExamCodeNormalization(unittest.TestCase):
    def test_canonical_strips_separators(self):
        self.assertEqual(canonical_exam_code("SK0-005"), "sk0005")
        self.assertEqual(canonical_exam_code("FCSS_NST_SE-7.6"), "fcssnstse76")
        self.assertEqual(canonical_exam_code("H12-711_V4.0"), "h12711v40")

    def test_normalize_preserves_valid_slug_chars(self):
        self.assertEqual(normalize_exam_code("SK0-005"), "sk0-005")
        self.assertEqual(normalize_exam_code("  FCSS_NST_SE-7.6  "), "fcss_nst_se-7.6")
        self.assertEqual(normalize_exam_code("H12-711_V4.0"), "h12-711_v4.0")
        self.assertEqual(normalize_exam_code("az 104"), "az-104")


class TestLinkMatching(unittest.TestCase):
    def test_valid_discussion_slug(self):
        url = "https://www.examtopics.com/discussions/comptia/view/61482-exam-sk0-005-topic-1-question-1-discussion/"
        self.assertTrue(link_matches_question(url, "sk0-005", 1, 1))

    def test_mismatched_qnum(self):
        url = "https://www.examtopics.com/discussions/comptia/view/61482-exam-sk0-005-topic-1-question-10-discussion/"
        self.assertFalse(link_matches_question(url, "sk0-005", 1, 1))

    def test_dotted_code_matching(self):
        url = "https://www.examtopics.com/discussions/huawei/view/12345-exam-h12-711_v40-topic-1-question-2-discussion/"
        self.assertTrue(link_matches_question(url, "H12-711_V4.0", 1, 2))

    def test_non_discussion_url(self):
        self.assertFalse(link_matches_question("https://www.google.com", "sk0-005", 1, 1))
        self.assertFalse(link_matches_question(None, "sk0-005", 1, 1))

    def test_is_examtopics_discussion_url(self):
        self.assertTrue(is_examtopics_discussion_url("https://www.examtopics.com/discussions/view/1/"))
        self.assertFalse(is_examtopics_discussion_url("https://www.examtopics.com/exams/comptia/"))
        self.assertFalse(is_examtopics_discussion_url("https://example.com/discussions/"))


class TestUnwrapHref(unittest.TestCase):
    def test_unwrap_duckduckgo_uddg(self):
        raw = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.examtopics.com%2Fdiscussions%2Ftest"
        urls = unwrap_search_href(raw, "https://duckduckgo.com")
        self.assertTrue(any("examtopics.com/discussions/test" in u for u in urls))

    def test_unwrap_relative_discussions(self):
        urls = unwrap_search_href("/discussions/item", "https://www.examtopics.com")
        self.assertTrue(any(u.startswith("https://www.examtopics.com/discussions/item") for u in urls))


class TestNoLinkResult(unittest.TestCase):
    def test_primary_ok_fallback_blocked_not_aborted(self):
        self.assertEqual(no_link_result(SEARCH_OK, SEARCH_BLOCKED), NO_DISCUSSION_MISSING)
        self.assertEqual(no_link_result(SEARCH_EMPTY, SEARCH_BLOCKED), NO_DISCUSSION_MISSING)

    def test_both_blocked_aborts(self):
        self.assertEqual(no_link_result(SEARCH_BLOCKED, SEARCH_BLOCKED), NO_DISCUSSION_BLOCKED)
        self.assertEqual(no_link_result(SEARCH_BLOCKED, SEARCH_ERROR), NO_DISCUSSION_BLOCKED)

    def test_primary_blocked_fallback_ok_not_aborted(self):
        self.assertEqual(no_link_result(SEARCH_BLOCKED, SEARCH_OK), NO_DISCUSSION_MISSING)


class TestLoadAllDataSafety(unittest.TestCase):
    """load_all KHONG duoc coi file hong la rong roi de save_progress ghi de
    -> mat toan bo du lieu cu. File hong phai duoc cach ly (doi ten) chu khong
    bi xoa.
    """

    def setUp(self):
        import examtopic.parser as P
        self.P = P
        self.tmp = tempfile.mkdtemp()
        self._old_dir = P.OUTPUT_DIR
        P.OUTPUT_DIR = self.tmp

    def tearDown(self):
        self.P.OUTPUT_DIR = self._old_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name="x_questions.json"):
        return os.path.join(self.tmp, name)

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_all(self._path()), [])

    def test_corrupt_file_is_quarantined_not_destroyed(self):
        import glob
        path = self._path()
        good = [{"topic": 1, "question_num": i, "question": f"q{i}"} for i in range(1, 51)]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(good, f)
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw[: len(raw) // 2])  # cat nua -> JSON hong

        data = load_all(path)
        self.assertEqual(data, [])
        # File hong phai duoc giu lai duoi dang .corrupt-*
        quarantined = glob.glob(path + ".corrupt-*")
        self.assertTrue(quarantined, "file hong phai duoc cach ly")
        with open(quarantined[0], encoding="utf-8") as f:
            self.assertGreater(len(f.read()), 0,
                               "noi dung file hong phai con nguyen de cuu")

    def test_non_list_json_is_quarantined(self):
        import glob
        path = self._path()
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"not": "a list"}')
        self.assertEqual(load_all(path), [])
        self.assertTrue(glob.glob(path + ".corrupt-*"))

    def test_save_progress_is_readable_after_write(self):
        path = self._path()
        data = [{"topic": 1, "question_num": 1, "question": "q"}]
        self.assertTrue(save_progress(data, "x_questions.json"))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), data)


class TestUpsertAndOrder(unittest.TestCase):
    def test_upsert_maintains_sorted_order(self):
        data = []
        upsert(data, {"topic": 1, "question_num": 20, "question": "Q20"})
        upsert(data, {"topic": 1, "question_num": 5, "question": "Q5"})
        upsert(data, {"topic": 2, "question_num": 1, "question": "T2Q1"})
        upsert(data, {"topic": 1, "question_num": 1, "question": "Q1"})

        expected = [(1, 1), (1, 5), (1, 20), (2, 1)]
        actual = [(q["topic"], q["question_num"]) for q in data]
        self.assertEqual(actual, expected)

    def test_upsert_overwrites_existing(self):
        data = [{"topic": 1, "question_num": 5, "question": "Old Q5"}]
        upsert(data, {"topic": 1, "question_num": 5, "question": "New Q5"})
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["question"], "New Q5")


class TestNegativeImageCache(unittest.TestCase):
    def test_failed_image_sets_negative_cache(self):
        url = "https://invalid-non-existent-domain-test.com/fake.png"
        _IMG_CACHE.clear()
        with patch("examtopic.config.httpx.get", side_effect=Exception("Network failure")) as mock_get:
            res = _fetch_image_bytes(url)
            self.assertIsNone(res)
            self.assertIn(url, _IMG_CACHE)
            self.assertIsNone(_IMG_CACHE[url])
            self.assertEqual(mock_get.call_count, 1)

            with patch("examtopic.config.httpx.get") as mock_get2:
                res2 = _fetch_image_bytes(url)
                self.assertIsNone(res2)
                mock_get2.assert_not_called()


class TestBuildHtml(unittest.TestCase):
    def test_no_double_escaping_in_payload(self):
        questions = [
            {
                "exam_code": "test",
                "topic": 1,
                "question_num": 1,
                "question": "What is & why?",
                "question_images": ["https://img.test.com/q.png?a=1&b=2"],
                "options": [
                    {"letter": "A", "text": "Opt & text", "images": [], "is_correct": True}
                ],
                "suggested_answers": ["A"],
                "answers": []
            }
        ]
        html_out = build_html(questions, "test", embed_images=False)
        self.assertNotIn("&amp;amp;", html_out)
        self.assertIn("https://img.test.com/q.png?a=1&b=2", html_out)

    def test_multi_topic_labels(self):
        questions = [
            {"topic": 1, "question_num": 1, "question": "T1Q1", "options": [], "suggested_answers": []},
            {"topic": 2, "question_num": 1, "question": "T2Q1", "options": [], "suggested_answers": []}
        ]
        html_out = build_html(questions, "test", embed_images=False)
        self.assertIn("Topic 1", html_out)
        self.assertIn("Topic 2", html_out)
        self.assertIn("T1 #1", html_out)
        self.assertIn("T2 #1", html_out)


class TestDocxImageFitted(unittest.TestCase):
    def test_add_picture_fitted(self):
        doc = Document()
        im = PILImage.new("RGB", (50, 50), color="blue")
        buf = BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)

        success = _add_picture_fitted(doc, buf, max_width_inches=5.5)
        self.assertTrue(success)


class TestAnswerKeyTable(unittest.TestCase):
    def test_answer_key_creates_compact_table(self):
        doc = Document()
        questions = [
            {"topic": 1, "question_num": 1, "question": "Q1", "suggested_answers": ["A"]},
            {"topic": 1, "question_num": 2, "question": "Q2", "suggested_answers": ["B", "C"]},
            {"topic": 1, "question_num": 3, "question": "Q3", "suggested_answers": ["D"]},
            {"topic": 1, "question_num": 4, "question": "Q4", "suggested_answers": []},
            {"topic": 1, "question_num": 5, "question": "Q5", "community_most_voted": ["C"]},
        ]
        _add_answer_key_table(doc, questions)
        self.assertEqual(len(doc.tables), 1)
        table = doc.tables[0]
        self.assertEqual(len(table.columns), 8)
        self.assertEqual(table.rows[0].cells[0].text, "Câu")
        self.assertEqual(table.rows[0].cells[1].text, "ĐA")


class TestBrowserSessionSync(unittest.TestCase):
    def test_sync_browser_session_updates_headers_and_cookies(self):
        mock_page = MagicMock()
        mock_page.evaluate.return_value = "Mozilla/5.0 (Custom macOS UA) TestAgent/1.0"
        mock_page.context.cookies.return_value = [
            {"name": "cf_clearance", "value": "test_cf_token"},
            {"name": "session_id", "value": "123456"}
        ]
        sync_browser_session(mock_page)
        self.assertEqual(_IMG_HEADERS["User-Agent"], "Mozilla/5.0 (Custom macOS UA) TestAgent/1.0")
        self.assertEqual(_SESSION_COOKIES.get("cf_clearance"), "test_cf_token")
        self.assertEqual(_SESSION_COOKIES.get("session_id"), "123456")


class TestCommunityMostVotedDisplay(unittest.TestCase):
    def test_html_displays_most_voted_chip_when_different(self):
        questions = [
            {
                "topic": 1,
                "question_num": 1,
                "question": "What is x?",
                "options": [],
                "suggested_answers": ["A"],
                "community_most_voted": ["B"]
            }
        ]
        html_out = build_html(questions, "test", embed_images=False)
        self.assertIn("Most Voted: B", html_out)

    def test_docx_displays_community_voted_when_different(self):
        doc = Document()
        q = {
            "topic": 1,
            "question_num": 1,
            "question": "What is x?",
            "options": [],
            "suggested_answers": ["A"],
            "community_most_voted": ["B"]
        }
        _add_question_docx(doc, q, 1)
        full_text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Cộng đồng: B", full_text)




class TestDiscussionInfoExtraction(unittest.TestCase):
    def test_extract_discussion_info_valid(self):
        url = "https://www.examtopics.com/discussions/comptia/view/71586-exam-sk0-005-topic-1-question-3-discussion/"
        info = extract_discussion_info(url)
        self.assertEqual(info, ("sk0005", 1, 3))

    def test_extract_discussion_info_dotted(self):
        url = "https://www.examtopics.com/discussions/huawei/view/12345-exam-h12-711_v40-topic-2-question-15-discussion/"
        info = extract_discussion_info(url)
        self.assertEqual(info, ("h12711v40", 2, 15))

    def test_extract_discussion_info_invalid(self):
        self.assertIsNone(extract_discussion_info("https://example.com"))
        self.assertIsNone(extract_discussion_info("https://www.examtopics.com/exams/comptia/"))


class TestHarvestedLinksCache(unittest.TestCase):
    def test_harvested_links_skips_search(self):
        _HARVESTED_LINKS.clear()
        key = ("sk0005", 1, 99)
        test_url = "https://www.examtopics.com/discussions/comptia/view/99999-exam-sk0-005-topic-1-question-99-discussion/"
        _HARVESTED_LINKS[key] = test_url

        mock_page = MagicMock()
        result = find_discussion_link(mock_page, "sk0-005", 1, 99)
        self.assertEqual(result, test_url)
        mock_page.goto.assert_not_called()


class TestProxyConfiguration(unittest.TestCase):
    def test_set_proxy(self):
        set_proxy("http://127.0.0.1:8888")
        from tool import _PROXY
        # Check through getter or import
        from examtopic.config import _PROXY as conf_proxy
        self.assertEqual(conf_proxy, "http://127.0.0.1:8888")
        set_proxy(None)


class TestScriptTagPreservation(unittest.TestCase):
    """_RE_SCRIPT phai GIU lai <script type="application/json"> (nguon du lieu
    community_most_voted) va STRIP cac script khac. Bien the co khoang trang
    quanh dau '=' tung bi xoa am tham -> mat du lieu vote ma khong bao loi.
    """

    def setUp(self):
        from examtopic.config import _RE_SCRIPT
        self.strip = _RE_SCRIPT.sub

    def _kept(self, html):
        return bool(self.strip('', html).strip())

    def test_keeps_canonical_json_script(self):
        self.assertTrue(self._kept('<script type="application/json">[1]</script>'))

    def test_keeps_json_script_with_space_around_equals(self):
        for html in (
            '<script type = "application/json">[1]</script>',
            '<script type= "application/json">[1]</script>',
            '<script type ="application/json" id="x">[1]</script>',
            "<script type = 'application/json'>[1]</script>",
        ):
            self.assertTrue(self._kept(html), f"bi strip nham: {html}")

    def test_keeps_real_examtopics_tally_markup(self):
        html = ('<div class="voted-answers-tally d-none">'
                '<script id="806123" type="application/json">'
                '[{"voted_answers": "D", "vote_count": 12, "is_most_voted": true}]'
                '</script></div>')
        out = self.strip('', html)
        self.assertIn("voted_answers", out)
        self.assertIn("is_most_voted", out)

    def test_strips_ordinary_scripts(self):
        for html in (
            '<script type="text/javascript">var x=1;</script>',
            '<script>var y=2;</script>',
            '<script src="https://ads.example/a.js"></script>',
        ):
            self.assertFalse(self._kept(html), f"khong strip: {html}")


class TestAsInt(unittest.TestCase):
    def test_int_passthrough(self):
        self.assertEqual(as_int(5), 5)
        self.assertEqual(as_int("7"), 7)

    def test_invalid_returns_default(self):
        self.assertEqual(as_int(None), 0)
        self.assertEqual(as_int("abc"), 0)
        self.assertEqual(as_int("abc", default=1), 1)
        self.assertEqual(as_int("", default=9), 9)


class TestUpsertRobustKeys(unittest.TestCase):
    def test_upsert_does_not_crash_on_garbage_topic(self):
        data = [{"topic": "abc", "question_num": 1, "question": "x"}]
        upsert(data, {"topic": 1, "question_num": 2, "question": "y"})
        self.assertEqual(len(data), 2)

    def test_upsert_matches_str_and_int_keys(self):
        data = [{"topic": "1", "question_num": "5", "question": "old"}]
        upsert(data, {"topic": 1, "question_num": 5, "question": "new"})
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["question"], "new")


class TestHttpRetryBackoff(unittest.TestCase):
    def test_retries_on_429_then_succeeds(self):
        from examtopic.crawler import load_discussion_via_http
        responses = [
            MagicMock(status_code=429, text="rate limited"),
            MagicMock(status_code=200, text="<div class='discussion-header-container'></div>"),
        ]
        tab = MagicMock()
        tab.query_selector.return_value = MagicMock()
        with patch("examtopic.crawler.httpx.get", side_effect=responses) as mock_get, \
             patch("examtopic.crawler.time.sleep") as mock_sleep:
            ok = load_discussion_via_http(tab, "https://x.test")
        self.assertTrue(ok)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    def test_gives_up_after_exhausting_retries(self):
        from examtopic.crawler import load_discussion_via_http
        responses = [MagicMock(status_code=503, text="")] * 3
        tab = MagicMock()
        with patch("examtopic.crawler.httpx.get", side_effect=responses), \
             patch("examtopic.crawler.time.sleep"):
            ok = load_discussion_via_http(tab, "https://x.test")
        self.assertFalse(ok)

    def test_non_retryable_status_fails_immediately(self):
        from examtopic.crawler import load_discussion_via_http
        tab = MagicMock()
        with patch("examtopic.crawler.httpx.get",
                   return_value=MagicMock(status_code=404, text="nope")) as mock_get, \
             patch("examtopic.crawler.time.sleep") as mock_sleep:
            ok = load_discussion_via_http(tab, "https://x.test")
        self.assertFalse(ok)
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()


class TestHasGoodData(unittest.TestCase):
    def test_detects_good_record(self):
        data = [{"topic": 1, "question_num": 5, "question": "real"}]
        self.assertTrue(has_good_data(data, 1, 5))

    def test_ignores_record_without_question(self):
        data = [{"topic": 1, "question_num": 5, "question": ""}]
        self.assertFalse(has_good_data(data, 1, 5))

    def test_matches_string_keys(self):
        data = [{"topic": "2", "question_num": "7", "question": "real"}]
        self.assertTrue(has_good_data(data, 2, 7))

    def test_absent_question(self):
        data = [{"topic": 1, "question_num": 5, "question": "real"}]
        self.assertFalse(has_good_data(data, 1, 6))


class TestConvertMalformedData(unittest.TestCase):
    """Converter khong duoc crash khi du lieu di dang (question_num/topic khong
    phai so) -- truoc day dung int() tran gay ValueError lam hong ca buoc convert.
    """

    def _write(self, data):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "x_questions.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def test_non_numeric_question_num_does_not_crash(self):
        path = self._write([{
            "exam_code": "X", "topic": "1", "question_num": "abc",
            "question": "q", "options": [], "suggested_answers": [], "answers": [],
        }])
        convert_to_html(path)
        convert_to_docx(path)

    def test_none_topic_and_num_do_not_crash(self):
        path = self._write([{
            "exam_code": "X", "topic": None, "question_num": None,
            "question": "q", "options": [], "suggested_answers": [], "answers": [],
        }])
        convert_to_html(path)
        convert_to_docx(path)


class TestDocxFormatting(unittest.TestCase):
    def _one_question(self):
        return [{
            "exam_code": "TEST-1",
            "topic": 1,
            "question_num": 1,
            "question": "What is x?",
            "options": [
                {"letter": "A", "text": "alpha", "images": [], "is_correct": True},
                {"letter": "B", "text": "beta", "images": [], "is_correct": False},
            ],
            "suggested_answers": ["A"],
            "question_images": [],
        }]

    def _full_text(self, doc):
        parts = [p.text for p in doc.paragraphs]
        for t in doc.tables:
            for row in t.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        for s in doc.sections:
            for p in list(s.header.paragraphs) + list(s.footer.paragraphs):
                parts.append(p.text)
        return "\n".join(parts)

    def test_hide_answers_omits_answer_line(self):
        doc = Document()
        _add_question_docx(doc, self._one_question()[0], 1, hide_answers=True)
        self.assertNotIn("Đáp án:", self._full_text(doc))

    def test_shows_answer_line_by_default(self):
        doc = Document()
        _add_question_docx(doc, self._one_question()[0], 1)
        self.assertIn("Đáp án: A", self._full_text(doc))

    def test_default_font_is_set(self):
        doc = Document()
        _set_default_font(doc)
        # Ap dung cho ca style Heading, khong chi Normal.
        for style_name in ("Normal", "Heading 1", "Heading 2"):
            self.assertEqual(
                doc.styles[style_name].font.name, "Calibri",
                f"style {style_name} phai dung font Calibri",
            )

    def test_convert_adds_header_and_footer(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "t_questions.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._one_question(), f)
        out = convert_to_docx(path, hide_answers=True)
        doc = Document(out)
        section = doc.sections[0]
        header_text = "\n".join(p.text for p in section.header.paragraphs)
        footer_text = "\n".join(p.text for p in section.footer.paragraphs)
        self.assertIn("TEST-1", header_text)
        self.assertIn("Trang", footer_text)
        shutil.rmtree(tmp)

    def test_answer_key_table_keeps_answers_when_hidden(self):
        doc = Document()
        _add_answer_key_table(doc, self._one_question())
        table = doc.tables[0]
        cell_texts = [c.text for row in table.rows for c in row.cells]
        self.assertIn("A", cell_texts)


if __name__ == "__main__":

    unittest.main()
