"""Giai URL discussion cua ExamTopics khong can search engine.

Chuoi hoat dong THAT (da kiem chung tren du lieu song, thang 9/2026):

 1. `/search/?q=<ma-de>` tra ve link trang exam, tu do biet DUOC category that
    (vd `hqt-4180` -> `hitachi`). Category nay BAT BUOC: `/exams/<cat>/<slug>/`
    moi la 200, con `/exams/<slug>/<slug>/` la 404.
 2. `/discussions/<category>/<n>/` liet ke toan bo discussion cua vendor, kem
    URL day du dang
    `/discussions/<cat>/view/<id>-exam-<code>-topic-<t>-question-<q>-discussion/`.
    Day la NGUON CHINH: lay duoc URL that ma khong can search engine, khong can
    doan id.
 3. Trang exam (`/exams/<cat>/<slug>/view/1/`) tra ve q1..q10 kem dap an chinh
    thuc dang `Correct Answer: AD`. Dung lam nguon answer key cho cac cau do.

Nhung thu KHONG con hoat dong (tung duoc dung o ban cu, nay da bo):

 - `/ajax/discussion/exam-question/<id>`: 404 voi moi id. Truoc day day la
   duong chinh de doi question_id thanh discussion_id.
 - `/ajax/discussion/load-complete/`: 404 voi moi id (da kiem chung 9/2026).
   Trang discussion gio render du binh luan inline, khong con nut
   "Load full discussion...".
 - `data-id` tren `.question-body` cua trang discussion: nay la HANG SO
   (`825909`) cho moi cau, moi de -> khong dung lam anchor duoc nua.
 - `/exams/<slug>/<slug>/view/1/` ("category la cosmetic"): da thanh 404.
 - `view/<id>-x/` (slug trang tri, ky thuat "id walk" cua vai repo khac): 404.
   Site gio khoa trang discussion theo CAP (id, slug) DAY DU, khong theo id:
   `99394-...question-5...` -> 200 nhung `99394-x/`, `99394/`,
   `99394-...question-99...` deu 404. Nen khong the doan id de tim cau thieu.

Vi vay "anchor" question_id khong con y nghia; thay bang chi muc URL that.
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
    REQUEST_INTERVAL,
    THROTTLE_ATTEMPTS,
    THROTTLE_BACKOFF,
    _env_float,
    _IMG_HEADERS,
    _SESSION_COOKIES,
)
from .parser import canonical_exam_code, normalize_exam_code

BASE = "https://www.examtopics.com"
SEARCH_URL = BASE + "/search/"
LISTING_URL = BASE + "/discussions/{category}/{page}/"
EXAM_VIEW_URL = BASE + "/exams/{category}/{slug}/view/1/"

# Link trang exam trong ket qua search: /exams/<category>/<slug>/
_RE_EXAM_LINK = re.compile(r'/exams/([a-z0-9\-]+)/([a-z0-9\-_\.]+)/', re.I)

# Mot muc trong trang liet ke discussion cua vendor.
_RE_LISTING_ITEM = re.compile(
    r'/discussions/(?P<category>[a-z0-9\-]+)/view/(?P<did>\d+)-exam-'
    r'(?P<code>[a-z0-9\-_\.]+)-topic-(?P<topic>\d+)-question-(?P<qnum>\d+)-discussion',
    re.I,
)
_RE_PAGE_TOTAL = re.compile(
    r'Page\s*<strong>\d+</strong>\s*of\s*<strong>(\d+)</strong>', re.I)

# Trang exam: moi cau la mot card `id="qqqN"`, dap an nam trong card do.
_RE_CARD_SPLIT = re.compile(r'id="qqq(\d+)"')
# Trang that viet: `<strong>Correct Answer:</strong> <strong class="ml-1">AD</strong>`
# Nhung co the gap dang khong co the dong nhan: `Correct Answer: <strong>AD</strong>`.
# Vi vay the dong nhan `</strong>` phai la TUY CHON, neu khong regex se bo sot
# dap an that va tra ve {} am tham.
_RE_CORRECT_ANSWER = re.compile(
    r'Correct Answer:\s*(?:</strong>)?\s*<strong[^>]*>\s*([A-Z]{1,8})\s*</strong>',
    re.S)

# exam_code -> category that (vd hqt4180 -> hitachi).
CATEGORY = {}
# exam_code -> {(topic, qnum): url discussion that}.
INDEX = {}
# exam_code -> {qnum: "AD"} dap an chinh thuc lay tu trang exam.
ANSWER_KEY = {}
# Category da duoc quet HET trong phien nay. Khong co co nay thi moi cau khong
# co trong listing (vd hqt-4180 q32/q36...) se quet lai toan bo listing -> ton
# 3 request vo ich MOI CAU.
_HARVESTED = set()

# URL da xac nhan CHET: url -> thoi diem (monotonic) het hieu luc.
#
# 404 la TAT DINH, khong phai "dang bi chan": do tren trang that (9/2026), khi
# Cloudflare chan thi MOI request deu tra 429 (24 request song song -> 24x429,
# khong mot 404 nao), con 404 chi xay ra khi cap (id, slug) sai hoac cau da bi
# go/paywall. Vi vay 404 ket thuc ngay (khong retry), va duoc ghi nho o day de
# cac lan goi sau khong ton request nao.
#
# Co THOI HAN chu khong vinh vien: mot cau co the duoc cong khai lai, nen sau
# cooldown phai cho phep thu lai thay vi khoa vinh vien.
_DEAD_URLS = {}
DEAD_URL_COOLDOWN = float(_env_float("DEAD_URL_COOLDOWN", 300))

_DIRTY = False


def _index_path():
    return os.path.join(OUTPUT_DIR, ".discussion_urls.json")


# ---------------------------------------------------------------------------
# Gian nhip request
# ---------------------------------------------------------------------------
# Do tren trang that: 8 worker song song -> ~6 req/s, 0x429; 24 worker -> 24x429
# ngay lap tuc. Nen gian nhip moi request va giu pool nho la du; retry chi ap
# dung cho 429/503 (dang bi chan), KHONG ap dung cho 404 (link chet/paywall).
_last_request_ts = [0.0]


def _wait_for_slot():
    """Gian nhip toan cuc: dam bao cach request truoc it nhat REQUEST_INTERVAL."""
    if REQUEST_INTERVAL <= 0:
        return
    gap = time.time() - _last_request_ts[0]
    if gap < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - gap)
    _last_request_ts[0] = time.time()


def _retry_after_seconds(resp, fallback):
    """So giay nen cho theo header `Retry-After` cua server, hoac `fallback`.

    Cloudflare tra 429 kem `Retry-After`; ton trong no thi lan retry sau thanh
    cong thay vi dam tiep roi bi chan lai. Chap nhan ca dang so giay lan dang
    ngay HTTP (RFC 7231); gia tri rac/qua lon bi bo qua de khong treo tool.
    """
    raw = resp.headers.get("Retry-After") if resp is not None else None
    if raw:
        raw = str(raw).strip()
        try:
            return max(0.0, min(float(raw), 120.0))
        except (TypeError, ValueError):
            pass
        try:
            import email.utils
            when = email.utils.parsedate_to_datetime(raw)
            if when is not None:
                delta = when.timestamp() - time.time()
                return max(0.0, min(delta, 120.0))
        except (TypeError, ValueError, OverflowError):
            pass
    return fallback


def fetch_html_status(url, params=None, timeout=25):
    """Nhu `fetch_html` nhung tra ve `(html, status_code)`.

    `status_code` la ma HTTP cuoi cung da thay (None neu loi ket noi), cho phep
    caller phan biet "link chet/paywall" (404) voi "dang bi chan" (429/503).
    """
    deadline = _DEAD_URLS.get(url)
    if deadline is not None:
        if time.monotonic() < deadline:
            LOG.debug(f"    Bo qua URL da biet chet: {url}")
            return None, 404
        _DEAD_URLS.pop(url, None)
    ua = _IMG_HEADERS.get("User-Agent") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    proxy = config._PROXY
    last_status = None
    for attempt in range(THROTTLE_ATTEMPTS + 1):
        _wait_for_slot()
        try:
            resp = httpx.get(
                url,
                params=params,
                headers={"User-Agent": ua},
                cookies=_SESSION_COOKIES or None,
                proxy=proxy,
                timeout=timeout,
                follow_redirects=True,
            )
        except Exception as e:
            LOG.warning(f"    Loi ket noi: {e}")
            return None, None
        last_status = resp.status_code
        if resp.status_code == 200 and resp.text:
            return resp.text, 200
        # CHI 429/503 moi la "co the dang bi chan". Do tren trang that: khi bi
        # chan, MOI request deu tra 429 (24 request song song -> 24x429, khong
        # co 404 nao). Con 404 la TAT DINH cho cap (id, slug) sai -> retry chi
        # dot 28s vo ich va lam nguoi dung tuong tool treo.
        if resp.status_code in (429, 503) and attempt < THROTTLE_ATTEMPTS:
            wait = _retry_after_seconds(resp, THROTTLE_BACKOFF * (2 ** attempt))
            LOG.info(f"    HTTP {resp.status_code} - dang bi chan, "
                     f"thu lai sau {wait:.0f}s (lan {attempt + 1}/{THROTTLE_ATTEMPTS})...")
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            LOG.info("    HTTP 404 - link chet/paywall, khong thu lai.")
        else:
            LOG.info(f"    HTTP {resp.status_code} cho {url}")
        break
    # 404 = link chet THAT (cap id+slug sai, hoac cau bi go/paywall). Ghi nho CO
    # THOI HAN de cac lan retry sau khong dam lai, nhung van cho thu lai sau khi
    # cooldown het (404 cung co the do cau duoc cong khai lai).
    if last_status == 404:
        _DEAD_URLS[url] = time.monotonic() + DEAD_URL_COOLDOWN
    return None, last_status


def fetch_html(url, params=None, timeout=25):
    """GET HTML voi gian nhip + retry khi bi chan. Tra ve text hoac None.

    Dung chung cho ca resolver lan crawler de moi request deu duoc gian nhip;
    neu chi mot duong gian nhip thi duong con lai van keo bi chan.

    URL da biet CHET (xem `_DEAD_URLS`) tra ve None ngay, khong ton request.
    """
    html, _status = fetch_html_status(url, params=params, timeout=timeout)
    return html


# ---------------------------------------------------------------------------
# Chi muc URL (thay cho "anchor" question_id cua ban cu)
# ---------------------------------------------------------------------------
def _mark_dirty():
    global _DIRTY
    _DIRTY = True


def clear_index():
    """Xoa chi muc trong bo nho (dung cho test)."""
    global _DIRTY
    CATEGORY.clear()
    INDEX.clear()
    ANSWER_KEY.clear()
    _HARVESTED.clear()
    _DEAD_URLS.clear()
    _DIRTY = False


def load_index():
    """Nap category + URL + answer key tu dia (idempotent)."""
    if INDEX or CATEGORY:
        return INDEX
    try:
        with open(_index_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return INDEX
    if not isinstance(data, dict):
        return INDEX
    for code, cat in (data.get("categories") or {}).items():
        if isinstance(cat, str) and cat:
            CATEGORY[str(code)] = cat
    for code, bucket in (data.get("urls") or {}).items():
        if not isinstance(bucket, dict):
            continue
        parsed = {}
        for key, url in bucket.items():
            try:
                topic, qnum = (int(x) for x in str(key).split("-", 1))
            except (TypeError, ValueError):
                continue
            if isinstance(url, str) and url:
                parsed[(topic, qnum)] = url
        if parsed:
            INDEX[str(code)] = parsed
    for code, bucket in (data.get("answers") or {}).items():
        if isinstance(bucket, dict):
            ANSWER_KEY[str(code)] = {
                int(q): str(a) for q, a in bucket.items()
                if str(q).isdigit() and a
            }
    return INDEX


def save_index():
    """Ghi chi muc xuong dia theo kieu atomic."""
    global _DIRTY
    if not _DIRTY:
        return
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = _index_path()
        tmp = path + ".tmp"
        payload = {
            "categories": CATEGORY,
            "urls": {code: {f"{t}-{q}": u for (t, q), u in bucket.items()}
                     for code, bucket in INDEX.items()},
            "answers": {code: {str(q): a for q, a in bucket.items()}
                        for code, bucket in ANSWER_KEY.items()},
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
        _DIRTY = False
    except OSError as e:
        LOG.warning(f"  Khong ghi duoc chi muc URL: {e}")


# ---------------------------------------------------------------------------
# Doi chieu ma de <-> slug
# ---------------------------------------------------------------------------
def exam_slug_variants(exam_code):
    """Cac dang slug co the dung, theo thu tu thu.

    LUU Y: dau GACH NGANG la ky tu hop le va phai duoc GIU. Do tren trang that:
    `exam-hqt-4180-topic-...` -> 200, con `exam-hqt4180-topic-...` -> 404. Ban cu
    dung `canonical_exam_code` (xoa het ky tu khong phai chu/so) nen moi ma de co
    gach ngang deu sinh URL chet.

    Dau CHAM va GACH DUOI thi nguoc lai: `H12-711_V4.0` duoc site viet thanh
    `h12-711-v4-0`.
    """
    raw = str(exam_code or "").strip().lower()
    norm = normalize_exam_code(exam_code)
    variants = []
    for cand in (
        norm,                                  # hqt-4180, h12-711_v4.0
        re.sub(r'[_.]', '-', norm),            # h12-711-v4-0 (dang site dung)
        re.sub(r'[_.]', '', norm),             # h12-711v40
        canonical_exam_code(exam_code),        # hqt4180, h12711v40
        re.sub(r'[^a-z0-9]+', '-', raw).strip('-'),
    ):
        cand = re.sub(r'-+', '-', cand).strip('-')
        if cand and cand not in variants:
            variants.append(cand)
    return variants


def discover_category(exam_code):
    """Tim category that (vendor) cua ma de qua trang search. None neu khong thay.

    Category BAT BUOC de dung URL trang exam: `/exams/hqt-4180/hqt-4180/` -> 404,
    con `/exams/hitachi/hqt-4180/` -> 200.
    """
    code = canonical_exam_code(exam_code)
    if not code:
        return None
    load_index()
    if code in CATEGORY:
        return CATEGORY[code]
    for slug in exam_slug_variants(exam_code):
        html = fetch_html(SEARCH_URL, params={"q": slug})
        if not html:
            continue
        for cat, found in _RE_EXAM_LINK.findall(html):
            if canonical_exam_code(found) == code:
                CATEGORY[code] = cat.lower()
                _mark_dirty()
                LOG.info(f"  [Danh muc] {exam_code} -> {cat}")
                return CATEGORY[code]
    LOG.info(f"  [Danh muc] Khong tim thay category cho {exam_code}.")
    return None


# ---------------------------------------------------------------------------
# Thu thap URL discussion tu trang liet ke cua vendor
# ---------------------------------------------------------------------------
def harvest_listing(category, max_pages=30):
    """Quet `/discussions/<category>/<n>/`, ghi moi URL discussion that vao INDEX.

    Tra ve so URL MOI them duoc. Day la duong thay the cho AJAX da chet.
    Category da quet trong phien nay thi tra ve 0 ngay (tranh quet lai).
    """
    if not category:
        return 0
    if category in _HARVESTED:
        return 0
    added = 0
    total_pages = None
    for page in range(1, max_pages + 1):
        html = fetch_html(LISTING_URL.format(category=category, page=page))
        if not html:
            break
        items = _RE_LISTING_ITEM.findall(html)
        if not items:
            break
        for cat, did, code, topic, qnum in items:
            key = (int(topic), int(qnum))
            url = (f"{BASE}/discussions/{cat.lower()}/view/{did}-exam-{code}-"
                   f"topic-{topic}-question-{qnum}-discussion/")
            bucket = INDEX.setdefault(canonical_exam_code(code), {})
            if bucket.get(key) != url:
                bucket[key] = url
                added += 1
        if total_pages is None:
            info = _RE_PAGE_TOTAL.search(html)
            if info:
                total_pages = int(info.group(1))
        if total_pages is not None and page >= total_pages:
            break
    _HARVESTED.add(category)
    if added:
        _mark_dirty()
        LOG.info(f"  [Thu thap] {category}: them {added} URL discussion.")
    return added


def seed_from_exam_page(exam_code):
    """Chuan bi chi muc cho mot ma de: tim category roi quet trang liet ke.

    Ten ham duoc giu lai cho tuong thich voi tool.py (ban cu no nap "anchor"
    question_id tu trang exam; cach do da chet nen nay no lam viec tuong duong
    nhung bang nguon con song). Tra ve so URL moi them duoc.
    """
    load_index()
    category = discover_category(exam_code)
    if not category:
        return 0
    added = harvest_listing(category)
    if added:
        save_index()
    return added


# ---------------------------------------------------------------------------
# Answer key tu trang exam (chi q1..q10 mien phi)
# ---------------------------------------------------------------------------
def exam_answer_key(exam_code):
    """{qnum: 'AD'} dap an chinh thuc tu trang exam. {} neu khong lay duoc.

    Trang exam chi tra mien phi 10 cau dau (q11+ doi dang nhap), nhung voi cac
    cau do day la nguon dap an CHINH THUC - tot hon han viec suy tu binh luan.
    """
    code = canonical_exam_code(exam_code)
    if not code:
        return {}
    load_index()
    if ANSWER_KEY.get(code):
        return ANSWER_KEY[code]
    category = discover_category(exam_code)
    if not category:
        return {}
    for slug in exam_slug_variants(exam_code):
        html = fetch_html(EXAM_VIEW_URL.format(category=category, slug=slug))
        if not html:
            continue
        key = _parse_answer_key(html)
        if key:
            ANSWER_KEY[code] = key
            _mark_dirty()
            save_index()
            LOG.info(f"  [Answer key] Lay duoc dap an chinh thuc cho {len(key)} cau dau.")
            return key
    return {}


def _parse_answer_key(html):
    """Tach {qnum: 'AD'} tu HTML trang exam (moi cau la card `id="qqqN"`)."""
    out = {}
    parts = _RE_CARD_SPLIT.split(html or "")
    # parts = [truoc, qnum1, than1, qnum2, than2, ...]
    for i in range(1, len(parts) - 1, 2):
        try:
            qnum = int(parts[i])
        except (TypeError, ValueError):
            continue
        m = _RE_CORRECT_ANSWER.search(parts[i + 1])
        if m:
            out[qnum] = m.group(1).strip()
    return out


# ---------------------------------------------------------------------------
# API chinh
# ---------------------------------------------------------------------------
def is_dead(url):
    """URL nay da duoc xac nhan chet va con trong thoi gian cooldown?"""
    deadline = _DEAD_URLS.get(url)
    if deadline is None:
        return False
    if time.monotonic() < deadline:
        return True
    _DEAD_URLS.pop(url, None)
    return False


def mark_url_dead(url, exam_code=None, topic=None, qnum=None):
    """Danh dau mot URL la CHET va loai no khoi chi muc.

    Vi sao can: neu chi `forget_harvested_link` (cache search) thi `resolve()`
    van tra ve dung URL chet do tu INDEX -> `find_discussion_link` return ngay
    va KHONG BAO GIO roi xuong search DDG/Google. Xoa khoi INDEX + ghi vao
    `_DEAD_URLS` thi lan retry sau `resolve()` tra None -> tool roi xuong search
    dung nhu hanh vi mong doi.
    """
    if not url:
        return False
    _DEAD_URLS[url] = time.monotonic() + DEAD_URL_COOLDOWN
    removed = False
    code = canonical_exam_code(exam_code) if exam_code else None
    if code:
        bucket = INDEX.get(code) or {}
        for key, value in list(bucket.items()):
            if value == url:
                del bucket[key]
                removed = True
    if removed:
        _mark_dirty()
        save_index()
    return removed


def resolve(exam_code, topic, qnum):
    """Giai URL discussion khong can search. Tra ve URL hoac None.

    Uu tien chi muc da co; neu chua co thi tim category roi quet trang liet ke
    cua vendor (mot lan cho ca de), sau do tra cuu lai.

    URL da biet chet (xem `mark_url_dead`) KHONG duoc tra ve, de caller roi
    xuong search thay vi dam lai vao mot link hong.
    """
    code = canonical_exam_code(exam_code)
    try:
        topic, qnum = int(topic), int(qnum)
    except (TypeError, ValueError):
        return None
    if not code or qnum < 1:
        return None

    key = (topic, qnum)
    bucket = load_index().get(code) or {}
    found = bucket.get(key)
    if found:
        if is_dead(found):
            LOG.info("  [Tat dinh] Link trong chi muc da biet chet, bo qua de tim lai.")
            return None
        return found

    category = discover_category(exam_code)
    if not category:
        return None
    if harvest_listing(category):
        save_index()
    found = (INDEX.get(code) or {}).get(key)
    if found and is_dead(found):
        return None
    return found
