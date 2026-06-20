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

DELAY = 3
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

def crawl_one_question(browser, exam_code, topic, qnum):
    context = None
    page = None
    new_tab = None
    clean_code = clean_exam_code(exam_code)
    query = f"exam {clean_code} topic {topic} question {qnum} discussion"
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    print(f"\n[Google] {query}")

    try:
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            viewport={'width': 1600, 'height': 900}
        )
        try:
            context.set_default_timeout(DEFAULT_OP_TIMEOUT)
        except Exception:
            pass
        page = context.new_page()

        # 1. Google search
        if not safe_goto(page, search_url):
            print("  Khong tai duoc Google")
            return None
        time.sleep(2)

        # 2. Tim link examtopics
        target_link = None
        selectors = [
            'a[href*="examtopics.com/discussions"]',
            'a[href*="examtopics.com"]'
        ]
        for sel in selectors:
            try:
                target_link = page.query_selector(sel)
                if target_link:
                    break
            except Exception as e:
                print(f"  Loi selector {sel}: {e}")
                continue
        if not target_link:
            try:
                links = page.query_selector_all('a')
            except Exception as e:
                print(f"  Loi liet ke link: {e}")
                links = []
            for link in links:
                try:
                    href = link.get_attribute('href')
                except Exception:
                    href = None
                if href and 'examtopics.com/discussions' in href:
                    target_link = link
                    break
        if not target_link:
            print("  Khong tim thay link examtopics")
            return None

        href = target_link.get_attribute('href')
        if not href:
            print("  Link examtopics khong co href hop le")
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
        print(f"  Cau hoi: {clean_q[:100]}...")
        print(f"  So binh luan: {len(clean_ans)}")

        return {
            "exam_code": clean_code,
            "topic": topic,
            "question_num": qnum,
            "question": clean_q,
            "answers": clean_ans,
            "url": url
        }
    except Exception as e:
        print(f"  Loi: {e}")
        return None
    finally:
        # Luon dong tab/page/context du co exception o bat ky buoc nao.
        safe_close(new_tab)
        safe_close(page)
        safe_close(context)

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

    print(f"\nCrawl {clean_code.upper()}, topic {topic}, cau {start_q}-{end_q}")
    print("-"*60)

    print("Khoi dong CloakBrowser...")
    browser = launch(headless=False, args=[
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-dev-shm-usage'
    ])

    added = 0
    failed = []
    try:
        total = end_q - start_q + 1
        for qnum in range(start_q, end_q + 1):
            print(f"\n[{qnum - start_q + 1}/{total}] cau {qnum}")

            result = None
            for attempt in range(1, RETRY_LIMIT + 1):
                result = crawl_one_question(browser, clean_code, topic, qnum)
                if result:
                    break
                print(f"  That bai lan {attempt}/{RETRY_LIMIT} cho cau {qnum}")
                if attempt < RETRY_LIMIT:
                    print("  -> Thu lai sau 10 giay...")
                    time.sleep(10)

            if result:
                upsert(all_data, result)
                added += 1
                print(f"  Luu cau {qnum} vao output/{filename}")
            else:
                # Khong lay duoc: in ra man hinh + note vao file, roi crawl tiep.
                failed.append(qnum)
                print(f"  KHONG LAY DUOC cau {qnum} -> ghi chu vao file va bo qua")
                upsert(all_data, {
                    "exam_code": clean_code,
                    "topic": topic,
                    "question_num": qnum,
                    "question": "",
                    "answers": [],
                    "url": "",
                    "error": "Khong lay duoc cau hoi"
                })
            save_progress(all_data, filename)

            # Nghi giua cac cau (jitter chong nhip deu), bo qua sau cau cuoi.
            if qnum < end_q:
                time.sleep(DELAY + random.uniform(0, 1.5))

        print("\n"+"="*60)
        print(f"Hoan tat! Lay duoc {added}/{total} cau (tong file: {len(all_data)}).")
        if failed:
            print(f"Khong lay duoc {len(failed)} cau: {', '.join(str(q) for q in failed)}")
        print(f"Ket qua: output/{filename}")
        print("="*60)
    finally:
        safe_close(browser)

if __name__ == "__main__":
    main()
