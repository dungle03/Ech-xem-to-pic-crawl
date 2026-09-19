import os
import re
import json
import html
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .config import (
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
        print(f"  Loi liet ke link: {e}")
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

def load_all(filepath):
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
    if not isinstance(record, dict):
        return
    key = (int(record.get("topic") or 1), int(record.get("question_num") or 0))
    for i, rec in enumerate(all_data):
        if isinstance(rec, dict) and (int(rec.get("topic") or 1), int(rec.get("question_num") or 0)) == key:
            all_data[i] = record
            all_data.sort(key=lambda r: (int(r.get("topic") or 1), int(r.get("question_num") or 0)) if isinstance(r, dict) else (0, 0))
            return
    all_data.append(record)
    all_data.sort(key=lambda r: (int(r.get("topic") or 1), int(r.get("question_num") or 0)) if isinstance(r, dict) else (0, 0))

def save_progress(data, filename):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, filename)
    temp_path = filepath + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, filepath)
        return True
    except Exception as e:
        print(f"  Loi JSON: {e}, thu fallback...")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
            os.replace(temp_path, filepath)
            return True
        except Exception as e2:
            print(f"  Fallback JSON that bai: {e2}")
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            return False
