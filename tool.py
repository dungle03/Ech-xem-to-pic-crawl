import time
import json
import os
import re
import random
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from cloakbrowser import launch
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image as PILImage

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# Nghi ngau nhien giua cac cau (giay) de tranh nhip deu de bi chan.
# DuckDuckGo khoan dung hon Google nhieu nen co the de thap.
MIN_DELAY = 2
MAX_DELAY = 5
RETRY_LIMIT = 3
OUTPUT_DIR = "output"

# Timeout mac dinh (ms) cho cac thao tac Playwright de tranh treo vo han.
DEFAULT_OP_TIMEOUT = 30000

# Sentinel rieng cho case search DDG + Google khong ra link dung cau. Case nay
# khong retry vi moi retry lai ton them 2 lan search engine nhung ket qua nhu cu.
NO_DISCUSSION_LINK = object()

_IMG_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_IMG_CACHE = {}


def _fetch_image(url):
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    try:
        resp = httpx.get(url, headers=_IMG_HEADERS, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        img = PILImage.open(BytesIO(resp.content))
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
    except Exception:
        buf = None
    _IMG_CACHE[url] = buf
    return buf


def _preload_images(questions):
    urls = set()
    for q in questions:
        urls.update(q.get("question_images", []))
        for opt in q.get("options", []):
            urls.update(opt.get("images", []))
    todo = [u for u in urls if u not in _IMG_CACHE]
    if not todo:
        return
    print(f"  Tai {len(todo)} anh...")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_image, u): u for u in todo}
        done = 0
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0:
                print(f"    {done}/{len(todo)}")


def escape_html(text):
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def build_html(questions, exam_code):
    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>{escape_html(exam_code)} - Exam Dump</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; color: #1a1a2e; padding: 24px 16px; }}
.container {{ max-width: 800px; margin: 0 auto; }}
h1 {{ text-align: center; font-size: 1.6em; color: #16213e; margin-bottom: 4px; }}
.meta {{ text-align: center; color: #666; font-size: 0.9em; margin-bottom: 32px; }}
.question-card {{
    background: #fff; border-radius: 12px; padding: 20px 24px; margin-bottom: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08); page-break-inside: avoid;
}}
.q-num {{
    display: inline-block; background: #16213e; color: #fff; border-radius: 6px;
    padding: 2px 10px; font-size: 0.85em; font-weight: 600; margin-bottom: 10px;
}}
.q-text {{ font-size: 1.05em; line-height: 1.55; white-space: pre-wrap; margin-bottom: 14px; }}
.q-images img {{ max-width: 100%; border-radius: 6px; margin: 6px 0; border: 1px solid #ddd; }}
.options {{ list-style: none; }}
.options li {{
    padding: 8px 12px; margin-bottom: 6px; border-radius: 8px;
    border: 1px solid #e0e0e0; line-height: 1.45; font-size: 0.95em;
}}
.options li.correct {{ background: #e8f5e9; border-color: #4caf50; font-weight: 500; }}
.opt-letter {{ font-weight: 700; margin-right: 8px; }}
.correct-badge {{
    display: inline-block; background: #4caf50; color: #fff; border-radius: 4px;
    padding: 1px 7px; font-size: 0.78em; margin-left: 8px; vertical-align: middle;
}}
.answers-section {{ margin-top: 14px; border-top: 1px solid #eee; padding-top: 12px; }}
.answers-toggle {{ cursor: pointer; color: #1565c0; font-size: 0.88em; user-select: none; }}
.answers-content {{ display: none; margin-top: 8px; }}
.answers-content.open {{ display: block; }}
.comment {{
    background: #fafafa; border-left: 3px solid #bbb; border-radius: 0 6px 6px 0;
    padding: 8px 12px; margin-top: 8px; font-size: 0.9em; line-height: 1.5;
    white-space: pre-wrap; word-break: break-word;
}}
.error-tag {{
    display: inline-block; background: #ffebee; color: #c62828; border: 1px solid #ef9a9a;
    border-radius: 6px; padding: 3px 10px; font-size: 0.85em; margin-top: 8px;
}}
</style>
</head>
<body>
<div class="container">
<h1>{escape_html(exam_code.upper())}</h1>
<div class="meta">{len(questions)} cau hoi &middot; Topic dump ExamTopics</div>
""")

    for i, q in enumerate(questions, 1):
        num = q.get("question_num", i)
        question_text = escape_html(q.get("question", ""))
        suggested = q.get("suggested_answers", [])

        images = q.get("question_images", [])
        img_html = ""
        for url in images:
            img_html += f'<img src="{escape_html(url)}" alt="" loading="lazy">\n'

        options_html = ""
        for opt in q.get("options", []):
            letter = opt.get("letter", "")
            text = escape_html(opt.get("text", ""))
            is_correct = opt.get("is_correct", False)
            cls = "correct" if is_correct else ""
            badge = '<span class="correct-badge">&#10003;</span>' if is_correct else ""

            opt_imgs = opt.get("images", [])
            opt_img_html = ""
            for u in opt_imgs:
                opt_img_html += f'<br><img src="{escape_html(u)}" alt="" style="max-width:100%;margin-top:6px;border-radius:4px;">\n'

            options_html += f'<li class="{cls}"><span class="opt-letter">{escape_html(letter)}.</span> {text}{badge}{opt_img_html}</li>\n'

        answers = q.get("answers", [])
        answers_html = ""
        if answers:
            comments = "\n".join(
                f'<div class="comment">{escape_html(c)}</div>' for c in answers
            )
            answers_html = f"""
<div class="answers-section">
<span class="answers-toggle" onclick="var c=this.nextElementSibling;c.classList.toggle('open');this.textContent=c.classList.contains('open')?'&#9654; An binh luan':'&#9660; Xem binh luan ({len(answers)})';">&#9660; Xem binh luan ({len(answers)})</span>
<div class="answers-content open">{comments}</div>
</div>"""

        error_tag = ""
        if q.get("error"):
            error_tag = f'<div><span class="error-tag">Loi: {escape_html(q["error"])}</span></div>'

        answer_str = ", ".join(suggested) if suggested else "N/A"
        parts.append(f"""
<div class="question-card" id="q{num}">
<span class="q-num">Cau {num} &middot; Dap an: {escape_html(answer_str)}</span>
<div class="q-text">{question_text}</div>
{'<div class="q-images">' + img_html + '</div>' if img_html else ''}
<ul class="options">{options_html}</ul>
{error_tag}
{answers_html}
</div>""")

    parts.append("</div>\n</body>\n</html>")
    return "\n".join(parts)


def convert_to_html(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("File JSON khong phai danh sach cau hoi.")
    questions = [q for q in data if isinstance(q, dict) and q.get("question")]
    if not questions:
        raise ValueError("Khong co cau hoi hop le trong file.")
    exam_code = questions[0].get("exam_code", "exam")
    html = build_html(questions, exam_code)
    out_path = os.path.splitext(json_path)[0] + ".html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML: {out_path}")
    return out_path


def _add_question_docx(doc, q, num):
    suggested = q.get("suggested_answers", [])
    answer_str = ", ".join(suggested) if suggested else "N/A"

    heading = doc.add_heading(f"Cau {num}", level=2)
    for run in heading.runs:
        run.font.color.rgb = RGBColor(0x16, 0x21, 0x3E)
        run.font.size = Pt(14)

    answer_p = doc.add_paragraph()
    answer_run = answer_p.add_run(f"Dap an: {answer_str}")
    answer_run.bold = True
    answer_run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)

    question_text = q.get("question", "")
    p = doc.add_paragraph(question_text)
    p.paragraph_format.space_after = Pt(8)

    for url in q.get("question_images", []):
        buf = _fetch_image(url)
        if buf:
            doc.add_picture(buf, width=Inches(5.5))
        else:
            doc.add_paragraph(url)

    for opt in q.get("options", []):
        letter = opt.get("letter", "")
        text = opt.get("text", "")
        is_correct = opt.get("is_correct", False)
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.left_indent = Inches(0.25)

        letter_run = p.add_run(f"{letter}. ")
        letter_run.bold = True

        text_run = p.add_run(text)
        if is_correct:
            text_run.bold = True
            text_run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)
            check = p.add_run("  \u2713")
            check.bold = True
            check.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)

        for img_url in opt.get("images", []):
            buf = _fetch_image(img_url)
            if buf:
                doc.add_picture(buf, width=Inches(4))

    answers = q.get("answers", [])
    if answers:
        doc.add_paragraph("Binh luan:", style="List Bullet")
        for comment in answers[:5]:
            p = doc.add_paragraph(comment[:500])
            p.paragraph_format.left_indent = Inches(0.5)
            p.paragraph_format.space_after = Pt(6)
            for run in p.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    if q.get("error"):
        p = doc.add_paragraph(f"[Loi] {q['error']}")
        for run in p.runs:
            run.font.color.rgb = RGBColor(0xC6, 0x28, 0x28)
            run.font.size = Pt(9)


def convert_to_docx(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("File JSON khong phai danh sach cau hoi.")
    questions = [q for q in data if isinstance(q, dict) and q.get("question")]
    if not questions:
        raise ValueError("Khong co cau hoi hop le trong file.")

    _preload_images(questions)

    exam_code = questions[0].get("exam_code", "exam")
    doc = Document()

    title = doc.add_heading(exam_code.upper(), level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph(f"{len(questions)} cau hoi - Topic dump ExamTopics")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_page_break()

    for i, q in enumerate(questions, 1):
        _add_question_docx(doc, q, q.get("question_num", i))

    out_path = os.path.splitext(json_path)[0] + ".docx"
    doc.save(out_path)
    print(f"DOCX: {out_path}")
    return out_path

def canonical_exam_code(code):
    """Chuan hoa ma de de DOI CHIEU URL: chi giu chu/so.

    Cung dung de dat ten file an toan (bo dau phan cach).
    Search van dung `normalize_exam_code()` de go dung ma de nguoi dung nhap
    (giu -, _, .). Rieng URL ExamTopics/search index co the bo/doi dau phan
    cach, vd H12-711_V4.0 -> h12-711_v40. So sanh chuoi chu/so giup nhan dung
    dung ma de ma khong phu thuoc cach URL bieu dien dau.
    """
    return re.sub(r'[^a-z0-9]', '', (code or '').lower())

def normalize_exam_code(code):
    """Chuan hoa ma de cho tim kiem.

    Giu dung dinh dang ma de nhu slug cua examtopics de query va so khop URL
    chinh xac. Da kiem chung tren examtopics:
        SK0-005          -> sk0-005
        H12-711_V4.0     -> h12-711_v4.0
        FCSS_NST_SE-7.6  -> fcss_nst_se-7.6
    Quy tac: chu thuong; khoang trang -> gach noi; GIU lai chu/so/gach
    duoi/gach noi/dau cham; bo cac ky tu con lai.
    Khac voi canonical_exam_code (ham do chi dung de dat ten file an toan).
    """
    code = code.strip().lower()
    code = re.sub(r'\s+', '-', code)          # khoang trang -> gach noi
    code = re.sub(r'[^a-z0-9_.-]', '', code)  # giu chu/so/gach duoi/gach noi/dau cham
    code = re.sub(r'-+', '-', code).strip('-_.')
    return code

def link_matches_question(href, exam_code, topic, qnum):
    """Kiem tra link discussion co dung cau hoi dang can hay khong.

    examtopics dung slug dang:
        .../view/61482-exam-sk0-005-topic-1-question-1-discussion/
    Ta yeu cau khop dung exam_code + topic + qnum de khong lay nham cau khac,
    ma de khac (vd xk0-005), hay trang tong hop nhieu cau. Rieng exam_code duoc
    so sanh theo chu/so vi search index co the bo/doi dau phan cach trong URL
    (vd h12-711_v4.0 -> h12-711_v40).
    Phan '-discussion' ngay sau qnum chong viec question-2 khop nham question-20.
    """
    if not href or 'examtopics.com/discussions' not in href:
        return False
    href = href.lower()
    match = re.search(
        r'exam-(?P<code>.+?)-topic-(?P<topic>\d+)-question-(?P<qnum>\d+)-discussion',
        href,
    )
    if not match:
        return False
    return (
        canonical_exam_code(match.group('code')) == canonical_exam_code(exam_code)
        and int(match.group('topic')) == int(topic)
        and int(match.group('qnum')) == int(qnum)
    )

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
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
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

# Cau hinh cac cong cu tim kiem. DuckDuckGo la engine chinh (it CAPTCHA),
# Google chi dung lam fallback khi DDG khong tra ra link dung cau.
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

def search_engine(page, query, engine="duckduckgo"):
    """Go query vao o tim kiem cua engine (duckduckgo/google) nhu nguoi that.

    Moi lan deu quay ve trang chu engine truoc roi moi go vao o tim kiem, nen
    o luon sach (tranh query bi noi chong), dong thoi van giu cookie/session vi
    context duoc tai su dung xuyen suot phien.
    Tra ve True neu search thanh cong, False neu that bai.
    """
    cfg = SEARCH_ENGINES.get(engine)
    if not cfg:
        print(f"  Engine khong ho tro: {engine}")
        return False

    # Luon ve trang chu de co o tim kiem trong, sach.
    if not safe_goto(page, cfg["home"]):
        print(f"  Khong tai duoc {engine}")
        return False
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
            if random.random() < 0.10:
                time.sleep(random.uniform(0.1, 0.25))
        time.sleep(random.uniform(0.3, 0.7))
        page.keyboard.press("Enter")
    except Exception as e:
        print(f"  Loi go query: {e}")
        return False

    # Cho ket qua hien. Ket qua render bat dong bo SAU khi domcontentloaded
    # da fire, nen phai doi tan element ket qua xuat hien, khong sleep cung.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_OP_TIMEOUT)
    except PlaywrightTimeoutError:
        pass
    for sel in cfg["result_selectors"]:
        try:
            page.wait_for_selector(sel, timeout=8000)
            break
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue
    time.sleep(random.uniform(0.8, 1.5))
    return True

def is_examtopics_discussion_url(url):
    """Kiem tra URL da giai ma co tro den trang discussion ExamTopics khong."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return (
        parsed.scheme in ("http", "https")
        and host == "examtopics.com"
        and "/discussions/" in parsed.path
    )

def unwrap_search_href(raw_href, base_url):
    """Giai ma link ket qua search ve cac URL ung vien thuc.

    DuckDuckGo/Google thuong boc link dich trong redirect params nhu `uddg`,
    `url`, `q`. Neu chi doc href thuan thi se thay domain search engine thay vi
    examtopics, dan den bo sot ket qua dang hien ro tren man hinh.
    """
    candidates = []

    def add(url):
        if not url:
            return
        url = unquote(str(url).strip())
        if base_url and url.startswith("/"):
            url = urljoin(base_url, url)
        if url and url not in candidates:
            candidates.append(url)

    add(raw_href)
    idx = 0
    while idx < len(candidates):
        current = candidates[idx]
        idx += 1

        try:
            parsed = urlparse(current)
            params = parse_qs(parsed.query)
        except Exception:
            params = {}

        for key in ("uddg", "url", "q", "u"):
            for value in params.get(key, []):
                add(value)

        decoded = unquote(current)
        for match in re.findall(
            r'https?://(?:www\.)?examtopics\.com/[^\s&"\'<>]+',
            decoded,
            flags=re.I,
        ):
            add(match)

    return candidates

def extract_matching_link(page, exam_code, topic, qnum):
    """Duyet link tren trang ket qua, tra ve URL examtopics discussion khop cau.

    Doc moi anchor tren trang search, giai ma redirect/wrapper cua DuckDuckGo
    va Google, sau do chi chap nhan URL dich thuc su nam tren examtopics.com.
    """
    try:
        links = page.query_selector_all('a[href]')
    except Exception as e:
        print(f"  Loi liet ke link: {e}")
        links = []
    try:
        base_url = page.url
    except Exception:
        base_url = ""
    for link in links:
        try:
            raw_href = link.get_attribute('href')
        except Exception:
            raw_href = None
        if not raw_href:
            continue
        for candidate in unwrap_search_href(raw_href, base_url):
            if not is_examtopics_discussion_url(candidate):
                continue
            if link_matches_question(candidate, exam_code, topic, qnum):
                return candidate
    return None

def find_discussion_link(page, exam_code, topic, qnum):
    """Tim URL discussion khop cau hoi. Thu DuckDuckGo truoc, khong thay -> Google.

    Them 'site:examtopics.com' de thu hep ket qua chi trong examtopics, tang
    do chinh xac va recall. Google chi dung khi DDG khong ra ket qua dung cau.
    """
    query = (f"exam {exam_code} topic {topic} question {qnum} "
             f"discussion site:examtopics.com")

    # 1. DuckDuckGo (engine chinh, it CAPTCHA)
    if search_engine(page, query, "duckduckgo"):
        href = extract_matching_link(page, exam_code, topic, qnum)
        if href:
            return href
    print("  DuckDuckGo khong co link dung cau, thu Google...")

    # 2. Google (fallback)
    if search_engine(page, query, "google"):
        href = extract_matching_link(page, exam_code, topic, qnum)
        if href:
            return href
    return None

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
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
    try:
        resp = httpx.get(href, headers={"User-Agent": ua}, timeout=timeout,
                         follow_redirects=True)
        if resp.status_code != 200 or not resp.text:
            print(f"    HTTP fallback tra ve {resp.status_code}")
            return False
        html_text = resp.text
    except Exception as e:
        print(f"    Loi tai HTTP: {e}")
        return False
    # Xoa script/iframe: chung khien trinh duyet co gang tai/thuc thi
    # tracker+ads, trong khi noi dung can boc la HTML tinh render san.
    html_text = re.sub(r'<script\b[^>]*>.*?</script>', '', html_text,
                       flags=re.S | re.I)
    html_text = re.sub(r'<script\b[^>]*/>', '', html_text, flags=re.I)
    html_text = re.sub(r'<iframe\b[^>]*>.*?</iframe>', '', html_text,
                       flags=re.S | re.I)
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
        if not href:
            print(f"  Khong tim thay link examtopics dung cau {qnum} (DDG + Google deu khong ra)")
            return NO_DISCUSSION_LINK
        print(f"  Tim thay: {href}")

        # 3. Mo tab discussion. Uu tien mo tab moi (giong nguoi bam vao ket qua),
        #    cho tan khi noi dung discussion hien. Neu tab treo/khong len noi dung
        #    -> fallback: tai HTML bang HTTP thuan (dung href da ghi nho) roi nap
        #    vao tab. Trang discussion render san tu server nen HTTP lay duoc
        #    trong ~1s ngay ca khi browser treo vo han vi tracker/ads.
        print("  Dang mo tab moi...")
        try:
            with page.context.expect_page(timeout=15000) as new_page_info:
                # json.dumps de chong vo JS khi href chua dau nhay don.
                page.evaluate(f"window.open({json.dumps(href)}, '_blank');")
            new_tab = new_page_info.value
        except PlaywrightTimeoutError:
            print("  Het thoi gian cho tab moi")
            new_tab = None
        except Exception as e:
            print(f"  Loi mo tab moi: {e}")
            new_tab = None

        loaded = False
        if new_tab:
            print("  Da mo tab moi, dang cho noi dung...")
            loaded = wait_for_discussion(new_tab, timeout=15000)

        if not loaded:
            # Fallback: tai HTML bang HTTP thuan roi nap vao tab.
            print("  Tab load lau/loi -> tai thang link bang HTTP...")
            # Dung tab da mo neu co, khong thi tao tab moi de nap noi dung.
            if new_tab is None:
                try:
                    new_tab = page.context.new_page()
                except Exception as e:
                    print(f"  Loi tao tab: {e}")
                    new_tab = None
            if new_tab is not None:
                loaded = load_discussion_via_http(new_tab, href)
                if loaded:
                    print("  Da tai noi dung qua HTTP")

        if not new_tab:
            print("  Khong mo duoc tab discussion")
            return None
        if not loaded:
            print("  Van khong tai duoc noi dung discussion, thu boc du lieu du co...")
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

        # Lay hinh anh trong de bai (neu co). Nhieu ma de (vd FCSS_NST_SE-7.6)
        # co so do/hinh minh hoa nam trong <img> ben trong .question-body.
        # Dung im.src (thuoc tinh) de luon ra URL tuyet doi; ho tro ca lazy-load
        # qua data-src/data-original.
        try:
            question_images = new_tab.evaluate("""
                () => {
                    const container = document.querySelector('.discussion-header-container');
                    if (!container) return [];
                    const scope = container.querySelector('.question-body') || container;
                    const imgs = Array.from(scope.querySelectorAll('img'));
                    const urls = imgs.map(im =>
                        im.getAttribute('data-src')
                        || im.getAttribute('data-original')
                        || im.src
                        || '');
                    // Loc rong + trung lap, giu thu tu.
                    return urls.filter((u, i) => u && urls.indexOf(u) === i);
                }
            """)
        except Exception as e:
            print(f"  Loi lay hinh de bai: {e}")
            question_images = []
        if not isinstance(question_images, list):
            question_images = []

        # Lay cac lua chon dap an (A/B/C/D...) tu .question-choices-container.
        # Moi item co .multi-choice-letter[data-choice-letter] cho chu cai,
        # phan text con lai la noi dung, va co the kem <img>. Class
        # 'correct-hidden' danh dau dap an goi y dung tren examtopics.
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
        print(f"  Cau hoi: {clean_q[:100]}...")
        if clean_q_images:
            print(f"  So hinh trong de bai: {len(clean_q_images)}")
        print(f"  So lua chon: {len(clean_options)}"
              + (f" (dap an goi y: {', '.join(suggested_answers)})" if suggested_answers else ""))
        print(f"  So binh luan: {len(clean_ans)}")

        return {
            "exam_code": exam_code,
            "topic": topic,
            "question_num": qnum,
            "question": clean_q,
            "question_images": clean_q_images,
            "options": clean_options,
            "suggested_answers": suggested_answers,
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
    clean_code = canonical_exam_code(exam_code) or "exam"

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
        context.set_default_timeout(DEFAULT_OP_TIMEOUT)
        page = context.new_page()
        print("Warm-up DuckDuckGo (tao session)...")
        if not warmup_search(page):
            print("  Canh bao: khong tai duoc DuckDuckGo, van thu crawl tiep.")

        for qnum in range(start_q, end_q + 1):
            print(f"\n[{qnum - start_q + 1}/{total}] cau {qnum}")

            result = None
            no_link = False
            for attempt in range(1, RETRY_LIMIT + 1):
                result = crawl_one_question(page, search_code, topic, qnum)
                if result is NO_DISCUSSION_LINK:
                    no_link = True
                    print(f"  Bo qua cau {qnum}: khong tim thay link, khong retry.")
                    break
                if result:
                    break
                print(f"  That bai lan {attempt}/{RETRY_LIMIT} cho cau {qnum}")
                if attempt < RETRY_LIMIT:
                    retry_wait = random.uniform(3, 6)
                    print(f"  -> Thu lai sau {retry_wait:.1f} giay...")
                    time.sleep(retry_wait)

            if result and result is not NO_DISCUSSION_LINK:
                upsert(all_data, result)
                added += 1
                print(f"  Luu cau {qnum} vao output/{filename}")
            else:
                # Khong lay duoc: in ra man hinh + note vao file, roi crawl tiep.
                failed.append(qnum)
                error_msg = "Khong tim thay link discussion" if no_link else "Khong lay duoc cau hoi"
                print(f"  KHONG LAY DUOC cau {qnum} -> ghi chu vao file va bo qua")
                upsert(all_data, {
                    "exam_code": search_code,
                    "topic": topic,
                    "question_num": qnum,
                    "question": "",
                    "question_images": [],
                    "options": [],
                    "suggested_answers": [],
                    "answers": [],
                    "url": "",
                    "error": error_msg
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

        choice = input("\nConvert sang HTML + DOCX? (y/N): ").strip().lower()
        if choice == "y":
            try:
                convert_to_html(filepath)
                convert_to_docx(filepath)
            except Exception as e:
                print(f"  Loi convert: {e}")
    finally:
        safe_close(page)
        safe_close(context)
        safe_close(browser)

if __name__ == "__main__":
    main()
