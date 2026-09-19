import time
import random
import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .config import (
    DEFAULT_OP_TIMEOUT,
    SEARCH_ENGINES,
    SEARCH_OK,
    SEARCH_EMPTY,
    SEARCH_BLOCKED,
    SEARCH_ERROR,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    _BLOCK_SELECTORS,
    _BLOCK_TEXT,
    _IMG_HEADERS,
    _SESSION_COOKIES,
    _HARVESTED_LINKS,
    _PROXY,
    _RE_SCRIPT,
    _RE_IFRAME,
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
    global _IMG_HEADERS, _SESSION_COOKIES
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
        print(f"    Loi dieu huong: {e}")
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

def search_engine(page, query, engine="duckduckgo"):
    """Go query vao o tim kiem va tra ve trang thai search.

    Moi lan deu quay ve trang chu engine truoc roi moi go vao o tim kiem, nen
    o luon sach (tranh query bi noi chong), dong thoi van giu cookie/session vi
    context duoc tai su dung xuyen suot phien.
    Tra ve `SEARCH_OK` khi co ket qua hien thi, `SEARCH_EMPTY` khi search binh
    thuong nhung khong co ket qua, `SEARCH_BLOCKED` khi CAPTCHA/challenge, va
    `SEARCH_ERROR` khi khong thao tac duoc trang.
    """
    cfg = SEARCH_ENGINES.get(engine)
    if not cfg:
        print(f"  Engine khong ho tro: {engine}")
        return SEARCH_ERROR

    # Luon ve trang chu de co o tim kiem trong, sach.
    if not safe_goto(page, cfg["home"]):
        print(f"  Khong tai duoc {engine}")
        return SEARCH_BLOCKED
    if _search_is_blocked(page):
        print(f"  {engine} dang hien CAPTCHA/challenge")
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
        print(f"  Khong tim thay o tim kiem {engine}")
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
        print(f"  Loi go query: {e}")
        return SEARCH_ERROR

    # Cho ket qua hien. Ket qua render bat dong bo SAU khi domcontentloaded
    # da fire, nen phai doi tan element ket qua xuat hien, khong sleep cung.
    got_results = False
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
    time.sleep(random.uniform(0.8, 1.5))
    if _search_is_blocked(page):
        print(f"  {engine} bi chan/CAPTCHA sau khi search")
        return SEARCH_BLOCKED
    return SEARCH_OK if got_results else SEARCH_EMPTY

def find_discussion_link(page, exam_code, topic, qnum):
    """Tim URL discussion khop cau hoi. Thu cache truoc, roi DuckDuckGo -> Google.

    Them 'site:examtopics.com' de thu hep ket qua chi trong examtopics, tang
    do chinh xac va recall. Google chi dung khi DDG khong ra ket qua dung cau.
    """
    target_key = (canonical_exam_code(exam_code), int(topic), int(qnum))
    if target_key in _HARVESTED_LINKS:
        cached_url = _HARVESTED_LINKS[target_key]
        print(f"  [Bo nho cache] Dung link discussion da thu thap: {cached_url}")
        return cached_url

    query = (f"exam {exam_code} topic {topic} question {qnum} "
             f"discussion site:examtopics.com")

    # 1. DuckDuckGo (engine chinh, it CAPTCHA)
    ddg_status = search_engine(page, query, "duckduckgo")
    if ddg_status == SEARCH_OK:
        href = extract_matching_link(page, exam_code, topic, qnum)
        if href:
            return href
    if ddg_status == SEARCH_BLOCKED:
        print("  DuckDuckGo bi chan/CAPTCHA, thu Google...")
    elif ddg_status == SEARCH_EMPTY:
        print("  DuckDuckGo khong tra ve ket qua nao, thu Google...")
    else:
        print("  DuckDuckGo khong co link dung cau, thu Google...")

    # 2. Google (fallback)
    google_status = search_engine(page, query, "google")
    if google_status == SEARCH_OK:
        href = extract_matching_link(page, exam_code, topic, qnum)
        if href:
            return href
    return no_link_result(ddg_status, google_status)

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

def load_discussion_via_http(tab, href, timeout=20):
    """Fallback: tai HTML discussion bang HTTP thuan roi nap vao tab.

    Trang discussion cua examtopics duoc render san tu server (curl/httpx lay
    duoc trong ~1s), nhung mo bang browser doi khi treo vo han vi tracker/ads.
    Ta tai HTML bang httpx, XOA cac the <script>/<iframe> (quang cao/tracker,
    khong can vi noi dung la HTML tinh render san), roi bom vao tab bang
    document.write de nap tuc thi ma KHONG cho tai nguyen ngoai.
    Tra ve True neu nap duoc noi dung discussion, False neu that bai.
    """
    ua = _IMG_HEADERS.get("User-Agent") or ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    cookies = _SESSION_COOKIES or None
    try:
        resp = httpx.get(href, headers={"User-Agent": ua}, cookies=cookies, proxy=_PROXY, timeout=timeout,
                         follow_redirects=True)
        if resp.status_code != 200 or not resp.text:
            print(f"    HTTP fallback tra ve ma HTTP {resp.status_code}")
            return False
        html_text = resp.text
    except httpx.RequestError as e:
        print(f"    Loi ket noi HTTP fallback: {e}")
        return False
    except Exception as e:
        print(f"    Loi ngoai le HTTP fallback: {e}")
        return False
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
        print(f"    Loi nap HTML vao tab: {e}")
        return False
    return tab.query_selector('.discussion-header-container') is not None

def crawl_one_question(page, exam_code, topic, qnum):
    """Crawl mot cau hoi, tai su dung `page` (va session/cookie) dung chung.

    `page` la trang DuckDuckGo da duoc warm-up tu truoc va giu xuyen suot phien.
    Khong tao context moi moi cau -> cookie/session duoc giu, trong giong
    mot nguoi dung quay lai thay vi khach la moi vai giay.
    """
    new_tab = None
    query = f"exam {exam_code} topic {topic} question {qnum} discussion"
    print(f"\n[Search] {query}")

    try:
        # Dam bao dau moi cau chi con 1 tab DDG (don tab cu/popup neu con sot).
        close_extra_tabs(page)

        # 1+2. Tim link discussion khop cau: DuckDuckGo truoc, khong thay -> Google.
        #      Chi nhan link khop CHINH XAC exam_code + topic + qnum de khong lay
        #      nham cau khac/ma de khac/trang tong hop.
        href = find_discussion_link(page, exam_code, topic, qnum)
        if href is NO_DISCUSSION_BLOCKED:
            print(f"  Bo qua cau {qnum}: search bi chan/CAPTCHA hoac khong truy cap duoc, khong retry.")
            return NO_DISCUSSION_BLOCKED
        if href is NO_DISCUSSION_MISSING:
            print(f"  Bo qua cau {qnum}: ca DuckDuckGo va Google da search nhung khong co link dung cau, khong retry.")
            return NO_DISCUSSION_MISSING
        print(f"  Tim thay: {href}")

        # 3. Mo tab va nap noi dung. Uu tien nap tuc thi qua HTTP (1s thay vi cho 15s quang cao),
        #    neu loi thi tu dong fallback sang dieu huong browser thong thuong.
        print("  Dang mo tab va nap noi dung...")
        try:
            new_tab = page.context.new_page()
        except Exception as e:
            print(f"  Loi mo tab: {e}")
            new_tab = None

        loaded = False
        if new_tab:
            loaded = load_discussion_via_http(new_tab, href)
            if loaded:
                print("  Da nap noi dung tuc thi qua HTTP (~1s)")
            else:
                print("  HTTP load khong thanh cong, thu dieu huong truc tiep trong browser...")
                if safe_goto(new_tab, href, timeout=15000):
                    loaded = wait_for_discussion(new_tab, timeout=15000)

        if not new_tab:
            print("  Khong mo duoc tab discussion")
            return None
        if not loaded:
            print("  Van khong tai duoc noi dung discussion, thu boc du lieu du co...")
        time.sleep(1)

        # 4 & 5. Xoa overlay va boc tach toan bo noi dung trong 1 lan evaluate duy nhat
        print("  Dang lay noi dung...")
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
                        return {
                            letter: letter,
                            text: text,
                            images: imgs,
                            is_correct: li.classList.contains('correct-hidden')
                        };
                    });

                    const comments = Array.from(document.querySelectorAll('.comment-content'))
                        .map(c => c.innerText.trim())
                        .filter(u => u);

                    let communityVotes = [];
                    let communityMostVoted = [];
                    try {
                        const tallyScript = document.querySelector('.voted-answers-tally script[type="application/json"]');
                        if (tallyScript && tallyScript.innerText) {
                            const parsedVotes = JSON.parse(tallyScript.innerText);
                            if (Array.isArray(parsedVotes)) {
                                communityVotes = parsedVotes;
                                for (let v of parsedVotes) {
                                    if (v && v.is_most_voted && v.voted_answers) {
                                        const letters = String(v.voted_answers).split(/[, \s]+/).filter(x => x);
                                        communityMostVoted.push(...letters);
                                    }
                                }
                            }
                        }
                    } catch (e) {}

                    if (communityMostVoted.length === 0) {
                        try {
                            const mostVotedBadges = document.querySelectorAll('.most-voted-answer-badge');
                            for (let badge of mostVotedBadges) {
                                const item = badge.closest('.multi-choice-item');
                                if (item) {
                                    const letterEl = item.querySelector('.multi-choice-letter');
                                    if (letterEl) {
                                        const l = letterEl.getAttribute('data-choice-letter') || letterEl.innerText.replace(/\.$/, '').trim();
                                        if (l && !communityMostVoted.includes(l)) {
                                            communityMostVoted.push(l);
                                        }
                                    }
                                }
                            }
                        } catch (e) {}
                    }

                    return {
                        question: questionText,
                        question_images: questionImages,
                        options: options,
                        community_most_voted: communityMostVoted,
                        community_votes: communityVotes,
                        answers: comments
                    };
                }
            """)
        except Exception as e:
            print(f"  Loi lay noi dung: {e}")
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
            print(f"  Khong lay duoc cau hoi cho cau {qnum}")
            return None

        clean_q = question
        clean_ans = [a for a in answers if a]
        clean_q_images = [u for u in question_images if isinstance(u, str) and u]
        clean_options = []
        suggested_answers = []
        for opt in options:
            if not isinstance(opt, dict):
                continue
            letter = opt.get("letter", "") or ""
            text = opt.get("text", "") or ""
            is_correct = bool(opt.get("is_correct"))
            opt_imgs_raw = opt.get("images") or []
            opt_images = [u for u in opt_imgs_raw if isinstance(u, str) and u]
            clean_options.append({
                "letter": letter,
                "text": text,
                "images": opt_images,
                "is_correct": is_correct,
            })
            # Cau "Choose two/three" co nhieu dap an dung -> gom tat ca lai.
            if is_correct and letter:
                suggested_answers.append(letter)

        raw_most_voted = [str(x).strip() for x in (extracted_data.get("community_most_voted") or []) if str(x).strip()]
        clean_community_most_voted = list(dict.fromkeys(raw_most_voted))
        community_votes = extracted_data.get("community_votes") or []

        print(f"  Cau hoi: {clean_q[:100]}...")
        if clean_q_images:
            print(f"  So hinh trong de bai: {len(clean_q_images)}")
        info_str = f"  So lua chon: {len(clean_options)}"
        if suggested_answers:
            info_str += f" (dap an goi y: {', '.join(suggested_answers)})"
        if clean_community_most_voted:
            info_str += f" [Cong dong: {', '.join(clean_community_most_voted)}]"
        print(info_str)
        print(f"  So binh luan: {len(clean_ans)}")

        return {
            "exam_code": exam_code,
            "topic": topic,
            "question_num": qnum,
            "question": clean_q,
            "question_images": clean_q_images,
            "options": clean_options,
            "suggested_answers": suggested_answers,
            "community_most_voted": clean_community_most_voted,
            "community_votes": community_votes,
            "answers": clean_ans,
            "url": url
        }
    except Exception as e:
        print(f"  Loi: {e}")
        return None
    finally:
        # Sau moi cau: dong het tab tru tab DuckDuckGo chinh (`page`).
        # Gom tab discussion vua mo + moi popup quang cao examtopics sinh ra,
        # de context luon chi con dung 1 tab, khong tich tu lam nang trinh duyet.
        # Page/context DDG duoc giu song xuyen suot phien de tai su dung
        # session/cookie.
        close_extra_tabs(page)
