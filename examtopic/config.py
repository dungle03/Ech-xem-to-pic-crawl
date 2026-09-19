import os
import re
import hashlib
import httpx
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image as PILImage

MIN_DELAY = 2
MAX_DELAY = 5
RETRY_LIMIT = 3
BLOCKED_ABORT_STREAK = 3
OUTPUT_DIR = "output"
_IMG_CACHE_DIR = os.path.join(OUTPUT_DIR, ".imgcache")

DEFAULT_OP_TIMEOUT = 30000

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

def set_proxy(proxy_url):
    global _PROXY
    _PROXY = proxy_url.strip() if proxy_url and isinstance(proxy_url, str) else None

# Giu lai <script type="application/json"> chua voted-answers-tally
_RE_SCRIPT = re.compile(r'<script\b(?![^>]*\btype=[\x22\x27]application/json[\x22\x27])[^>]*>.*?</script>|<script\b(?![^>]*\btype=[\x22\x27]application/json[\x22\x27])[^>]*/>', re.S | re.I)
_RE_IFRAME = re.compile(r'<iframe\b[^>]*>.*?</iframe>', re.S | re.I)
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
    print(f"  Dang tai {total_imgs} anh (song song)...")
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    with httpx.Client(headers=_IMG_HEADERS, cookies=_SESSION_COOKIES or None, proxy=_PROXY, limits=limits, timeout=_IMG_TIMEOUT, follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {pool.submit(_fetch_image_bytes, u, client): u for u in todo}
            done = 0
            step = max(1, total_imgs // 5) if total_imgs > 20 else 5
            for future in as_completed(futures):
                done += 1
                if done % step == 0 or done == total_imgs:
                    print(f"    Tien do tai anh: {done}/{total_imgs}")
