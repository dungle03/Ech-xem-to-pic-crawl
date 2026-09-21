"""Facade tai-export toan bo API cua goi `examtopic`.

Cac import duoi day co chu dich KHONG duoc dung trong chinh file nay: chung
ton tai de `from examtopic import X` van hoat dong nhu truoc (backward-compat
voi tool.py va bat ky script nguoi dung nao). `__all__` duoi cuoi file khai
bao tuong minh danh sach re-export nay, nen day khong phai import thua.
"""
from .config import (
    LOG,
    configure_logging,
    MIN_DELAY,
    MAX_DELAY,
    RETRY_LIMIT,
    BLOCKED_ABORT_STREAK,
    OUTPUT_DIR,
    DEFAULT_OP_TIMEOUT,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    SEARCH_OK,
    SEARCH_EMPTY,
    SEARCH_BLOCKED,
    SEARCH_ERROR,
    _IMG_HEADERS,
    _IMG_CACHE,
    _SESSION_COOKIES,
    _HARVESTED_LINKS,
    _PROXY,
    set_proxy,
    _fetch_image_bytes,
    _fetch_image,
    _preload_images,
)
from .parser import (
    escape_html,
    as_int,
    record_topic,
    canonical_exam_code,
    normalize_exam_code,
    extract_discussion_info,
    link_matches_question,
    is_examtopics_discussion_url,
    unwrap_search_href,
    extract_matching_link,
    no_link_result,
    parse_range,
    load_all,
    has_good_data,
    upsert,
    save_progress,
)
from .crawler import (
    safe_close,
    safe_goto,
    warmup_search,
    search_engine,
    find_discussion_link,
    close_extra_tabs,
    wait_for_discussion,
    load_discussion_via_http,
    sync_browser_session,
    crawl_one_question,
)
from .exporters import (
    build_html,
    convert_to_html,
    convert_to_docx,
    _add_picture_fitted,
    _add_question_docx,
    _add_answer_key_table,
    _set_default_font,
)

# Khai bao tuong minh danh sach re-export. Day la ly do cac import tren khong
# bi coi la "unused": chung la API cong khai cua goi.
__all__ = [
    "__version__",
    # config
    "LOG", "configure_logging",
    "MIN_DELAY", "MAX_DELAY", "RETRY_LIMIT", "BLOCKED_ABORT_STREAK",
    "OUTPUT_DIR", "DEFAULT_OP_TIMEOUT",
    "NO_DISCUSSION_BLOCKED", "NO_DISCUSSION_MISSING",
    "SEARCH_OK", "SEARCH_EMPTY", "SEARCH_BLOCKED", "SEARCH_ERROR",
    "_IMG_HEADERS", "_IMG_CACHE", "_SESSION_COOKIES", "_HARVESTED_LINKS", "_PROXY",
    "set_proxy", "_fetch_image_bytes", "_fetch_image", "_preload_images",
    # parser
    "escape_html", "as_int", "record_topic", "canonical_exam_code", "normalize_exam_code",
    "extract_discussion_info", "link_matches_question", "is_examtopics_discussion_url",
    "unwrap_search_href", "extract_matching_link", "no_link_result",
    "parse_range", "load_all", "has_good_data", "upsert", "save_progress",
    # crawler
    "safe_close", "safe_goto", "warmup_search", "search_engine",
    "find_discussion_link", "close_extra_tabs", "wait_for_discussion",
    "load_discussion_via_http", "sync_browser_session", "crawl_one_question",
    # exporters
    "build_html", "convert_to_html", "convert_to_docx",
    "_add_picture_fitted", "_add_question_docx", "_add_answer_key_table", "_set_default_font",
]

__version__ = "1.1.0"
