import os
import sys
import random
import time
from cloakbrowser import launch

from examtopic import (
    LOG,
    configure_logging,
    MIN_DELAY,
    MAX_DELAY,
    RETRY_LIMIT,
    BLOCKED_ABORT_STREAK,
    OUTPUT_DIR,
    DEFAULT_OP_TIMEOUT,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    SEARCH_OK,
    SEARCH_EMPTY,
    SEARCH_BLOCKED,
    SEARCH_ERROR,
    _IMG_HEADERS,
    _IMG_CACHE,
    _SESSION_COOKIES,
    _HARVESTED_LINKS,
    _PROXY,
    set_proxy,
    _fetch_image_bytes,
    _fetch_image,
    _preload_images,
    escape_html,
    as_int,
    canonical_exam_code,
    normalize_exam_code,
    extract_discussion_info,
    link_matches_question,
    is_examtopics_discussion_url,
    unwrap_search_href,
    extract_matching_link,
    no_link_result,
    parse_range,
    load_all,
    has_good_data,
    upsert,
    save_progress,
    safe_close,
    safe_goto,
    warmup_search,
    search_engine,
    find_discussion_link,
    close_extra_tabs,
    wait_for_discussion,
    load_discussion_via_http,
    sync_browser_session,
    crawl_one_question,
    build_html,
    convert_to_html,
    convert_to_docx,
    _add_picture_fitted,
    _add_question_docx,
    _add_answer_key_table,
    _set_default_font,
)


__all__ = [
    "MIN_DELAY",
    "MAX_DELAY",
    "RETRY_LIMIT",
    "BLOCKED_ABORT_STREAK",
    "OUTPUT_DIR",
    "LOG",
    "configure_logging",
    "DEFAULT_OP_TIMEOUT",
    "NO_DISCUSSION_BLOCKED",
    "NO_DISCUSSION_MISSING",
    "SEARCH_OK",
    "SEARCH_EMPTY",
    "SEARCH_BLOCKED",
    "SEARCH_ERROR",
    "_IMG_HEADERS",
    "_IMG_CACHE",
    "_SESSION_COOKIES",
    "_HARVESTED_LINKS",
    "_PROXY",
    "set_proxy",
    "_fetch_image_bytes",
    "_fetch_image",
    "_preload_images",
    "escape_html",
    "canonical_exam_code",
    "normalize_exam_code",
    "extract_discussion_info",
    "link_matches_question",
    "is_examtopics_discussion_url",
    "unwrap_search_href",
    "extract_matching_link",
    "no_link_result",
    "parse_range",
    "load_all",
    "upsert",
    "as_int",
    "has_good_data",
    "save_progress",
    "safe_close",
    "safe_goto",
    "warmup_search",
    "search_engine",
    "find_discussion_link",
    "close_extra_tabs",
    "wait_for_discussion",
    "load_discussion_via_http",
    "sync_browser_session",
    "crawl_one_question",
    "build_html",
    "convert_to_html",
    "convert_to_docx",
    "_add_picture_fitted",
    "_add_question_docx",
    "_add_answer_key_table",
    "_set_default_font",
    "parse_args",
    "record_error",
    "main",
]

def record_error(record, errors):
    """Them mot ban ghi loi vao danh sach loi (ghi ra file .errors.json rieng).

    Tach khoi file du lieu chinh de so record trong file khop voi so cau convert
    duoc, tranh nguoi dung tuong bi mat cau. Giu lai ham nay (du `main()` nay
    dung `upsert` truc tiep de merge thay vi append) de khong pha vo API cong
    khai `tool.record_error`.
    """
    errors.append(record)


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="ExamTopics Crawler & Converter")
    parser.add_argument("-e", "--exam", help="Ma de (vd: sk0-005, az-104, FCSS_NST_SE-7.6)")
    parser.add_argument("-t", "--topic", type=int, default=None, help="Topic number (mac dinh: 1)")
    parser.add_argument("-r", "--range", help="Pham vi cau (vd: 1-50, 5)")
    parser.add_argument("-p", "--proxy", help="Proxy server URL (vd: http://127.0.0.1:8080 hoac socks5://127.0.0.1:1080)")
    parser.add_argument("-y", "--yes", action="store_true", help="Tu dong convert sang HTML va DOCX sau khi crawl")
    parser.add_argument("--convert-only", help="Duong dan file JSON can convert truc tiep sang HTML va DOCX")
    parser.add_argument("--hide-answers", action="store_true", help="An dap an trong file DOCX (che do tu luyen, dap an chi con o bang Answer Key)")
    parser.add_argument("--headless", action="store_true", help="Chay browser an (khong hien cua so). Dung tren server/CI khong co man hinh; mac dinh la hien de giam CAPTCHA khi search.")
    # Nhom dieu khien muc do log. Mac dinh (khong flag) giu nguyen output nhu cu.
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("-q", "--quiet", action="store_true", help="Chi in canh bao va loi (tat tien do). Hop voi CI hoac khi ghi log ra file.")
    log_group.add_argument("-v", "--verbose", action="store_true", help="In them chi tiet chan doan (retry, cache, tai anh...). Hop voi khi debug.")
    return parser.parse_args()


def main():
    args = parse_args()
    configure_logging(quiet=args.quiet, verbose=args.verbose)

    if args.convert_only:
        json_path = args.convert_only
        if not os.path.exists(json_path):
            LOG.error(f"Loi: Khong tim thay file {json_path}")
            sys.exit(1)
        try:
            convert_to_html(json_path)
            convert_to_docx(json_path, hide_answers=args.hide_answers)
        except Exception as e:
            # Tra ve ma loi khac 0 de script/CI khong tuong nham la thanh cong.
            LOG.error(f"Loi convert: {e}")
            sys.exit(2)
        return

    LOG.info("="*60)
    LOG.info("  CRAWL EXAMTOPICS - BAN LUU LIEN TUC")
    LOG.info("="*60)

    if args.exam:
        exam_code = args.exam.strip()
    else:
        exam_code = input("Nhap ma de (ex200, ex300): ").strip() or "ex200"

    search_code = normalize_exam_code(exam_code) or "exam"
    clean_code = canonical_exam_code(exam_code) or "exam"

    if args.topic is not None:
        topic = max(1, args.topic)
    else:
        topic_str = input("Nhap topic (mac dinh 1): ").strip()
        topic = max(1, int(topic_str)) if topic_str.isdigit() else 1

    if args.range:
        range_input = args.range.strip()
    else:
        range_input = input("Nhap pham vi cau (vd: 1-10, hoac de trong lay 1-120): ").strip()

    if range_input:
        parsed = parse_range(range_input)
        if parsed is None:
            LOG.warning("  Pham vi khong hop le, dung mac dinh 1-120.")
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
    error_filename = f"{clean_code}_errors.json"
    error_path = os.path.join(OUTPUT_DIR, error_filename)

    # Nap lai ban ghi loi cu truoc khi ghi tiep. Neu khong, moi lan chay lai se
    # GHI DE file .errors.json va lam mat am tham danh sach cau loi cua cac lan
    # truoc (nguoc lai voi file du lieu chinh da duoc bao toan).
    error_records = load_all(error_path)
    if error_records:
        LOG.info(f"  Nap san {len(error_records)} ban ghi loi tu output/{error_filename}.")

    all_data = load_all(filepath)
    for rec in all_data:
        if isinstance(rec, dict) and rec.get("url"):
            info = extract_discussion_info(rec.get("url"))
            if info:
                _HARVESTED_LINKS[info] = rec["url"]
    if _HARVESTED_LINKS:
        LOG.info(f"  Nap san {len(_HARVESTED_LINKS)} link discussion tu du lieu cu vao bo nho cache.")

    if args.proxy:
        set_proxy(args.proxy.strip())
        LOG.info(f"  Su dung proxy: {args.proxy.strip()}")

    LOG.info(f"\nCrawl {search_code.upper()}, topic {topic}, cau {start_q}-{end_q}")
    LOG.info("-"*60)

    LOG.info("Khoi dong CloakBrowser...")
    fp_seed = random.randint(10000, 99999)
    browser = launch(
        headless=args.headless,
        humanize=True,
        stealth_args=False,
        proxy=args.proxy.strip() if args.proxy else None,
        args=[
            '--no-sandbox',
            f'--fingerprint={fp_seed}',
            '--fingerprint-platform=macos',
            '--disable-dev-shm-usage',
        ],
    )

    added = 0
    failed = []
    failed_blocked = []
    failed_missing = []
    context = None
    page = None
    try:
        total = end_q - start_q + 1
        context = browser.new_context()
        context.set_default_timeout(DEFAULT_OP_TIMEOUT)
        page = context.new_page()
        sync_browser_session(page)
        LOG.info("Warm-up DuckDuckGo (tao session)...")
        if not warmup_search(page):
            LOG.warning("  Canh bao: khong tai duoc DuckDuckGo, van thu crawl tiep.")
        sync_browser_session(page)

        interrupted = False
        aborted = False
        blocked_streak = 0
        try:
            for qnum in range(start_q, end_q + 1):
                LOG.info(f"\n[{qnum - start_q + 1}/{total}] cau {qnum}")

                result = None
                no_link_reason = ""
                for attempt in range(1, RETRY_LIMIT + 1):
                    result = crawl_one_question(page, search_code, topic, qnum)
                    if result is NO_DISCUSSION_BLOCKED:
                        no_link_reason = ("Khong tim thay link discussion vi search bi "
                                          "chan/CAPTCHA hoac khong truy cap duoc")
                        break
                    if result is NO_DISCUSSION_MISSING:
                        no_link_reason = ("Khong tim thay link discussion vi ca "
                                          "DuckDuckGo va Google da search nhung khong co link dung cau")
                        break
                    if isinstance(result, dict):
                        break
                    LOG.info(f"  That bai lan {attempt}/{RETRY_LIMIT} cho cau {qnum}")
                    if attempt < RETRY_LIMIT:
                        retry_wait = random.uniform(3, 6)
                        LOG.info(f"  -> Thu lai sau {retry_wait:.1f} giay...")
                        time.sleep(retry_wait)

                if result is NO_DISCUSSION_BLOCKED:
                    blocked_streak += 1
                else:
                    blocked_streak = 0

                if isinstance(result, dict):
                    upsert(all_data, result)
                    added += 1
                    LOG.info(f"  Luu cau {qnum} vao output/{filename}")
                else:
                    failed.append(qnum)
                    if result is NO_DISCUSSION_BLOCKED:
                        failed_blocked.append(qnum)
                    elif result is NO_DISCUSSION_MISSING:
                        failed_missing.append(qnum)
                    error_msg = no_link_reason or "Khong lay duoc cau hoi"
                    # So sanh key bang as_int: du lieu cu co the luu topic dang
                    # chuoi, neu so sanh == truc tiep se coi la khac cau va record
                    # loi se ghi de mat cau hoi tot. Xem parser.has_good_data.
                    if not has_good_data(all_data, topic, qnum):
                        # Ghi ban ghi loi ra FILE RIENG (.errors.json), khong tron
                        # vao file du lieu chinh. Neu tron vao, file chinh co N
                        # record nhung convert chi ra it hon -> nguoi dung tuong mat
                        # cau. Ban ghi loi chi de ghi nhan, khong chan crawl lai.
                        LOG.info(f"  KHONG LAY DUOC cau {qnum} -> ghi vao {error_filename} va bo qua")
                        # Dung upsert (khong phai append) de neu cau nay da co ban
                        # ghi loi tu lan chay truoc thi cap nhat tai cho, tranh
                        # trung lap khi chay lai nhieu lan.
                        upsert(error_records, {
                            "exam_code": search_code,
                            "topic": topic,
                            "question_num": qnum,
                            "error": error_msg,
                        })
                    else:
                        LOG.info(f"  Khong lay duoc cau {qnum} nhung giu du lieu tot tu lan truoc.")
                save_progress(all_data, filename)

                if blocked_streak >= BLOCKED_ABORT_STREAK:
                    LOG.info(f"\n[!] Bi chan/CAPTCHA {BLOCKED_ABORT_STREAK} cau lien tiep "
                          f"-> dung phien som. Data da luu an toan, chay lai sau.")
                    aborted = True
                    break

                if qnum < end_q:
                    wait = random.uniform(MIN_DELAY, MAX_DELAY)
                    LOG.info(f"  Nghi {wait:.1f}s truoc cau tiep theo...")
                    time.sleep(wait)
        except KeyboardInterrupt:
            interrupted = True
            LOG.info("\n\n[!] Da dung theo yeu cau nguoi dung (Ctrl+C).")

        LOG.info("\n"+"="*60)
        status_label = "Tam dung!" if interrupted else ("Dung som vi bi chan!" if aborted else "Hoan tat!")
        LOG.info(f"{status_label} Lay duoc {added}/{total} cau trong phien nay (tong file: {len(all_data)}).")
        if failed:
            LOG.info(f"Khong lay duoc {len(failed)} cau: {', '.join(str(q) for q in failed)}")
        if failed_blocked:
            LOG.info(f"  Vi search bi chan/CAPTCHA: {', '.join(map(str, failed_blocked))}")
        if failed_missing:
            LOG.info(f"  Vi thuc su khong co discussion: {', '.join(map(str, failed_missing))}")
        LOG.info(f"Ket qua: output/{filename}")
        if error_records:
            save_progress(error_records, error_filename)
            LOG.info(f"Cau loi ({len(error_records)}) luu rieng tai output/{error_filename}")
        LOG.info("="*60)

        if all_data:
            if args.yes:
                choice = "y"
            else:
                choice = input("\nConvert sang HTML + DOCX? (y/N): ").strip().lower()
            if choice == "y":
                try:
                    convert_to_html(filepath)
                    convert_to_docx(filepath, hide_answers=args.hide_answers)
                except Exception as e:
                    LOG.info(f"  Loi convert: {e}")
    finally:
        safe_close(page)
        safe_close(context)
        safe_close(browser)

if __name__ == "__main__":
    main()
