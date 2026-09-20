import os
import re
import json
import html
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .config import (
    LOG,
    _HARVESTED_LINKS,
    OUTPUT_DIR,
    SEARCH_BLOCKED,
    SEARCH_ERROR,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    _RE_EXAMTOPICS_URL,
    _RE_DISCUSSION_SLUG,
)

def escape_html(text):
    return html.escape(str(text or ""), quote=True)

def as_int(value, default=0):
    """Ep ve int an toan, chiu duoc chuoi so, None va gia tri rac.

    Dung de so sanh key (topic, question_num) giua cac nguon du lieu co the
    luu kieu khac nhau (int hoac str), tranh coi hai ban ghi cung cau la khac
    nhau roi ghi de mat du lieu tot.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def canonical_exam_code(code):
    return re.sub(r'[^a-z0-9]', '', (code or '').lower())

def normalize_exam_code(code):
    code = str(code or "").strip().lower()
    code = re.sub(r'\s+', '-', code)
    code = re.sub(r'[^a-z0-9_.-]', '', code)
    code = re.sub(r'-+', '-', code).strip('-_.')
    return code

def extract_discussion_info(href):
    """Trich xuat (canonical_code, topic, qnum) tu URL discussion ExamTopics."""
    if not href or 'examtopics.com/discussions' not in str(href).lower():
        return None
    match = _RE_DISCUSSION_SLUG.search(str(href).lower())
    if not match:
        return None
    try:
        code = canonical_exam_code(match.group('code'))
        topic = int(match.group('topic'))
        qnum = int(match.group('qnum'))
        return code, topic, qnum
    except (ValueError, TypeError):
        return None


def link_matches_question(href, exam_code, topic, qnum):
    """Kiem tra mot href co tro dung cau hoi (code + topic + qnum) khong.

    Luu y: pipeline crawl hien tai KHONG goi ham nay truc tiep -- no dung
    `extract_discussion_info()` + so sanh tuple trong `extract_matching_link()`.
    Ham duoc giu lai nhu mot tien ich so khop doc lap (va duoc xuat qua
    `examtopic.link_matches_question` + `tool.link_matches_question`) de khong
    pha vo API cong khai.
    """
    if not href or 'examtopics.com/discussions' not in href.lower():
        return False
    href = href.lower()
    match = _RE_DISCUSSION_SLUG.search(href)
    if not match:
        return False
    return (
        canonical_exam_code(match.group('code')) == canonical_exam_code(exam_code)
        and int(match.group('topic')) == int(topic)
        and int(match.group('qnum')) == int(qnum)
    )

def is_examtopics_discussion_url(url):
    raw = str(url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return (
        (host == "examtopics.com" or host.endswith(".examtopics.com"))
        and parsed.path.lower().startswith("/discussions/")
    )

def unwrap_search_href(raw_href, base_url):
    candidates = []

    def add(url):
        if not url:
            return
        url = unquote(str(url).strip())
        if url.startswith("www."):
            url = "https://" + url
        elif url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/discussions/"):
            url = "https://www.examtopics.com" + url
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
        for match in _RE_EXAMTOPICS_URL.findall(decoded):
            add(match)
        for m in re.findall(r'www\.examtopics\.com/[^\s&"\'<>\']+', decoded, re.I):
            add("https://" + m)

    return candidates

def extract_matching_link(page, exam_code, topic, qnum):
    try:
        links = page.query_selector_all('a[href]')
    except Exception as e:
        LOG.warning(f"  Loi liet ke link: {e}")
        links = []
    try:
        base_url = page.url
    except Exception:
        base_url = ""
    target_key = (canonical_exam_code(exam_code), int(topic), int(qnum))
    matched_link = None
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
            info = extract_discussion_info(candidate)
            if info:
                _HARVESTED_LINKS[info] = candidate
                if info == target_key and not matched_link:
                    matched_link = candidate
    return matched_link

def no_link_result(primary_status, fallback_status):
    unavailable = (SEARCH_BLOCKED, SEARCH_ERROR)
    if primary_status in unavailable and fallback_status in unavailable:
        return NO_DISCUSSION_BLOCKED
    return NO_DISCUSSION_MISSING

def parse_range(range_input):
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

def _quarantine_corrupt_file(filepath, reason):
    """Doi ten file hong sang <file>.corrupt-<timestamp> de KHONG mat du lieu.

    Neu doc file that bai, ta khong duoc coi nhu chua co du lieu roi ghi de:
    lam vay se xoa vinh vien toan bo du lieu cu. Thay vao do, giu nguyen file
    (doi ten) de nguoi dung con co the cuu, va canh bao ro rang.
    """
    import time as _time
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    backup = f"{filepath}.corrupt-{stamp}"
    try:
        os.replace(filepath, backup)
        LOG.warning(f"  [!] File cu bi loi ({reason}). Da giu lai ban goc tai: {backup}")
        LOG.warning("      Bat dau lai tu dau, nhung du lieu cu KHONG bi mat.")
    except OSError as e:
        LOG.error(f"  [!] File cu bi loi ({reason}) va khong the doi ten ({e}).")
        LOG.error("      DUNG LAI de tranh ghi de mat du lieu. Hay sao luu file roi chay lai.")
        raise SystemExit(1)


def load_all(filepath):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        _quarantine_corrupt_file(filepath, e)
        return []
    if not isinstance(data, list):
        _quarantine_corrupt_file(filepath, "khong phai danh sach")
        return []
    return data

def has_good_data(all_data, topic, qnum):
    """Kiem tra da co cau hoi tot (co noi dung) cho (topic, qnum) chua.

    Dung truoc khi ghi ban ghi loi de tranh ghi de mat cau hoi tot da crawl
    duoc tu lan truoc. So sanh key bang as_int nen chiu duoc ca du lieu cu
    luu topic/question_num dang chuoi.
    """
    key = (as_int(topic, 1) or 1, as_int(qnum, 0))
    return any(_record_key(rec) == key and rec.get("question") for rec in all_data)

def _record_key(rec):
    """Khoa sap xep (topic, question_num) an toan voi moi kieu du lieu."""
    if not isinstance(rec, dict):
        return (0, 0)
    return (as_int(rec.get("topic"), 1) or 1, as_int(rec.get("question_num"), 0))

def upsert(all_data, record):
    if not isinstance(record, dict):
        return
    key = _record_key(record)
    for i, rec in enumerate(all_data):
        if _record_key(rec) == key:
            all_data[i] = record
            all_data.sort(key=_record_key)
            return
    all_data.append(record)
    all_data.sort(key=_record_key)

def _write_json_durable(temp_path, payload):
    """Ghi payload ra temp_path roi fsync de du lieu thuc su xuong dia.

    Khong fsync thi sau os.replace, du lieu co the con nam trong cache cua OS;
    mat dien ngay sau do co the de lai file rong/hong. fsync truoc khi replace
    dam bao file tam da ben vung truoc khi thay the file chinh.
    """
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())


def save_progress(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    temp_path = filepath + ".tmp"
    try:
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        _write_json_durable(temp_path, payload)
        os.replace(temp_path, filepath)
        return True
    except Exception as e:
        LOG.warning(f"  Loi JSON: {e}, thu fallback...")
        try:
            payload = json.dumps(data, ensure_ascii=True, indent=2)
            _write_json_durable(temp_path, payload)
            os.replace(temp_path, filepath)
            return True
        except Exception as e2:
            LOG.error(f"  Fallback JSON that bai: {e2}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False
