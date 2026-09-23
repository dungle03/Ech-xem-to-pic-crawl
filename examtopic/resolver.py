"""Giai URL discussion bang duong TAT DINH, khong dung search engine.

Vi sao can: search engine hay tu dong SUA ma de (ccaak -> ccsk) nen co nhung cau
ton tai that ma search khong bao gio tra ve link dung. Do tren ccaak: cau 108,
98, 85, 57, 86 deu co trang that nhung bi bao "khong co discussion".

Chuoi tat dinh (da kiem chung tren du lieu that):

 1. `/exams/<bat-ky>/<code>/view/1/` tra ve 10 question_id dau tien. Phan
    `<bat-ky>` la COSMETIC -- dien gi cung duoc, nen khong can biet category.
 2. `/ajax/discussion/exam-question/<question_id>` tra ve
    `data-discussion-id` + `data-title` ("Exam CCAAK topic 1 question 108
    discussion") -> vua lay duoc URL, vua VERIFY duoc dung de/topic/cau.
 3. question_id xep thanh KHOI LIEN MACH theo (topic, qnum) trong cung 1 de:
    ccaak q1..q54 -> 949311..949364 ; q55..q109 -> 977877..977931.
    Nen chi can 1 anchor moi khoi la noi suy duoc ca khoi.

Nho do: cau thuoc khoi da co anchor duoc giai hoan toan khong can search, va moi
ket qua deu duoc VERIFY bang title truoc khi dung -- doan sai bi loai bo, khong
bao gio tra ve link cua cau khac.
"""
import json
import os
import re
import time

import httpx

from . import config
from .config import (
    LOG,
    OUTPUT_DIR,
    RETRY_HTTP_ATTEMPTS,
    RETRY_HTTP_BACKOFF,
    _IMG_HEADERS,
    _SESSION_COOKIES,
)
from .parser import canonical_exam_code, normalize_exam_code

AJAX_QUESTION_URL = "https://www.examtopics.com/ajax/discussion/exam-question/"
EXAM_VIEW_URL = "https://www.examtopics.com/exams/{slug}/{slug}/view/1/"

# So lan thu toi da cho MOI cau. Moi lan la 1 request AJAX (~1.2s). Sau khi giai
# duoc 1 cau, anchor duoc ghi lai nen cac cau sau trong cung khoi chi ton 1 lan.
MAX_ANCHOR_TRIES = 3


def exam_slug_variants(exam_code):
    """Cac dang slug co the dung cho URL trang exam, theo thu tu thu.

    Ma de co dau cham dung slug KHAC voi ma hien thi: `H12-711_V4.0` duoc site
    viet thanh `h12-711-v4-0` (thay `_` va `.` bang `-`), chu khong phai
    `h12-711_v4.0`. Do tren du lieu that: `h12-711_v4.0` -> 404, con
    `h12-711-v4-0` -> 200. Vi khong doan chac dang nao dung cho moi ma de, ta
    thu lan luot vai bien the pho bien nhat.
    """
    raw = str(exam_code or "").strip().lower()
    norm = normalize_exam_code(exam_code)
    canonical = canonical_exam_code(exam_code)
    variants = []
    for cand in (
        re.sub(r'[_.]', '-', norm),   # h12-711-v4-0  (dang site dung)
        re.sub(r'[_.]', '', norm),    # h12-711v40
        norm,                          # h12-711_v4.0  (dang cu)
        canonical,                     # h12711v40
        re.sub(r'[^a-z0-9]+', '-', raw).strip('-'),  # h12-711-v4-0 tu ban goc
    ):
        cand = re.sub(r'-+', '-', cand).strip('-')
        if cand and cand not in variants:
            variants.append(cand)
    return variants

_RE_CARD = re.compile(
    r'Question\s*#(?P<qnum>\d+)\s*.*?Topic\s*(?P<topic>\d+)\s*.*?'
    r'question-body[^>]*data-id="(?P<qid>\d+)"',
    re.S,
)
# `question-body` co the co them class khac truoc `data-id`
# (vd `class="question-body mt-3 pt-3 border-top" data-id="977931"`) nen phai la
# `[^>]*` chu khong phai `"` ngay sau ten class.
_RE_QUESTION_ID = re.compile(r'question-body[^>]*data-id="(\d+)"')
_RE_AJAX_DID = re.compile(r'data-discussion-id="(\d+)"')
_RE_AJAX_TITLE = re.compile(r'data-title="([^"]*)"')
# Category that (vendor) nam trong link checkout: /checkout/confluent/ccaak/month
_RE_CATEGORY = re.compile(r'/checkout/([a-z0-9_-]+)/', re.I)
_RE_TITLE_PARTS = re.compile(
    r'^Exam\s+(?P<code>.+?)\s+topic\s+(?P<topic>\d+)\s+'
    r'question\s+(?P<qnum>\d+)\s+discussion$',
    re.I,
)

# exam_code -> {(topic, qnum): question_id}. Ghi ra dia de lan chay sau khong
# phai do lai; day la thu giup cac lan crawl sau giai duoc ca khi search chet.
ANCHORS = {}
# exam_code -> vendor/category that (vd ccaak -> confluent), chi de URL gon.
CATEGORY = {}
_SEED_ATTEMPTED = set()


def _anchor_path():
    return os.path.join(OUTPUT_DIR, ".anchors.json")


_DIRTY = False


def clear_anchors():
    """Xoa cache anchor trong bo nho (dung cho test)."""
    global _DIRTY
    ANCHORS.clear()
    _SEED_ATTEMPTED.clear()
    _DIRTY = False


def load_anchors():
    """Nap anchor tu dia vao bo nho (idempotent)."""
    if ANCHORS:
        return ANCHORS
    try:
        with open(_anchor_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ANCHORS
    if not isinstance(data, dict):
        return ANCHORS
    for code, bucket in data.items():
        if not isinstance(bucket, dict):
            continue
        parsed = {}
        for key, qid in bucket.items():
            try:
                topic, qnum = (int(x) for x in str(key).split("-", 1))
                parsed[(topic, qnum)] = int(qid)
            except (TypeError, ValueError):
                continue
        if parsed:
            ANCHORS[str(code)] = parsed
    return ANCHORS


def save_anchors():
    """Ghi anchor xuong dia theo kieu atomic (khong de lai file hong)."""
    global _DIRTY
    if not _DIRTY:
        return
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = _anchor_path()
        tmp = path + ".tmp"
        payload = {code: {f"{t}-{q}": qid for (t, q), qid in bucket.items()}
                   for code, bucket in ANCHORS.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
        _DIRTY = False
    except OSError as e:
        LOG.warning(f"  Khong ghi duoc cache anchor: {e}")


def record_anchor(exam_code, topic, qnum, question_id, flush=True):
    """Ghi nho (topic, qnum) -> question_id. Tra ve True neu la anchor moi."""
    global _DIRTY
    code = canonical_exam_code(exam_code)
    try:
        key = (int(topic), int(qnum))
        qid = int(question_id)
    except (TypeError, ValueError):
        return False
    if not code or qid <= 0:
        return False
    load_anchors()
    bucket = ANCHORS.setdefault(code, {})
    if bucket.get(key) == qid:
        return False
    bucket[key] = qid
    _DIRTY = True
    if flush:
        save_anchors()
    return True


def _http_get(url, timeout=20):
    """GET voi UA/cookie/proxy cua phien hien tai. Tra ve text hoac None."""
    ua = _IMG_HEADERS.get("User-Agent") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    # Doc `config._PROXY` tai thoi diem goi (khong import truc tiep) de proxy set
    # sau khi import van duoc ap dung.
    proxy = config._PROXY
    for attempt in range(RETRY_HTTP_ATTEMPTS + 1):
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": ua},
                cookies=_SESSION_COOKIES or None,
                proxy=proxy,
                timeout=timeout,
                follow_redirects=True,
            )
        except Exception:
            return None
        if resp.status_code == 200 and resp.text:
            return resp.text
        if resp.status_code in (429, 503) and attempt < RETRY_HTTP_ATTEMPTS:
            time.sleep(RETRY_HTTP_BACKOFF * (2 ** attempt))
            continue
        return None
    return None


def ajax_lookup(question_id):
    """Tra ve (discussion_id, title) cho question_id, hoac None."""
    html = _http_get(AJAX_QUESTION_URL + str(question_id), timeout=15)
    if not html:
        return None
    did = _RE_AJAX_DID.search(html)
    title = _RE_AJAX_TITLE.search(html)
    if not did or not title:
        return None
    return did.group(1), title.group(1)


def parse_title(title):
    """Tach title -> (canonical_code, topic, qnum), hoac None."""
    m = _RE_TITLE_PARTS.match((title or "").strip())
    if not m:
        return None
    try:
        return (canonical_exam_code(m.group("code")),
                int(m.group("topic")),
                int(m.group("qnum")))
    except (TypeError, ValueError):
        return None


def seed_from_exam_page(exam_code):
    """Nap anchor tu 10 cau dau cua trang exam. Tra ve so anchor moi.

    Phan category trong URL la cosmetic nen dien chinh ma de cung duoc; nho vay
    khong can biet vendor/category truoc. Category that (neu tim thay) duoc ghi
    nho de dung cho URL discussion cho gon.

    Phai thu NHIEU bien the slug: ma de co dau cham duoc site viet khac di
    (`H12-711_V4.0` -> `h12-711-v4-0`). Xem `exam_slug_variants`.
    """
    code = canonical_exam_code(exam_code)
    variants = exam_slug_variants(exam_code)
    if not code or not variants:
        return 0
    _SEED_ATTEMPTED.add(code)

    html = None
    for slug in variants:
        html = _http_get(EXAM_VIEW_URL.format(slug=slug))
        if html and _RE_CARD.search(html):
            break
        html = None
    if not html:
        LOG.info("  [Tat dinh] Khong nap duoc anchor tu trang exam "
                 "(trang trong/khong co cau nao) - se dung search.")
        return 0

    cat = _RE_CATEGORY.search(html)
    if cat:
        CATEGORY[code] = cat.group(1).lower()
    added = 0
    for m in _RE_CARD.finditer(html):
        try:
            if record_anchor(exam_code, int(m.group("topic")),
                             int(m.group("qnum")), int(m.group("qid")), flush=False):
                added += 1
        except (TypeError, ValueError):
            continue
    save_anchors()
    if added:
        LOG.info(f"  [Tat dinh] Nap {added} anchor question_id tu trang exam.")
    return added


def discussion_url(discussion_id, exam_code, topic, qnum, category=None):
    """Dung URL discussion chuan tu discussion_id.

    Slug ma de trong URL phai la dang canonical (bo het ky tu khong phai chu/so:
    `H12-711_V4.0` -> `h12711v40`). DA DO TREN TRANG THAT: dau CHAM trong slug ma
    de lam server tra 404 (`exam-h12-711_v4.0-...` -> 404, `exam-h12-711_v40-...`
    -> 200, `exam-h12-411_v2.0-...` -> 404, `exam-fcss_nst_se-7.6-...` -> 404).
    Truoc day ham nay dung `normalize_exam_code` (giu `_` va `.`) nen moi ma de co
    dau cham deu sinh ra URL chet -> cau hoi that bi coi la "khong lay duoc".
    Phan category KHONG bi rang buoc nay (dien gi cung duoc), nhung cung chuan hoa
    cho gon va nhat quan.
    """
    slug = canonical_exam_code(exam_code)
    cat = canonical_exam_code(category) if category else (slug or "exam")
    return (f"https://www.examtopics.com/discussions/{cat}/view/"
            f"{discussion_id}-exam-{slug}-topic-{int(topic)}-"
            f"question-{int(qnum)}-discussion/")


def question_id_from_html(html):
    """Doc question_id tu HTML trang discussion (de thu hoach anchor)."""
    if not html:
        return None
    m = _RE_QUESTION_ID.search(html)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def resolve(exam_code, topic, qnum):
    """Giai URL discussion khong can search. Tra ve URL hoac None.

    Moi ung vien deu duoc VERIFY bang title cua AJAX (dung ma de + topic + cau),
    nen doan sai bi loai bo thay vi tra ve link cua cau khac.
    """
    code = canonical_exam_code(exam_code)
    try:
        topic, qnum = int(topic), int(qnum)
    except (TypeError, ValueError):
        return None
    if not code or qnum < 1:
        return None

    anchors = load_anchors().get(code) or {}
    if not anchors and code not in _SEED_ATTEMPTED:
        seed_from_exam_page(exam_code)
        anchors = load_anchors().get(code) or {}
    if not anchors:
        return None

    # Uu tien anchor gan nhat cung topic, nhung DEDUPE gia doan: nhieu anchor
    # gan nhau cho ra cung mot question_id nen thu het se ton request vo ich.
    guesses = []
    same_topic = [(q, qid) for (t, q), qid in anchors.items() if t == topic]
    for anchor_q, anchor_qid in sorted(same_topic, key=lambda x: abs(x[0] - qnum)):
        guess = anchor_qid + (qnum - anchor_q)
        if guess > 0 and guess not in guesses:
            guesses.append(guess)

    for guess in guesses[:MAX_ANCHOR_TRIES]:
        got = ajax_lookup(guess)
        if not got:
            continue
        did, title = got
        if parse_title(title) != (code, topic, qnum):
            continue
        record_anchor(exam_code, topic, qnum, guess)
        return discussion_url(did, exam_code, topic, qnum,
                              category=CATEGORY.get(code))
    return None
