import time
import json
import os
import re
import random
from cloakbrowser import launch

try:
    # cloakbrowser chay tren Playwright nen TimeoutError luon co san.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except Exception:  # fallback neu backend thay doi
    class PlaywrightTimeoutError(Exception):
        pass

# Nghi ngau nhien giua cac cau (giay) de tranh nhip deu de bi chan.
# DuckDuckGo khoan dung hon Google nhieu nen co the de thap.
MIN_DELAY = 2
MAX_DELAY = 5
RETRY_LIMIT = 3
OUTPUT_DIR = "output"

# Timeout mac dinh (ms) cho cac thao tac Playwright de tranh treo vo han.
DEFAULT_OP_TIMEOUT = 30000

def safe_encode(text):
    if not isinstance(text, str):
        return text
    try:
        return text.encode('utf-8', errors='ignore').decode('utf-8')
    except Exception:
        result = []
        for ch in text:
            try:
                ch.encode('utf-8')
                result.append(ch)
            except Exception:
                continue
        return ''.join(result)

def clean_exam_code(code):
    return re.sub(r'[^a-zA-Z0-9]', '', code).lower()

def normalize_exam_code(code):
    """Chuan hoa ma de cho tim kiem.

    Giu lai chu cai, chu so va dau gach noi (vd: 'SK0-005' -> 'sk0-005')
    de query dung dung dinh dang ma de that, khong bi mat dau gach nhu
    clean_exam_code (ham do chi dung de dat ten file an toan).
    """
    code = code.strip().lower()
    code = re.sub(r'\s+', '-', code)        # khoang trang -> gach noi
    code = re.sub(r'[^a-z0-9-]', '', code)  # bo ky tu la, giu chu/so/gach
    code = re.sub(r'-+', '-', code).strip('-')
    return code

def link_matches_question(href, exam_code, topic, qnum):
    """Kiem tra link discussion co dung cau hoi dang can hay khong.

    examtopics dung slug dang:
        .../view/61482-exam-sk0-005-topic-1-question-1-discussion/
    Ta yeu cau khop chinh xac exam_code + topic + qnum de khong lay nham
    cau khac, ma de khac (vd xk0-005), hay trang tong hop nhieu cau.
    Phan '-discussion' ngay sau qnum chong viec question-2 khop nham question-20.
    """
    if not href or 'examtopics.com/discussions' not in href:
        return False
    pattern = rf'exam-{re.escape(exam_code)}-topic-{topic}-question-{qnum}-discussion'
    return re.search(pattern, href.lower()) is not None

def clean_data(data):
    if isinstance(data, dict):
        return {k: clean_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_data(v) for v in data]
    elif isinstance(data, str):
        return safe_encode(data)
    else:
        return data

def safe_close(obj):
    """Dong an toan mot page/context/tab/browser, nuot loi dong khong quan trong."""
    if obj is None:
        return
    try:
        obj.close()
    except Exception:
        pass

def save_progress(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    try:
        cleaned = clean_data(data)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"  Loi JSON: {e}, thu fallback...")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
            return True
        except Exception as e2:
            print(f"  Fallback JSON that bai: {e2}")
            return False

def wait_for_page_load(page, timeout=DEFAULT_OP_TIMEOUT):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        return True
    except PlaywrightTimeoutError:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            return True
        except PlaywrightTimeoutError:
            return False
        except Exception as e:
            print(f"    Loi cho load (domcontentloaded): {e}")
            return False
    except Exception as e:
        print(f"    Loi cho load (networkidle): {e}")
        return False

def safe_goto(page, url, timeout=60000):
    try:
        page.goto(url, wait_until="commit", timeout=timeout)
        time.sleep(1)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        except Exception as e:
            print(f"    Loi cho networkidle: {e}")
        return True
    except Exception as e:
        print(f"    Loi dieu huong: {e}")
        return False

SEARCH_HOME = "https://duckduckgo.com/"
SEARCH_BOX_SELECTORS = ('input[name="q"]', 'input#searchbox_input', 'textarea[name="q"]')

def warmup_search(page):
    """Ghe trang chu DuckDuckGo mot lan dau de tao cookie/session.

    DuckDuckGo khoan dung voi truy van tu dong hon Google rat nhieu (it
    CAPTCHA), nen ta dung DDG de tra URL discussion. Chi goi mot lan khi
    bat dau phien. DDG khong co man hinh consent nen warm-up don gian.
    """
    if not safe_goto(page, SEARCH_HOME):
        return False
    time.sleep(random.uniform(1.0, 2.0))
    return True

def search_duckduckgo(page, query):
    """Go query vao o tim kiem DuckDuckGo nhu nguoi dung that.

    Moi cau deu quay ve trang chu DDG truoc roi moi go vao o tim kiem. Lam vay
    o tim kiem luon sach (tranh loi query bi noi chong), dong thoi van giu
    cookie/session vi context duoc tai su dung xuyen suot phien.
    Tra ve True neu search thanh cong, False neu that bai.
    """
    # Luon ve trang chu DDG de co o tim kiem trong, sach.
    if not safe_goto(page, SEARCH_HOME):
        print("  Khong tai duoc duckduckgo.com")
        return False
    time.sleep(random.uniform(0.5, 1.0))

    # Tim o input tren trang DDG.
    search_box = None
    for sel in SEARCH_BOX_SELECTORS:
        try:
            search_box = page.query_selector(sel)
            if search_box:
                break
        except Exception:
            continue
    if not search_box:
        print("  Khong tim thay o tim kiem DuckDuckGo")
        return False

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
            # Them nghi ngoi nho sau moi vai ky tu
            if random.random() < 0.10:
                time.sleep(random.uniform(0.1, 0.25))
        time.sleep(random.uniform(0.3, 0.7))
        page.keyboard.press("Enter")
    except Exception as e:
        print(f"  Loi go query: {e}")
        return False

    # Cho ket qua hien. DDG render ket qua bat dong bo SAU khi domcontentloaded
    # da fire, nen phai doi tan element ket qua xuat hien, khong sleep cung.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_OP_TIMEOUT)
    except PlaywrightTimeoutError:
        pass
    # Doi vung ket qua thuc su co link (uu tien element ket qua cua DDG).
    result_selectors = (
        '[data-testid="result"]',
        'a[data-testid="result-title-a"]',
        'article',
        'a[href*="examtopics.com"]',
    )
    for sel in result_selectors:
        try:
            page.wait_for_selector(sel, timeout=8000)
            break
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    time.sleep(random.uniform(0.8, 1.5))
    return True

def crawl_one_question(page, exam_code, topic, qnum):
    """Crawl mot cau hoi, tai su dung `page` (va session/cookie) dung chung.

    `page` la trang DuckDuckGo da duoc warm-up tu truoc va giu xuyen suot phien.
    Khong tao context moi moi cau -> cookie/session duoc giu, trong giong
    mot nguoi dung quay lai thay vi khach la moi vai giay.
    """
    new_tab = None
    query = f"exam {exam_code} topic {topic} question {qnum} discussion"
    print(f"\n[DuckDuckGo] {query}")

    try:
        # 1. Go query vao o tim kiem nhu nguoi that (khong goto thang URL)
        if not search_duckduckgo(page, query):
            print("  Khong search duoc tren DuckDuckGo")
            return None

        # 2. Tim link examtopics
        # Chi chap nhan link discussion khop CHINH XAC exam_code + topic + qnum.
        # Khong lay link dau tien chung chung, vi search engine hay day trang tong hop
        # ("Free Actual Q&As, Page 1" chua cau 1-10) hoac cau/ma de khac len dau,
        # khien du lieu bi gan sai nhan ma khong bao loi.
        try:
            links = page.query_selector_all('a[href*="examtopics.com/discussions"]')
        except Exception as e:
            print(f"  Loi liet ke link: {e}")
            links = []
        href = None
        for link in links:
            try:
                candidate = link.get_attribute('href')
            except Exception:
                candidate = None
            if link_matches_question(candidate, exam_code, topic, qnum):
                href = candidate
                break
        if not href:
            print(f"  Khong tim thay link examtopics dung cau {qnum} (bo qua link tong hop/cau khac)")
            return None
        print(f"  Tim thay: {href}")

        # 3. Mo tab moi
        print("  Dang mo tab moi...")
        try:
            with page.context.expect_page(timeout=DEFAULT_OP_TIMEOUT) as new_page_info:
                # json.dumps de chong vo JS khi href chua dau nhay don.
                page.evaluate(f"window.open({json.dumps(href)}, '_blank');")
            new_tab = new_page_info.value
        except PlaywrightTimeoutError:
            print("  Het thoi gian cho tab moi")
            return None
        except Exception as e:
            print(f"  Loi mo tab moi: {e}")
            return None
        if not new_tab:
            print("  Khong mo duoc tab moi")
            return None
        print("  Da mo tab moi")

        if not wait_for_page_load(new_tab, timeout=DEFAULT_OP_TIMEOUT):
            print("  Tab moi load cham, van tiep tuc...")
        time.sleep(1)

        # 4. Xoa overlay
        print("  Dang xoa overlay...")
        try:
            new_tab.evaluate("""
                (() => {
                    const styles = document.querySelectorAll('style');
                    for (let st of styles) {
                        if (st.innerHTML && st.innerHTML.includes('.popup-overlay')) {
                            st.remove();
                        }
                    }
                    const popup = document.querySelector('.popup-overlay');
                    if (popup) popup.remove();
                })();
            """)
            time.sleep(0.5)
            print("  Da xoa overlay")
        except Exception as e:
            print(f"  Loi xoa overlay: {e}")

        # 5. Lay cau hoi va binh luan
        print("  Dang lay noi dung...")
        try:
            question = new_tab.evaluate("""
                () => {
                    const container = document.querySelector('.discussion-header-container');
                    if (!container) return '';
                    const qP = container.querySelector('.question-body .card-text');
                    if (qP) return qP.innerText.trim();
                    const qBody = container.querySelector('.question-body');
                    return qBody ? qBody.innerText.trim() : '';
                }
            """)
        except Exception as e:
            print(f"  Loi lay cau hoi: {e}")
            question = ''
        if not question:
            try:
                question = new_tab.evaluate("""
                    () => {
                        const body = document.querySelector('.discussion-header-container');
                        return body ? body.innerText.trim() : '';
                    }
                """)
            except Exception as e:
                print(f"  Loi lay cau hoi (fallback): {e}")
                question = ''

        # Lay cac lua chon dap an (A/B/C/D...) tu .question-choices-container.
        # Moi item co .multi-choice-letter[data-choice-letter] cho chu cai,
        # phan text con lai la noi dung. Class 'correct-hidden' danh dau dap an
        # goi y dung tren examtopics.
        try:
            options = new_tab.evaluate("""
                () => {
                    const items = document.querySelectorAll(
                        '.question-choices-container .multi-choice-item');
                    return Array.from(items).map(li => {
                        const letterEl = li.querySelector('.multi-choice-letter');
                        const letter = letterEl
                            ? (letterEl.getAttribute('data-choice-letter')
                               || letterEl.innerText.replace(/\\.$/, '').trim())
                            : '';
                        let text = li.innerText.trim();
                        if (letterEl) {
                            // Bo phan "A." o dau de chi giu noi dung lua chon.
                            text = text.replace(letterEl.innerText, '').trim();
                        }
                        return {
                            letter: letter,
                            text: text,
                            is_correct: li.classList.contains('correct-hidden')
                        };
                    });
                }
            """)
        except Exception as e:
            print(f"  Loi lay lua chon: {e}")
            options = []
        if not isinstance(options, list):
            options = []

        try:
            answers = new_tab.evaluate("""
                () => {
                    const comments = document.querySelectorAll('.comment-content');
                    return Array.from(comments).map(c => c.innerText.trim());
                }
            """)
        except Exception as e:
            print(f"  Loi lay binh luan: {e}")
            answers = []
        if not isinstance(answers, list):
            answers = []

        try:
            url = new_tab.url
        except Exception:
            url = href

        if not question:
            print(f"  Khong lay duoc cau hoi cho cau {qnum}")
            return None

        clean_q = safe_encode(question)
        clean_ans = [safe_encode(a) for a in answers if a]
        clean_options = []
        suggested_answers = []
        for opt in options:
            if not isinstance(opt, dict):
                continue
            letter = safe_encode(opt.get("letter", "") or "")
            text = safe_encode(opt.get("text", "") or "")
            is_correct = bool(opt.get("is_correct"))
            clean_options.append({
                "letter": letter,
                "text": text,
                "is_correct": is_correct,
            })
            # Cau "Choose two/three" co nhieu dap an dung -> gom tat ca lai.
            if is_correct and letter:
                suggested_answers.append(letter)
        print(f"  Cau hoi: {clean_q[:100]}...")
        print(f"  So lua chon: {len(clean_options)}"
              + (f" (dap an goi y: {', '.join(suggested_answers)})" if suggested_answers else ""))
        print(f"  So binh luan: {len(clean_ans)}")

        return {
            "exam_code": exam_code,
            "topic": topic,
            "question_num": qnum,
            "question": clean_q,
            "options": clean_options,
            "suggested_answers": suggested_answers,
            "answers": clean_ans,
            "url": url
        }
    except Exception as e:
        print(f"  Loi: {e}")
        return None
    finally:
        # Chi dong tab discussion vua mo. Page/context DDG duoc giu song
        # xuyen suot phien de tai su dung session/cookie.
        safe_close(new_tab)

def parse_range(range_input):
    """Phan tich chuoi pham vi. Tra ve (start, end) hoac None neu khong hop le."""
    parts = [p.strip() for p in range_input.split('-')]
    try:
        if len(parts) == 2 and parts[0] and parts[1]:
            return int(parts[0]), int(parts[1])
        if len(parts) == 1 and parts[0]:
            v = int(parts[0])
            return v, v
    except ValueError:
        return None
    return None

def load_all(filepath):
    """Doc toan bo file cu mot cach ben vung. Luon tra ve list (rong neu loi/khong hop le)."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"  Khong doc duoc file cu ({e}), coi nhu chua co du lieu.")
        return []
    if not isinstance(data, list):
        print("  File cu khong phai danh sach hop le, coi nhu chua co du lieu.")
        return []
    return data

def upsert(all_data, record):
    """Them record moi, hoac ghi de neu da co cung (topic, question_num)."""
    key = (record.get("topic"), record.get("question_num"))
    for i, rec in enumerate(all_data):
        if isinstance(rec, dict) and (rec.get("topic"), rec.get("question_num")) == key:
            all_data[i] = record
            return
    all_data.append(record)

def main():
    print("="*60)
    print("  CRAWL EXAMTOPICS - BAN LUU LIEN TUC")
    print("="*60)

    exam_code = input("Nhap ma de (ex200, ex300): ").strip() or "ex200"
    # search_code giu nguyen dinh dang that (vd: sk0-005) de query chinh xac;
    # clean_code chi de dat ten file an toan (vd: sk0005).
    search_code = normalize_exam_code(exam_code) or "exam"
    clean_code = clean_exam_code(exam_code) or "exam"

    topic_str = input("Nhap topic (mac dinh 1): ").strip()
    topic = int(topic_str) if topic_str.isdigit() else 1

    range_input = input("Nhap pham vi cau (vd: 1-10, hoac de trong lay 1-120): ").strip()
    if range_input:
        parsed = parse_range(range_input)
        if parsed is None:
            print("  Pham vi khong hop le, dung mac dinh 1-120.")
            start_q, end_q = 1, 120
        else:
            start_q, end_q = parsed
    else:
        start_q, end_q = 1, 120

    if start_q < 1:
        start_q = 1
    if end_q < 1:
        end_q = 1
    if start_q > end_q:
        start_q, end_q = end_q, start_q

    filename = f"{clean_code}_questions.json"
    filepath = os.path.join(OUTPUT_DIR, filename)

    # Nap du lieu cu de khong ghi de mat; ket qua moi se duoc gop vao.
    all_data = load_all(filepath)

    print(f"\nCrawl {search_code.upper()}, topic {topic}, cau {start_q}-{end_q}")
    print("-"*60)

    print("Khoi dong CloakBrowser...")
    # humanize=True: bat chuyen dong chuot/cuon/go giong nguoi that.
    #
    # Mac dinh cloakbrowser ep fingerprint Windows. Ta doi sang macOS:
    # phai dat stealth_args=False roi TU cap lai dung bo args mac dinh
    # (--no-sandbox + --fingerprint=seed) kem --fingerprint-platform=macos.
    # Da kiem chung: cac lop chong phat hien van nguyen ven (navigator.webdriver
    # = False, window.chrome ton tai) va moi tin hieu nhat quan la macOS
    # (UA, sec-ch-ua-platform, navigator.platform, WebGL renderer = Apple).
    # Giu --disable-dev-shm-usage cho moi truong it RAM (Docker).
    fp_seed = random.randint(10000, 99999)
    browser = launch(
        headless=False,
        humanize=True,
        stealth_args=False,
        args=[
            '--no-sandbox',
            f'--fingerprint={fp_seed}',
            '--fingerprint-platform=macos',
            '--disable-dev-shm-usage',
        ],
    )

    added = 0
    failed = []
    context = None
    page = None
    try:
        total = end_q - start_q + 1
        # Tao mot context/page duy nhat, warm-up cong cu tim kiem mot lan,
        # roi tai su dung xuyen suot phien de giu cookie/session.
        context = browser.new_context()
        try:
            context.set_default_timeout(DEFAULT_OP_TIMEOUT)
        except Exception:
            pass
        page = context.new_page()
        print("Warm-up DuckDuckGo (tao session)...")
        warmup_search(page)

        for qnum in range(start_q, end_q + 1):
            print(f"\n[{qnum - start_q + 1}/{total}] cau {qnum}")

            result = None
            for attempt in range(1, RETRY_LIMIT + 1):
                result = crawl_one_question(page, search_code, topic, qnum)
                if result:
                    break
                print(f"  That bai lan {attempt}/{RETRY_LIMIT} cho cau {qnum}")
                if attempt < RETRY_LIMIT:
                    retry_wait = random.uniform(3, 6)
                    print(f"  -> Thu lai sau {retry_wait:.1f} giay...")
                    time.sleep(retry_wait)

            if result:
                upsert(all_data, result)
                added += 1
                print(f"  Luu cau {qnum} vao output/{filename}")
            else:
                # Khong lay duoc: in ra man hinh + note vao file, roi crawl tiep.
                failed.append(qnum)
                print(f"  KHONG LAY DUOC cau {qnum} -> ghi chu vao file va bo qua")
                upsert(all_data, {
                    "exam_code": search_code,
                    "topic": topic,
                    "question_num": qnum,
                    "question": "",
                    "answers": [],
                    "url": "",
                    "error": "Khong lay duoc cau hoi"
                })
            save_progress(all_data, filename)

            # Nghi ngau nhien giua cac cau (chong nhip deu), bo qua sau cau cuoi.
            if qnum < end_q:
                wait = random.uniform(MIN_DELAY, MAX_DELAY)
                print(f"  Nghi {wait:.1f}s truoc cau tiep theo...")
                time.sleep(wait)

        print("\n"+"="*60)
        print(f"Hoan tat! Lay duoc {added}/{total} cau (tong file: {len(all_data)}).")
        if failed:
            print(f"Khong lay duoc {len(failed)} cau: {', '.join(str(q) for q in failed)}")
        print(f"Ket qua: output/{filename}")
        print("="*60)
    finally:
        safe_close(page)
        safe_close(context)
        safe_close(browser)

if __name__ == "__main__":
    main()
