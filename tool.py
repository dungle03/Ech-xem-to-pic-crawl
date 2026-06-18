import time
import json
import os
import re
from cloakbrowser import launch

DELAY = 3
RETRY_LIMIT = 3
OUTPUT_DIR = "output"

def safe_encode(text):
    if not isinstance(text, str):
        return text
    try:
        return text.encode('utf-8', errors='ignore').decode('utf-8')
    except:
        result = []
        for ch in text:
            try:
                ch.encode('utf-8')
                result.append(ch)
            except:
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

def save_progress(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    try:
        cleaned = clean_data(data)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"  ⚠️ Lỗi JSON: {e}, thử fallback...")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
            return True
        except:
            return False

def wait_for_page_load(page, timeout=30000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        return True
    except:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            return True
        except:
            return False

def safe_goto(page, url, timeout=60000):
    try:
        page.goto(url, wait_until="commit", timeout=timeout)
        time.sleep(1)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass
        return True
    except Exception as e:
        print(f"    Lỗi điều hướng: {e}")
        return False

def crawl_one_question(browser, exam_code, topic, qnum):
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        viewport={'width': 1600, 'height': 900}
    )
    page = context.new_page()
    clean_code = clean_exam_code(exam_code)
    query = f"exam {clean_code} topic {topic} question {qnum} discussion"
    search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    print(f"\n🔍 [Google] {query}")

    try:
        # 1. Google search
        if not safe_goto(page, search_url):
            print("  ❌ Không tải được Google")
            page.close(); context.close(); return None
        time.sleep(2)

        # 2. Tìm link examtopics
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
            except:
                continue
        if not target_link:
            links = page.query_selector_all('a')
            for link in links:
                href = link.get_attribute('href')
                if href and 'examtopics.com/discussions' in href:
                    target_link = link
                    break
        if not target_link:
            print("  ❌ Không tìm thấy link examtopics")
            page.close(); context.close(); return None

        href = target_link.get_attribute('href')
        print(f"  ✅ Tìm thấy: {href}")

        # 3. Mở tab mới (chuột giữa)
        print("  🖱️ Đang mở tab mới...")
        with page.context.expect_page() as new_page_info:
            page.evaluate(f"window.open('{href}', '_blank');")
        new_tab = new_page_info.value
        if not new_tab:
            print("  ❌ Không mở được tab mới")
            page.close(); context.close(); return None
        print("  ✅ Đã mở tab mới")
        
        if not wait_for_page_load(new_tab, timeout=30000):
            print("  ⚠️ Tab mới load chậm, vẫn tiếp tục...")
        time.sleep(1)

        # 4. Xóa overlay
        print("  ⏳ Đang xóa overlay...")
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
            print("  ✅ Đã xoá overlay")
        except Exception as e:
            print(f"  ⚠️ Lỗi xóa overlay: {e}")

        # 5. Lấy câu hỏi và bình luận
        print("  ⏳ Đang lấy nội dung...")
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
        if not question:
            question = new_tab.evaluate("""
                () => {
                    const body = document.querySelector('.discussion-header-container');
                    return body ? body.innerText.trim() : '';
                }
            """)
        
        answers = new_tab.evaluate("""
            () => {
                const comments = document.querySelectorAll('.comment-content');
                return Array.from(comments).map(c => c.innerText.trim());
            }
        """)
        url = new_tab.url
        new_tab.close()
        page.close()
        context.close()

        if not question:
            print(f"  ⚠️ Không lấy được câu hỏi cho câu {qnum}")
            return None

        clean_q = safe_encode(question)
        clean_ans = [safe_encode(a) for a in answers if a]
        print(f"  📝 Câu hỏi: {clean_q[:100]}...")
        print(f"  💬 Số bình luận: {len(clean_ans)}")
        
        return {
            "exam_code": clean_code,
            "topic": topic,
            "question_num": qnum,
            "question": clean_q,
            "answers": clean_ans,
            "url": url
        }
    except Exception as e:
        print(f"  ❌ Lỗi: {e}")
        try:
            page.close()
            context.close()
        except:
            pass
        return None

def main():
    print("="*60)
    print("  CRAWL EXAMTOPICS - BẢN LƯU LIÊN TỤC")
    print("="*60)
    
    exam_code = input("🔹 Nhập mã đề (ex200, ex300): ").strip() or "ex200"
    clean_code = clean_exam_code(exam_code) or "exam"
    
    topic_str = input("🔹 Nhập topic (mặc định 1): ").strip()
    topic = int(topic_str) if topic_str.isdigit() else 1
    
    range_input = input("🔹 Nhập phạm vi câu (vd: 1-10, hoặc để trống lấy 1-120): ").strip()
    if range_input:
        parts = range_input.split('-')
        if len(parts) == 2:
            start_q, end_q = int(parts[0]), int(parts[1])
        elif len(parts) == 1:
            start_q = end_q = int(parts[0])
        else:
            start_q, end_q = 1, 120
    else:
        max_q = input("🔹 Nhập số câu tối đa (mặc định 120): ").strip()
        start_q, end_q = 1, int(max_q) if max_q.isdigit() else 120
    
    if start_q > end_q:
        start_q, end_q = end_q, start_q
    
    filename = f"{clean_code}_questions.json"
    all_data = []
    start_from = start_q
    
    # Kiểm tra file cũ
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing:
                last_q = existing[-1]["question_num"]
                print(f"📂 Đã có {len(existing)} câu (cuối: {last_q})")
                if input("Tiếp tục từ câu tiếp theo? (y/n): ").strip().lower() == 'y':
                    start_from = last_q + 1
                    all_data = existing
                    if start_from > end_q:
                        print("✅ Đã crawl hết phạm vi!")
                        return
        except:
            pass
    
    print(f"\n🚀 Crawl {clean_code.upper()}, topic {topic}, từ câu {start_from} đến {end_q}")
    print("-"*60)
    
    print("🚀 Khởi động CloakBrowser...")
    browser = launch(headless=False, args=[
        '--disable-blink-features=AutomationControlled',
        '--no-sandbox',
        '--disable-dev-shm-usage'
    ])
    
    qnum = start_from
    fail = 0
    while qnum <= end_q and fail < 3:
        result = crawl_one_question(browser, clean_code, topic, qnum)
        if result:
            all_data.append(result)
            save_progress(all_data, filename)
            print(f"  ✅ Lưu câu {qnum} vào output/{filename}")
            fail = 0
            qnum += 1
        else:
            fail += 1
            print(f"  ⚠️ Thất bại lần {fail} cho câu {qnum}")
            if fail < 3:
                print("  -> Thử lại sau 10 giây...")
                time.sleep(10)
            else:
                print(f"  ❌ Dừng vì không tìm thấy câu {qnum}")
                break
        time.sleep(DELAY)
    
    save_progress(all_data, filename)
    print("\n"+"="*60)
    print(f"🎉 Hoàn tất! Đã crawl {len(all_data)} câu.")
    print(f"📁 Kết quả: output/{filename}")
    print("="*60)
    browser.close()

if __name__ == "__main__":
    main()
