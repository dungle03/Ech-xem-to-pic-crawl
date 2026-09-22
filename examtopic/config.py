import os
import re
import sys
import logging
import hashlib
import httpx
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image as PILImage


def _env_int(name, default):
    """Doc bien moi truong dang so nguyen, tra ve `default` neu thieu/khong hop le.

    Cho phep tinh chinh delay/retry qua env ma khong phai sua code:
        MIN_DELAY=5 MAX_DELAY=9 python3 tool.py -e az-104
    Gia tri rac (chu, so am) bi bo qua va roi ve mac dinh thay vi lam crash tool.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _env_str(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw or default


MIN_DELAY = _env_int("MIN_DELAY", 2)
MAX_DELAY = _env_int("MAX_DELAY", 5)
RETRY_LIMIT = _env_int("RETRY_LIMIT", 3)
BLOCKED_ABORT_STREAK = _env_int("BLOCKED_ABORT_STREAK", 3)

# Retry tai discussion bang HTTP khi Cloudflare tra 429/503 giua phien.
RETRY_HTTP_ATTEMPTS = _env_int("RETRY_HTTP_ATTEMPTS", 2)
RETRY_HTTP_BACKOFF = float(_env_int("RETRY_HTTP_BACKOFF", 1))

OUTPUT_DIR = _env_str("OUTPUT_DIR", "output")
_IMG_CACHE_DIR = os.path.join(OUTPUT_DIR, ".imgcache")

DEFAULT_OP_TIMEOUT = _env_int("DEFAULT_OP_TIMEOUT", 30000)

NO_DISCUSSION_BLOCKED = object()
NO_DISCUSSION_MISSING = object()

SEARCH_OK = "ok"
SEARCH_EMPTY = "empty"
SEARCH_BLOCKED = "blocked"
SEARCH_ERROR = "error"

_IMG_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_IMG_CACHE = {}
_SESSION_COOKIES = {}
_HARVESTED_LINKS = {}
_PROXY = None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Tool nay xuat ra console de nguoi dung theo doi tien do truc tiep, nen KHONG
# dung format logging mac dinh (co timestamp/level) -- no se lam thay doi toan
# bo output ma nguoi dung da quen. Thay vao do ta ve dung chuoi goc, va dung
# level chi de LOC bot khi chay CI/nen (--quiet) hoac hien them khi debug.
#
# Mac dinh (khong co flag) cho ra output Y HET phan lon truong hop cu.
LOG = logging.getLogger("examtopic")

_LEVEL_STYLES = {
    logging.DEBUG: "verbose",
    logging.INFO: "normal",
    logging.WARNING: "normal",
    logging.ERROR: "normal",
}


class _PlainFormatter(logging.Formatter):
    """Giu nguyen chuoi goc, khong them timestamp/level/ten logger."""

    def format(self, record):
        message = record.getMessage()
        # Giu kha nang in loi kem traceback khi can (exc_info).
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        return message


def _build_handler(stream):
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_PlainFormatter())
    return handler


def configure_logging(quiet=False, verbose=False, stream=None):
    """Thiet lap muc log cho tool.

    - Mac dinh: INFO  -> in moi thu nhu cu (khong doi hanh vi).
    - quiet    : WARNING -> chi in canh bao/loi, hop voi CI hoac ghi log file.
    - verbose  : DEBUG   -> in them chi tiet chan doan (retry, cache, ...).

    Tra ve level da dat de tien test.
    """
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    LOG.setLevel(level)
    LOG.propagate = False
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
    LOG.addHandler(_build_handler(stream if stream is not None else sys.stdout))
    return level


# Cau hinh mac dinh ngay khi import: giu nguyen hanh vi cu (in ra stdout).
configure_logging()


def set_proxy(proxy_url):
    global _PROXY
    _PROXY = proxy_url.strip() if proxy_url and isinstance(proxy_url, str) else None

# Giu lai <script type="application/json"> chua voted-answers-tally.
# Cho phep khoang trang quanh dau '=' va quanh gia tri (vd: type = "application/json")
# vi HTML hop le van dung duoc bien the nay; neu khong, tally (nguon du lieu
# community_most_voted) se bi xoa am tham ma khong bao loi.
_RE_SCRIPT = re.compile(
    r'<script\b(?![^>]*\btype\s*=\s*[\x22\x27]\s*application/json\s*[\x22\x27])[^>]*>.*?</script>'
    r'|'
    r'<script\b(?![^>]*\btype\s*=\s*[\x22\x27]\s*application/json\s*[\x22\x27])[^>]*/>',
    re.S | re.I,
)
_RE_IFRAME = re.compile(r'<iframe\b[^>]*>.*?</iframe>', re.S | re.I)
# Endpoint tra ve fragment HTML chua TOAN BO binh luan cua mot discussion.
# Trang discussion chi render san ~20-25 binh luan dau; phan con lai nam sau
# nut "Load full discussion..." va chi lay duoc qua AJAX nay.
LOAD_COMPLETE_URL = "https://www.examtopics.com/ajax/discussion/load-complete/"
_RE_EXAMTOPICS_URL = re.compile(r'https?://(?:www\.)?examtopics\.com/[^\s&"\'<>]+', re.I)
_RE_DISCUSSION_SLUG = re.compile(
    r'exam-(?P<code>.+?)-topic-(?P<topic>\d+)-question-(?P<qnum>\d+)-discussion',
    re.I,
)

_IMG_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0)

SEARCH_ENGINES = {
    "duckduckgo": {
        "home": "https://duckduckgo.com/",
        "box_selectors": ('input[name="q"]', 'input#searchbox_input', 'textarea[name="q"]'),
        "result_selectors": (
            '[data-testid="result"]',
            'a[data-testid="result-title-a"]',
            'article',
            'a[href*="examtopics.com"]',
        ),
        "has_consent": False,
    },
    "google": {
        "home": "https://www.google.com/",
        "box_selectors": ('textarea[name="q"]', 'input[name="q"]'),
        "result_selectors": (
            'div#search',
            'div#rso',
            'a[href*="examtopics.com"]',
        ),
        "has_consent": True,
    },
}

_BLOCK_SELECTORS = (
    "#anomaly",
    "#challenge-form",
    "#captcha",
    ".g-recaptcha",
    'iframe[src*="recaptcha"]',
)
_BLOCK_TEXT = (
    "unfortunately, bots use duckduckgo too",
    "verify that you're a real person",
    "unusual traffic from your computer network",
    "just a moment...",
    "attention required",
)

def _img_cache_key(url):
    return hashlib.md5(url.encode()).hexdigest()

def _img_cache_path(url):
    key = _img_cache_key(url)
    return os.path.join(_IMG_CACHE_DIR, key)

def _fetch_image_bytes(url, client=None):
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    cache_path = _img_cache_path(url)
    try:
        if os.path.isfile(cache_path):
            with open(cache_path, "rb") as f:
                data = f.read()
            _IMG_CACHE[url] = data
            return data
    except Exception:
        pass
    try:
        if client:
            resp = client.get(url, timeout=_IMG_TIMEOUT)
        else:
            resp = httpx.get(url, headers=_IMG_HEADERS, cookies=_SESSION_COOKIES or None, proxy=_PROXY, timeout=_IMG_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        raw = resp.content
        if (raw.startswith(b'\x89PNG\r\n\x1a\n')
                or raw.startswith(b'\xff\xd8\xff')
                or raw.startswith(b'GIF8')):
            data = raw
        else:
            img = PILImage.open(BytesIO(raw))
            buf = BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
    except Exception:
        _IMG_CACHE[url] = None
        return None
    _IMG_CACHE[url] = data
    try:
        os.makedirs(_IMG_CACHE_DIR, exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(data)
    except Exception:
        pass
    return data

def _fetch_image(url, client=None):
    data = _fetch_image_bytes(url, client=client)
    return BytesIO(data) if data is not None else None

def _preload_images(questions):
    urls = set()
    for q in questions:
        urls.update(q.get("question_images") or [])
        for opt in (q.get("options") or []):
            if isinstance(opt, dict):
                urls.update(opt.get("images") or [])
    todo = [u for u in urls
            if u not in _IMG_CACHE and not os.path.isfile(_img_cache_path(u))]
    if not todo:
        return
    total_imgs = len(todo)
    LOG.info(f"  Dang tai {total_imgs} anh (song song)...")
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    with httpx.Client(headers=_IMG_HEADERS, cookies=_SESSION_COOKIES or None, proxy=_PROXY, limits=limits, timeout=_IMG_TIMEOUT, follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_image_bytes, u, client): u for u in todo}
            done = 0
            step = max(1, total_imgs // 5) if total_imgs > 20 else 5
            for future in as_completed(futures):
                done += 1
                if done % step == 0 or done == total_imgs:
                    # Giu o INFO de output mac dinh KHONG doi so voi truoc.
                    # Khi chay --quiet thi dong nay (va moi INFO khac) se tat.
                    LOG.info(f"    Tien do tai anh: {done}/{total_imgs}")
