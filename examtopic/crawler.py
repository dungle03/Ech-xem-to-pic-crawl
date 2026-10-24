import re
import time
import random
from urllib.parse import urljoin, quote_plus
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import resolver
from .config import (
    LOG,
    DEFAULT_OP_TIMEOUT,
    SEARCH_ENGINES,
    SEARCH_OK,
    SEARCH_EMPTY,
    SEARCH_BLOCKED,
    SEARCH_ERROR,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    NO_DISCUSSION_GATED,
    _BLOCK_SELECTORS,
    _BLOCK_TEXT,
    _IMG_HEADERS,
    _SESSION_COOKIES,
    _HARVESTED_LINKS,
    _RE_SCRIPT,
    _RE_IFRAME,
    _RE_NOISE_COMMENT,
)
from .parser import (
    canonical_exam_code,
    extract_matching_link,
    no_link_result,
)

def sync_browser_session(page):
    """Dong bo User-Agent thuc va Cookies tu Playwright context sang httpx.

    Dam bao cac request tai anh va HTTP fallback dung chung dung 1 fingerprint
    va cookie Cloudflare session voi CloakBrowser. Tra ve True neu lay thanh cong.
    """
    # Khong can `global` o day: ta chi MUTATE hai dict nay tai cho
    # (`_IMG_HEADERS[...] = ...`, `_SESSION_COOKIES.clear()/update()`), khong
    # bao gio gan lai ten. Vi dict la mutable va duoc share theo reference giua
    # cac module, thay doi se duoc nhin thay o moi noi.
    if not page:
        return False
    synced = False
    try:
        ua = page.evaluate("navigator.userAgent")
        if ua and isinstance(ua, str) and len(ua) > 10:
            _IMG_HEADERS["User-Agent"] = ua
            synced = True
    except Exception:
        pass
    try:
        cookies = page.context.cookies()
        _SESSION_COOKIES.clear()
        _SESSION_COOKIES.update({c["name"]: c["value"] for c in cookies if "name" in c and "value" in c})
        if _SESSION_COOKIES:
            synced = True
    except Exception:
        pass
    return synced

def safe_close(obj):
    """Dong an toan mot page/context/tab/browser, nuot loi dong khong quan trong."""
    if obj is None:
        return
    try:
        obj.close()
    except Exception:
        pass

def safe_goto(page, url, timeout=60000):
    try:
        page.goto(url, wait_until="commit", timeout=timeout)
        time.sleep(1)
        return True
    except Exception as e:
        LOG.warning(f"    Loi dieu huong: {e}")
        return False

def warmup_search(page):
    """Ghe trang chu DuckDuckGo mot lan dau de tao cookie/session.

    DuckDuckGo khoan dung voi truy van tu dong hon Google rat nhieu (it
    CAPTCHA), nen ta dung DDG lam engine chinh. Chi goi mot lan khi bat dau
    phien. DDG khong co man hinh consent nen warm-up don gian.
    """
    if not safe_goto(page, SEARCH_ENGINES["duckduckgo"]["home"]):
        return False
    time.sleep(random.uniform(1.0, 2.0))
    return True

def _accept_consent(page):
    """Chap nhan man hinh consent cua Google neu hien (doc lap ngon ngu)."""
    for sel in ('button#L2AGLb', 'button:has-text("Accept all")',
                'button:has-text("I agree")'):
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.click()
                time.sleep(random.uniform(0.5, 1.0))
                return
        except Exception:
            continue

def _search_is_blocked(page):
    """Nhan biet man hinh CAPTCHA/anomaly cua DuckDuckGo hoac Google."""
    try:
        if "/sorry/" in page.url.lower():
            return True
        for selector in _BLOCK_SELECTORS:
            if page.query_selector(selector):
                return True
        state = page.evaluate(
            "() => ({title: document.title || '', text: document.body?.innerText.slice(0, 4000).toLowerCase() || ''})"
        )
        title = state.get("title", "").lower()
        text = state.get("text", "")
        return any(marker in title or marker in text for marker in _BLOCK_TEXT)
    except Exception:
        return False

def _read_search_result(page, cfg, engine, wait_load=True):
    """Cho ket qua hien va doc trang thai search. Dung chung cho ca 2 duong.

    Ket qua render bat dong bo SAU khi domcontentloaded da fire, nen phai doi
    tan element ket qua xuat hien, khong sleep cung.

    `wait_load=False` khi caller da cho trang load xong roi (duong URL truc tiep
    truyen `wait_until="domcontentloaded"` vao chinh `goto`): cho them lan nua la
    doi vo ich ~4s moi lan search.
    """
    got_results = False
    if wait_load:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_OP_TIMEOUT)
        except PlaywrightTimeoutError:
            pass
    combined_sel = ", ".join(cfg["result_selectors"])
    try:
        page.wait_for_selector(combined_sel, timeout=8000)
        got_results = True
    except (PlaywrightTimeoutError, Exception):
        pass
    time.sleep(random.uniform(0.4, 0.8))
    if _search_is_blocked(page):
        LOG.warning(f"  {engine} bi chan/CAPTCHA sau khi search")
        return SEARCH_BLOCKED
    return SEARCH_OK if got_results else SEARCH_EMPTY

def _search_via_url(page, cfg, query, engine):
    """Duong nhanh: dieu huong thang toi URL ket qua cua engine.

    Do tren trang that: ~1.8-3.7s thay vi 12.9s vi bo duoc buoc ve trang chu +
    go tung ky tu + cho tung ky tu. Da do 22/22 lan lien tiep khong bi CAPTCHA
    tren DuckDuckGo. Tra ve None neu khong dung duoc (thieu template, khong tai
    duoc trang, hoac bi chan) de caller rot ve duong go tay.
    """
    template = cfg.get("url_template")
    if not template:
        return None
    url = template.format(query=quote_plus(query))
    # Cho thang domcontentloaded trong goto: khong can them wait_for_load_state
    # nua, tiet kiem ~4s moi lan search (do duoc).
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        LOG.warning(f"    Khong tai duoc URL search truc tiep: {e}")
        return None
    if cfg["has_consent"]:
        _accept_consent(page)
    if _search_is_blocked(page):
        # Bi chan ngay khi vao -> tra None de thu duong go tay (giong nguoi hon).
        return None
    return _read_search_result(page, cfg, engine, wait_load=False)

def _search_by_typing(page, cfg, query, engine):
    """Duong du phong: ve trang chu roi go tung ky tu nhu nguoi that.

    Cham hon nhung giong nguoi hon, nen giu lai cho truong hop URL truc tiep bi
    chan/CAPTCHA.
    """
    # Luon ve trang chu de co o tim kiem trong, sach.
    if not safe_goto(page, cfg["home"]):
        LOG.warning(f"  Khong tai duoc {engine}")
        return SEARCH_BLOCKED
    if _search_is_blocked(page):
        LOG.warning(f"  {engine} dang hien CAPTCHA/challenge")
        return SEARCH_BLOCKED
    time.sleep(random.uniform(0.5, 1.0))

    if cfg["has_consent"]:
        _accept_consent(page)

    # Tim o input.
    search_box = None
    for sel in cfg["box_selectors"]:
        try:
            search_box = page.query_selector(sel)
            if search_box:
                break
        except Exception:
            continue
    if not search_box:
        LOG.warning(f"  Khong tim thay o tim kiem {engine}")
        return SEARCH_BLOCKED

    # Click vao o, xoa sach noi dung cu (phong khi con sot), go query moi.
    try:
        search_box.click()
        time.sleep(random.uniform(0.2, 0.4))
        # fill("") xoa sach o input mot cach chac chan truoc khi go tay.
        try:
            search_box.fill("")
        except Exception:
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
        time.sleep(random.uniform(0.1, 0.2))
        # Go tung ky tu voi delay ngau nhien de giong nguoi.
        for ch in query:
            page.keyboard.type(ch, delay=random.randint(25, 70))
            if random.random() < 0.10:
                time.sleep(random.uniform(0.1, 0.25))
        time.sleep(random.uniform(0.3, 0.7))
        page.keyboard.press("Enter")
    except Exception as e:
        LOG.warning(f"  Loi go query: {e}")
        return SEARCH_ERROR

    return _read_search_result(page, cfg, engine)

def search_engine(page, query, engine="duckduckgo"):
    """Search by opening the engine home page and typing like a user by default.

    The query is entered character-by-character with small randomized delays;
    direct search-URL navigation remains available only as an explicit helper,
    not the default runtime path.

    Returns `SEARCH_OK`, `SEARCH_EMPTY`, `SEARCH_BLOCKED`, or `SEARCH_ERROR`.
    """
    cfg = SEARCH_ENGINES.get(engine)
    if not cfg:
        LOG.warning(f"  Engine khong ho tro: {engine}")
        return SEARCH_ERROR
    return _search_by_typing(page, cfg, query, engine)

def forget_harvested_link(exam_code, topic, qnum):
    """Xoa mot link KHOI cache `_HARVESTED_LINKS` sau khi xac dinh no hong.

    Vi sao can: cache nay duoc ghi tu ket qua search va tu du lieu cu. Search
    engine co the tra ve URL dung dinh dang nhung da chet (404 that), va ban cu
    cu dung lai dung link do cho MOI lan retry -> 3 lan thu vo ich cho mot cau.
    Xoa khoi cache thi lan sau se di tim lai thay vi dam vao tuong.
    """
    try:
        key = (canonical_exam_code(exam_code), int(topic), int(qnum))
    except (TypeError, ValueError):
        return False
    return _HARVESTED_LINKS.pop(key, None) is not None


def find_discussion_link(page, exam_code, topic, qnum):
    """Tim URL discussion khop cau hoi. Thu TAT DINH truoc, roi moi den search.

    Thu tu:
    0. Bo giai tat dinh (`resolver.resolve`): dung question_id + AJAX cua chinh
       examtopics, KHONG dung search engine. Day la duong chinh vi no khong phu
       thuoc vao viec search engine co index dung trang hay khong.
    1. DuckDuckGo voi 2 dang query (co/khong `site:`).
    2. Google voi 2 dang query do.

    Vi sao van phai giu search: bo giai tat dinh can 1 "anchor" (question_id da
    biet) cho moi khoi cau. Khoi dau tien luon co san tu trang exam, con khoi sau
    thi phai cho den khi crawl duoc 1 cau trong khoi do. Khi search tim ra cau dau
    tien cua khoi, anchor duoc ghi lai va cac cau con lai cua khoi duoc giai tat
    dinh -> search chi con dung 1 lan cho moi khoi thay vi moi cau.
    """
    target_key = (canonical_exam_code(exam_code), int(topic), int(qnum))
    if target_key in _HARVESTED_LINKS:
        cached_url = _HARVESTED_LINKS[target_key]
        LOG.info(f"  [Bo nho cache] Dung link discussion da thu thap: {cached_url}")
        return cached_url
    # 0. Duong tat dinh (khong search).
    try:
        resolved = resolver.resolve(exam_code, topic, qnum)
    except Exception as e:
        LOG.warning(f"  Loi bo giai tat dinh: {e}")
        resolved = None
    if resolved:
        LOG.info(f"  [Tat dinh] Giai duoc link khong can search: {resolved}")
        return resolved

    queries = (
        f"exam {exam_code} topic {topic} question {qnum} discussion site:examtopics.com",
        f'exam "{exam_code}" topic {topic} question {qnum} discussion',
    )
    statuses = {"duckduckgo": SEARCH_ERROR, "google": SEARCH_ERROR}
    # Thu het cac dang query tren DuckDuckGo TRUOC khi chuyen sang Google: DDG
    # khoan dung voi query tu dong hon nhieu, con Google de ra CAPTCHA nen chi nen
    # goi khi DDG da het cach.
    for index, query in enumerate(queries):
        status = search_engine(page, query, "duckduckgo")
        statuses["duckduckgo"] = status
        if status == SEARCH_OK:
            href = extract_matching_link(page, exam_code, topic, qnum)
            if href:
                return href
        if status == SEARCH_BLOCKED:
            LOG.info("  DuckDuckGo bi chan/CAPTCHA.")
        elif status == SEARCH_EMPTY:
            LOG.info("  DuckDuckGo khong tra ve ket qua nao.")
        else:
            LOG.info("  DuckDuckGo khong co link dung cau.")
        if index < len(queries) - 1:
            LOG.info("  Thu lai bang dang query khac (bo 'site:', boc ma de trong ngoac kep)...")

    for query in queries:
        status = search_engine(page, query, "google")
        statuses["google"] = status
        if status == SEARCH_OK:
            href = extract_matching_link(page, exam_code, topic, qnum)
            if href:
                return href
        if status == SEARCH_BLOCKED:
            LOG.info("  Google bi chan/CAPTCHA.")
        elif status == SEARCH_EMPTY:
            LOG.info("  Google khong tra ve ket qua nao.")
        else:
            LOG.info("  Google khong co link dung cau.")
    return no_link_result(statuses["duckduckgo"], statuses["google"])

def close_extra_tabs(main_page):
    """Dong moi tab tru tab DuckDuckGo chinh (main_page).

    Sau moi cau, context chi con dung 1 tab DDG. Tranh tab discussion cu +
    cac popup do quang cao examtopics mo ra tich tu lam nang trinh duyet.
    """
    try:
        for pg in list(main_page.context.pages):
            if pg is not main_page:
                safe_close(pg)
    except Exception:
        pass

def wait_for_discussion(tab, timeout=DEFAULT_OP_TIMEOUT):
    """Cho khoi noi dung discussion (.discussion-header-container) hien.

    Cho tan element noi dung thay vi networkidle: trang examtopics hay treo
    o networkidle vi tracker/ads khong bao gio idle, nhung noi dung that su
    da co san. Tra ve True neu thay container, False neu het gio.
    """
    try:
        tab.wait_for_selector('.discussion-header-container', timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        return False
    except Exception:
        return False

def load_discussion_via_http_status(tab, href, timeout=20):
    """Nhu `load_discussion_via_http` nhung tra ve `(loaded, status_code)`.

    `status_code` cho caller biet VI SAO that bai: 404 = link chet/paywall (khong
    nen fallback sang browser, khong nen retry), 429/503 = dang bi chan, None =
    loi ket noi. Neu khong phan biet duoc, tool se mo browser cho mot link 404
    da biet -> `Page.goto: ERR_HTTP_RESPONSE_CODE_FAILURE` treo ~15s, dung nhu
    hien tuong "mo link blank va cho" ma nguoi dung bao.
    """
    # Dung resolver.fetch_html_status (khong goi httpx truc tiep) de MOI request
    # deu duoc GIAN NHIP toan cuc va retry khi bi chan. Do tren trang that: khi
    # bi chan MOI request deu tra 429 (24 song song -> 24x429, khong 404 nao),
    # con 404 la TAT DINH cho cap (id, slug) sai hoac cau bi go/paywall.
    html_text, status = resolver.fetch_html_status(href, timeout=timeout)
    if html_text is None:
        return False, status
    # Xoa script/iframe: chung khien trinh duyet co gang tai/thuc thi
    # tracker+ads, trong khi noi dung can boc la HTML tinh render san.
    html_text = _RE_SCRIPT.sub('', html_text)
    html_text = _RE_IFRAME.sub('', html_text)
    try:
        # Dung document.write thay cho set_content: no chi bom HTML vao DOM
        # dong bo, KHONG cho tai nguyen ngoai nao ca -> nap tuc thi (~0.1s),
        # tranh viec set_content treo cho commit/load vo han.
        tab.goto("about:blank", wait_until="commit", timeout=10000)
        tab.evaluate(
            "(h) => { document.open(); document.write(h); document.close(); }",
            html_text,
        )
    except Exception as e:
        LOG.warning(f"    Loi nap HTML vao tab: {e}")
        return False, status
    return tab.query_selector('.discussion-header-container') is not None, status


def load_discussion_via_http(tab, href, timeout=20):
    """Fallback: tai HTML discussion bang HTTP thuan roi nap vao tab.

    Trang discussion cua examtopics duoc render san tu server (curl/httpx lay
    duoc trong ~1s), nhung mo bang browser doi khi treo vo han vi tracker/ads.
    Ta tai HTML bang httpx, XOA cac the <script>/<iframe> (quang cao/tracker,
    khong can vi noi dung la HTML tinh render san), roi bom vao tab bang
    document.write de nap tuc thi ma KHONG cho tai nguyen ngoai.
    Tra ve True neu nap duoc noi dung discussion, False neu that bai.
    """
    loaded, _status = load_discussion_via_http_status(tab, href, timeout=timeout)
    return loaded

def _absolutize_images(urls, base_url):
    """Doi URL anh tuong doi thanh tuyet doi, lay `base_url` lam goc.

    Vi sao can: duong nap nhanh `load_discussion_via_http` bom HTML vao
    `about:blank` bang `document.write`, nen trang KHONG co base URL de phan
    giai. Khi do `im.src` tra ve nguyen chuoi tuong doi nam trong HTML
    (`/assets/media/exam-media/...`), va cac lop sau (`_safe_url` cua exporter)
    coi do la scheme khong an toan roi loai bo -> anh mat AM THAM, khong loi.
    Khi trang duoc nap bang dieu huong that thi `im.src` da la URL tuyet doi, nen
    ham nay chi la lop bao hiem (idempotent).

    Tra ve danh sach moi, giu nguyen thu tu va bo qua gia tri rac.
    """
    cleaned = []
    for u in urls or []:
        if not isinstance(u, str) or not u:
            continue
        if base_url and not u.startswith(("http://", "https://", "data:")):
            u = urljoin(base_url, u)
        cleaned.append(u)
    return cleaned

_RE_OPTION_LINE = re.compile(r'(?:^|\n)\s*([A-Z])[\.\)]\s+')


def _split_options_from_text(text):
    """Tach lua chon ra khoi text de bai, tra ve (de_bai, danh_sach_lua_chon).

    Vi sao can: tu 9/2026 trang discussion KHONG con markup
    `.question-choices-container .multi-choice-item` nua (do tren trang that: 0
    phan tu). Lua chon chi con nam lan trong text dang

        Which three RAID configurations are supported? (Choose three.)

        A. 2D + 2D

        B. 4D + 1P

    Neu khong tach, moi ban ghi se co `options: []` va exporter khong hien duoc
    lua chon nao (dung nhu 10 ban ghi hqt-4180 hong truoc day).

    Chi tach khi tim thay day du A, B, C... LIEN TIEP tu A: nho vay cau hoi co
    chu "A." trong de bai (vd "VSP G700. A drive fails") khong bi cat sai.
    """
    if not text:
        return text, []
    matches = list(_RE_OPTION_LINE.finditer(text))
    if len(matches) < 2:
        return text, []
    letters = [m.group(1) for m in matches]
    if letters != [chr(ord('A') + i) for i in range(len(letters))]:
        return text, []
    stem = text[:matches[0].start()].strip()
    if not stem:
        return text, []
    options = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if body:
            options.append({"letter": m.group(1), "text": body,
                            "images": [], "is_correct": False})
    if len(options) < 2:
        return text, []
    return stem, options


def _is_noise_comment(text):
    """Binh luan chi bao "da gap cau nay trong ky thi" -> khong phai y kien ve dap an.

    Do tren du lieu that ms-700 (20 cau dac biet): 13/86 (15%) binh luan noi bat
    chi la "On exam March 2023", "On the test Nov, 12 2021"... Nhung nguoi thi roi
    upvote nhau nen chung len top, trong khi dap an that nam o binh luan it vote
    hon. Hien thi chung se lam loang thong tin huu ich.
    """
    t = (text or "").strip()
    if not t:
        return True
    return bool(_RE_NOISE_COMMENT.match(t))

def _detect_question_type(text, options):
    """Doan loai cau hoi de exporter khong hien "options rong" vo nghia.

    Do tren du lieu that: 140/382 ban ghi ms-700 khong co lua chon A/B/C/D, va
    hau het la HOTSPOT / DRAG DROP (de bai co "Hot Area", "drag", "select the
    appropriate..."). Truoc day chung chi co `options: []` im lang -> nguoi doc
    tuong tool loi, trong khi that ra dang cau khong co dap an A/B/C/D.
    """
    if options:
        return "multiple-choice"
    t = (text or "").lower()
    if "hot area" in t or "hotspot" in t:
        return "hotspot"
    if "drag" in t or "drop" in t:
        return "drag-drop"
    if "select the appropriate" in t or "answer area" in t:
        return "selection"
    return "unknown"


def _clean_community_votes(raw):
    """Chuan hoa danh sach phieu cong dong lay tu badge binh luan.

    Moi muc la `{letter: 'A', weight: N}` — phieu cho mot lua chon, `weight` la
    so upvote cua binh luan mang phieu do. Du lieu rac (thieu letter, weight am,
    khong phai dict) bi bo qua thay vi lam hong ca ban ghi.

    Thay the `.voted-answers-tally` da chet (do tren trang that: 0 lan xuat
    hien). Truoc day truong nay luon la [] nen exporter khong co gi de hien.
    """
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        letter = str(item.get("letter") or "").strip().upper()
        letter = "".join(c for c in letter if c.isalpha())
        if not letter:
            continue
        try:
            weight = int(item.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        cleaned.append({"letter": letter, "weight": max(0, weight)})
    return cleaned


def _clean_top_comments(raw):
    """Chuan hoa danh sach binh luan noi bat lay tu trang discussion.

    Moi muc: {text, votes, user, badge}. Sap xep theo so luot upvote that va giu
    toi da 5 muc. Du lieu rac bi bo qua thay vi lam hong ca ban ghi.

    Day la du lieu CONG DONG (khong phai dap an chinh thuc), nen chi de hien thi
    cho nguoi doc tu danh gia -- dac biet voi cau HOTSPOT/DRAG DROP khong co dap
    an A/B/C/D. Tool KHONG tu suy ra dap an tu day.
    """
    if not isinstance(raw, list):
        return []
    cleaned = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if _is_noise_comment(text):
            continue
        key = text[:120]
        if key in seen:
            continue
        seen.add(key)
        try:
            votes = int(item.get("votes") or 0)
        except (TypeError, ValueError):
            votes = 0
        cleaned.append({
            "text": text,
            "votes": max(0, votes),
            "user": str(item.get("user") or "").strip(),
            "badge": str(item.get("badge") or "").strip(),
        })
    cleaned.sort(key=lambda c: -c["votes"])
    return cleaned[:5]

def crawl_one_question(page, exam_code, topic, qnum):
    """Crawl mot cau hoi, tai su dung `page` (va session/cookie) dung chung.

    `page` la trang DuckDuckGo da duoc warm-up tu truoc va giu xuyen suot phien.
    Khong tao context moi moi cau -> cookie/session duoc giu, trong giong
    mot nguoi dung quay lai thay vi khach la moi vai giay.
    """
    new_tab = None
    query = f"exam {exam_code} topic {topic} question {qnum} discussion"
    LOG.info(f"\n[Search] {query}")

    try:
        # Dam bao dau moi cau chi con 1 tab DDG (don tab cu/popup neu con sot).
        close_extra_tabs(page)

        # 1+2. Tim link discussion khop cau: DuckDuckGo truoc, khong thay -> Google.
        #      Chi nhan link khop CHINH XAC exam_code + topic + qnum de khong lay
        #      nham cau khac/ma de khac/trang tong hop.
        href = find_discussion_link(page, exam_code, topic, qnum)
        if href is NO_DISCUSSION_BLOCKED:
            LOG.info(f"  Bo qua cau {qnum}: search bi chan/CAPTCHA hoac khong truy cap duoc, khong retry.")
            return NO_DISCUSSION_BLOCKED
        if href is NO_DISCUSSION_MISSING:
            LOG.info(f"  Bo qua cau {qnum}: ca DuckDuckGo va Google da search nhung khong co link dung cau, khong retry.")
            return NO_DISCUSSION_MISSING
        LOG.info(f"  Tim thay: {href}")

        # 3. Mo tab va nap noi dung. Uu tien nap tuc thi qua HTTP (1s thay vi cho 15s quang cao),
        #    chi fallback sang dieu huong browser khi loi la TAM THOI (429/503/loi mang).
        LOG.info("  Dang mo tab va nap noi dung...")
        try:
            new_tab = page.context.new_page()
        except Exception as e:
            LOG.warning(f"  Loi mo tab: {e}")
            new_tab = None

        loaded = False
        http_status = None
        if new_tab:
            # Search engines may return a stale discussion slug even though the
            # same category/id/topic/question is live under the current exam
            # slug. Try only those constrained alternatives before classifying
            # a 404 as gated/paywalled.
            candidates = resolver.discussion_url_variants(href, exam_code)
            for candidate in candidates:
                if candidate != href:
                    LOG.info(f"  Thu lai slug discussion: {candidate}")
                loaded, http_status = load_discussion_via_http_status(new_tab, candidate)
                if loaded or http_status != 404:
                    href = candidate
                    break
            if loaded:
                LOG.info("  Da nap noi dung tuc thi qua HTTP (~1s)")
            elif http_status == 404:
                # 404: KHONG mo browser. Mo browser cho link nay chi tao
                # `Page.goto: ERR_HTTP_RESPONSE_CODE_FAILURE` roi treo ~15s ->
                # dung hien tuong "mo link blank va cho" nguoi dung bao.
                #
                # Nhung KHONG ket luan "cau bi go vinh vien": do tren trang that,
                # 404 doi khi chi la chan tam (q32 hqt-4180, 29 cau ccdak tra 404
                # luc tai cao roi 200 khi tai giam). Vi vay mark_url_dead chi giu
                # cooldown NGAN (60s) de second pass cuoi phien con thu lai duoc.
                LOG.info("  HTTP 404: link khong ton tai ngay luc nay "
                         "(co the bi go/paywall, hoac chan tam - second pass se thu lai).")
                forget_harvested_link(exam_code, topic, qnum)
                try:
                    resolver.mark_url_dead(href, exam_code, topic, qnum)
                except Exception:
                    pass
                return NO_DISCUSSION_GATED
            else:
                LOG.info("  HTTP load khong thanh cong, thu dieu huong truc tiep trong browser...")
                if safe_goto(new_tab, href, timeout=15000):
                    loaded = wait_for_discussion(new_tab, timeout=15000)

        if not new_tab:
            LOG.warning("  Khong mo duoc tab discussion")
            return None
        if not loaded:
            # Chi con cac truong hop TAM THOI o day: 429/503 (dang bi chan), loi
            # ket noi, hoac dieu huong browser that bai. 404 da duoc xu ly rieng
            # phia tren (tra NO_DISCUSSION_GATED) nen KHONG duoc danh dau chet o
            # day — danh dau chet mot link 429 se lam tool bo qua mot cau that
            # su ton tai cho den het cooldown.
            LOG.info("  Van khong tai duoc noi dung discussion, thu boc du lieu du co...")
            time.sleep(1)

        # Truoc day cho nay con 2 buoc da CHET (da xoa):
        #  - thu hoach "anchor" question_id tu `.question-body[data-id]`: gia tri
        #    nay tu 9/2026 la HANG SO 825909 cho moi cau/moi de -> vo dung.
        #  - `load_full_comments` goi AJAX `/ajax/discussion/load-complete/`:
        #    endpoint nay tra 404 voi moi id (da kiem chung). Trang discussion gio
        #    render du binh luan inline, khong con nut "Load full discussion...".

        # 4 & 5. Xoa overlay va boc tach toan bo noi dung trong 1 lan evaluate duy nhat
        LOG.info("  Dang lay noi dung...")
        extracted_data = {}
        try:
            extracted_data = new_tab.evaluate(r"""
                () => {
                    // Xoa overlay neu co
                    const styles = document.querySelectorAll('style');
                    for (let st of styles) {
                        if (st.innerHTML && st.innerHTML.includes('.popup-overlay')) {
                            st.remove();
                        }
                    }
                    const popup = document.querySelector('.popup-overlay');
                    if (popup) popup.remove();

                    const container = document.querySelector('.discussion-header-container');
                    let questionText = '';
                    let questionImages = [];
                    if (container) {
                        const qP = container.querySelector('.question-body .card-text');
                        if (qP) {
                            questionText = qP.innerText.trim();
                        } else {
                            const qBody = container.querySelector('.question-body');
                            questionText = qBody ? qBody.innerText.trim() : container.innerText.trim();
                        }
                        const scope = container.querySelector('.question-body') || container;
                        const imgs = Array.from(scope.querySelectorAll('img'));
                        const urls = imgs.map(im =>
                            im.getAttribute('data-src')
                            || im.getAttribute('data-original')
                            || im.src
                            || '').filter(u => u);
                        questionImages = urls.filter((u, i) => u && urls.indexOf(u) === i);
                    }

                    const items = document.querySelectorAll('.question-choices-container .multi-choice-item');
                    const options = Array.from(items).map(li => {
                        const letterEl = li.querySelector('.multi-choice-letter');
                        const letter = letterEl
                            ? (letterEl.getAttribute('data-choice-letter')
                               || letterEl.innerText.replace(/\.$/, '').trim())
                            : '';
                        let text = li.innerText.trim();
                        if (letterEl) {
                            text = text.replace(letterEl.innerText, '').trim();
                        }
                        const imgs = Array.from(li.querySelectorAll('img')).map(im =>
                            im.getAttribute('data-src')
                            || im.getAttribute('data-original')
                            || im.src
                            || '').filter(u => u);
                        // Marker lua chon DUNG: `correct-hidden` (cu) da chet tren
                        // trang discussion (0 lan xuat hien), nhung tren TRANG EXAM
                        // thi marker dang song la thuoc tinh `data-correct<qid>`
                        // (vd `data-correct862259`) va class `correct-choice`.
                        // Nhan CA HAI de khong phu thuoc vao mot marker duy nhat.
                        const hasAttr = Array.from(li.attributes)
                            .some(a => a.name.toLowerCase().startsWith('data-correct'));
                        return {
                            letter: letter,
                            text: text,
                            images: imgs,
                            is_correct: hasAttr
                                || li.classList.contains('correct-hidden')
                                || li.classList.contains('correct-choice')
                        };
                    });

                    const comments = Array.from(document.querySelectorAll('.comment-content'))
                        .map(c => c.innerText.trim())
                        .filter(u => u);

                    // Binh luan noi bat: ExamTopics hien so luot upvote that
                    // (`.upvote-count`) va badge "Highly Voted" do cong dong binh
                    // chon. Day la tin hieu KHACH QUAN, khong phai suy doan cua
                    // tool -> dung de hien thi cho nguoi doc tu danh gia, dac biet
                    // voi cau HOTSPOT/DRAG DROP khong co dap an A/B/C/D.
                    let topComments = [];
                    try {
                        const seen = new Set();
                        topComments = Array.from(document.querySelectorAll('.media.comment-container'))
                            .map(box => {
                                const contentEl = box.querySelector('.comment-content');
                                const text = contentEl ? contentEl.innerText.trim() : '';
                                if (!text) return null;
                                const voteEl = box.querySelector('.upvote-count');
                                const badgeEl = box.querySelector('.comment-head .badge');
                                const userEl = box.querySelector('.comment-username');
                                return {
                                    text: text,
                                    votes: voteEl ? parseInt(voteEl.innerText, 10) || 0 : 0,
                                    user: userEl ? userEl.innerText.trim() : '',
                                    badge: badgeEl ? badgeEl.innerText.trim() : ''
                                };
                            })
                            .filter(c => {
                                if (!c) return false;
                                // Bo trung lap (trang co the lap lai comment sau khi load-complete).
                                const k = c.user + '|' + c.text.slice(0, 80);
                                if (seen.has(k)) return false;
                                seen.add(k);
                                return true;
                            })
                            .sort((a, b) => b.votes - a.votes)
                            .slice(0, 5);
                    } catch (e) {}

                    let communityVotes = [];
                    let communityMostVoted = [];
                    // Nguon tin hieu CONG DONG duy nhat con song (9/2026).
                    //
                    // `.voted-answers-tally` va `.most-voted-answer-badge` deu da
                    // bien mat (do tren trang that: 0 lan xuat hien) -> ban cu luon
                    // tra ve [] (do duoc: 0/45 va 0/417 ban ghi co du lieu nay).
                    //
                    // Cach thay the: moi binh luan co the mang badge
                    //   Selected Answer: <span><strong>ABC</strong></span>
                    // va so upvote rieng (`.upvote-count`). Cong DON theo upvote
                    // thay vi dem so binh luan, vi nguoi thi roi upvote nhau nen
                    // binh luan it nguoi nhung dung van co the it upvote hon.
                    try {
                        const blocks = document.querySelectorAll('.media.comment-container');
                        for (const box of blocks) {
                            const badgeEl = box.querySelector('.badge');
                            const answerEl = badgeEl ? badgeEl.querySelector('strong') : null;
                            const answerText = answerEl ? answerEl.innerText.trim() : '';
                            if (!answerText) continue;
                            const voteEl = box.querySelector('.upvote-count');
                            let weight = voteEl ? parseInt(voteEl.innerText, 10) : 0;
                            if (!(weight > 0)) weight = 1; // khong ro so upvote -> dem 1
                            for (const letter of answerText.toUpperCase().replace(/[^A-F]/g, '')) {
                                communityVotes.push({ letter: letter, weight: weight });
                            }
                        }
                    } catch (e) {}

                    if (communityVotes.length) {
                        const totals = {};
                        for (const v of communityVotes) {
                            totals[v.letter] = (totals[v.letter] || 0) + v.weight;
                        }
                        const best = Math.max.apply(null, Object.keys(totals).map(k => totals[k]));
                        // Chi ket luan khi co it nhat 2 luot upvote: 1 binh luan le
                        // khong du tin cay de goi la "y kien cong dong".
                        if (best >= 2) {
                            communityMostVoted = Object.keys(totals)
                                .filter(k => totals[k] === best)
                                .sort();
                        }
                    }

                    return {
                        question: questionText,
                        question_images: questionImages,
                        options: options,
                        community_most_voted: communityMostVoted,
                        community_votes: communityVotes,
                        answers: comments,
                        top_comments: topComments
                    };
                }
            """)
        except Exception as e:
            LOG.warning(f"  Loi lay noi dung: {e}")
            extracted_data = {}

        if not isinstance(extracted_data, dict):
            extracted_data = {}

        question = extracted_data.get("question", "") or ""
        question_images = extracted_data.get("question_images") or []
        options = extracted_data.get("options") or []
        answers = extracted_data.get("answers") or []

        try:
            url = new_tab.url
            if not url or url == "about:blank" or "examtopics.com" not in url.lower():
                url = href
        except Exception:
            url = href

        if not question:
            LOG.warning(f"  Khong lay duoc cau hoi cho cau {qnum}")
            return None

        clean_q = question
        clean_ans = [a for a in answers if a]
        # Anh phai duoc tuyet doi hoa truoc khi luu: duong HTTP-first bom HTML vao
        # about:blank nen URL anh con nguyen dang tuong doi (/assets/...) va se bi
        # exporter loai bo -> mat anh. Xem `_absolutize_images`.
        clean_q_images = _absolutize_images(question_images, href)
        clean_options = []
        suggested_answers = []
        for opt in options:
            if not isinstance(opt, dict):
                continue
            letter = opt.get("letter", "") or ""
            text = opt.get("text", "") or ""
            is_correct = bool(opt.get("is_correct"))
            opt_images = _absolutize_images(opt.get("images"), href)
            clean_options.append({
                "letter": letter,
                "text": text,
                "images": opt_images,
                "is_correct": is_correct,
            })
            # Cau "Choose two/three" co nhieu dap an dung -> gom tat ca lai.
            if is_correct and letter:
                suggested_answers.append(letter)

        # Duong du phong khi trang khong con markup lua chon: tach tu text de bai.
        if not clean_options:
            stem, split_opts = _split_options_from_text(clean_q)
            if split_opts:
                clean_q = stem
                clean_options = split_opts

        # Dap an CHINH THUC tu trang exam (chi q1..q10 mien phi) la nguon dang tin
        # nhat; uu tien hon `suggested_answers` (von dua vao marker lua chon dung
        # tren trang discussion -- nay khong con, xem comment trong evaluate).
        # Danh dau luon lua chon dung de exporter hien dung.
        official = (resolver.ANSWER_KEY.get(canonical_exam_code(exam_code)) or {}).get(qnum)
        if official:
            letters = [c for c in official.upper() if c.isalpha()]
            suggested_answers = letters
            for opt in clean_options:
                opt["is_correct"] = opt.get("letter") in letters

        raw_most_voted = [str(x).strip() for x in (extracted_data.get("community_most_voted") or []) if str(x).strip()]
        clean_community_most_voted = list(dict.fromkeys(raw_most_voted))
        community_votes = _clean_community_votes(extracted_data.get("community_votes"))
        top_comments = _clean_top_comments(extracted_data.get("top_comments"))

        LOG.info(f"  Cau hoi: {clean_q[:100]}...")
        if clean_q_images:
            LOG.info(f"  So hinh trong de bai: {len(clean_q_images)}")
        info_str = f"  So lua chon: {len(clean_options)}"
        if suggested_answers:
            info_str += f" (dap an goi y: {', '.join(suggested_answers)})"
        if clean_community_most_voted:
            info_str += f" [Cong dong: {', '.join(clean_community_most_voted)}]"
        LOG.info(info_str)
        LOG.info(f"  So binh luan: {len(clean_ans)}")

        return {
            "exam_code": exam_code,
            "topic": topic,
            "question_num": qnum,
            "question": clean_q,
            "question_images": clean_q_images,
            "options": clean_options,
            "question_type": _detect_question_type(clean_q, clean_options),
            "suggested_answers": suggested_answers,
            "community_most_voted": clean_community_most_voted,
            "community_votes": community_votes,
            "answers": clean_ans,
            "top_comments": top_comments,
            "url": url
        }
    except Exception as e:
        LOG.warning(f"  Loi: {e}")
        return None
    finally:
        # Sau moi cau: dong het tab tru tab DuckDuckGo chinh (`page`).
        # Gom tab discussion vua mo + moi popup quang cao examtopics sinh ra,
        # de context luon chi con dung 1 tab, khong tich tu lam nang trinh duyet.
        # Page/context DDG duoc giu song xuyen suot phien de tai su dung
        # session/cookie.
        close_extra_tabs(page)
