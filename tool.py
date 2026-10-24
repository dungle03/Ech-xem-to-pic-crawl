import os
import sys
import random
import time
from cloakbrowser import launch

from examtopic import (
    LOG,
    resolver,
    configure_logging,
    MIN_DELAY,
    MAX_DELAY,
    RETRY_LIMIT,
    BLOCKED_ABORT_STREAK,
    SECOND_PASS_ATTEMPTS,
    SECOND_PASS_DELAY,
    OUTPUT_DIR,
    DEFAULT_OP_TIMEOUT,
    NO_DISCUSSION_BLOCKED,
    NO_DISCUSSION_MISSING,
    NO_DISCUSSION_GATED,
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
    forget_harvested_link,
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
    "SECOND_PASS_ATTEMPTS",
    "SECOND_PASS_DELAY",
    "OUTPUT_DIR",
    "LOG",
    "configure_logging",
    "DEFAULT_OP_TIMEOUT",
    "NO_DISCUSSION_BLOCKED",
    "NO_DISCUSSION_MISSING",
    "NO_DISCUSSION_GATED",
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
    "forget_harvested_link",
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
    "second_pass",
    "main",
]

def _same_question(record, topic, qnum):
    """Ban ghi (loi) nay co phai cua dung (topic, question_num) khong.

    So sanh qua as_int vi du lieu cu co the luu topic/question_num dang chuoi;
    so sanh == truc tiep se coi la khac cau roi giu lai ban ghi loi da cu.
    """
    if not isinstance(record, dict):
        return False
    return (as_int(record.get("question_num"), -1) == qnum
            and as_int(record.get("topic"), 1) == topic)


def record_error(record, errors):
    """Them mot ban ghi loi vao danh sach loi (ghi ra file .errors.json rieng).

    Tach khoi file du lieu chinh de so record trong file khop voi so cau convert
    duoc, tranh nguoi dung tuong bi mat cau. Giu lai ham nay (du `main()` nay
    dung `upsert` truc tiep de merge thay vi append) de khong pha vo API cong
    khai `tool.record_error`.
    """
    errors.append(record)


def second_pass(page, search_code, topic, retry_qs, all_data, filename,
                failed, failed_blocked, failed_missing, failed_gated,
                error_records, attempts=None, delay=None):
    """Thu lai cac cau that bai voi toc do CHAM. Tra ve danh sach cau phuc hoi.

    Vi sao can: do tren trang that, 404 doi khi chi la chan TAM thoi chu khong
    phai cau bi go vinh vien -- q32 hqt-4180 va 29 cau ccdak tra 404 luc tai
    cao, roi 200 khi tai giam. Crawl chinh chay nhanh nen de "rot" cac cau nay;
    second pass chay cham de bat lai.

    Xoa `_DEAD_URLS` truoc khi chay: khong co buoc nay thi no se bo qua dung
    nhung cau 404 vua roi, tuc la khong thu lai cau nao ca.

    Cac list `failed*` va `error_records` duoc sua TAI CHO de caller thay ket qua.
    """
    attempts = SECOND_PASS_ATTEMPTS if attempts is None else attempts
    delay = SECOND_PASS_DELAY if delay is None else delay
    recovered = []
    if not retry_qs or attempts <= 0:
        return recovered

    LOG.info("\n" + "="*60)
    LOG.info(f"SECOND PASS: thu lai {len(retry_qs)} cau that bai "
             f"(toc do cham, {attempts} lan)...")
    LOG.info("="*60)
    try:
        resolver.clear_dead_urls()
    except Exception:
        pass

    for idx, qnum in enumerate(retry_qs, 1):
        LOG.info(f"\n[second pass {idx}/{len(retry_qs)}] cau {qnum}")
        time.sleep(delay)  # nghi cham de tai thuc su ha xuong
        result = None
        for attempt in range(1, attempts + 1):
            result = crawl_one_question(page, search_code, topic, qnum)
            if isinstance(result, dict):
                break
            if result in (NO_DISCUSSION_BLOCKED, NO_DISCUSSION_MISSING,
                          NO_DISCUSSION_GATED):
                break
            if attempt < attempts:
                time.sleep(delay)
        if not isinstance(result, dict):
            continue
        upsert(all_data, result)
        recovered.append(qnum)
        if qnum in failed:
            failed.remove(qnum)
        for lst in (failed_blocked, failed_missing, failed_gated):
            if qnum in lst:
                lst.remove(qnum)
        kept = [r for r in error_records if not _same_question(r, topic, qnum)]
        if len(kept) != len(error_records):
            error_records[:] = kept
        save_progress(all_data, filename)
        LOG.info(f"  [second pass] Lay duoc cau {qnum} (truoc day that bai).")

    if recovered:
        LOG.info(f"\n[second pass] Phuc hoi them {len(recovered)} cau: "
                 f"{', '.join(map(str, recovered))}")
    return recovered


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
    parser.add_argument("--wait-on-captcha", action="store_true", help="Khi search gap CAPTCHA, dem 30 giay roi tu kiem tra lai; lap lai den khi CAPTCHA duoc xu ly.")
    # Nhom dieu khien muc do log. Mac dinh (khong flag) giu nguyen output nhu cu.
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("-q", "--quiet", action="store_true", help="Chi in canh bao va loi (tat tien do). Hop voi CI hoac khi ghi log ra file.")
    log_group.add_argument("-v", "--verbose", action="store_true", help="In them chi tiet chan doan (retry, cache, tai anh...). Hop voi khi debug.")
    return parser.parse_args()


def main():
    args = parse_args()
    configure_logging(quiet=args.quiet, verbose=args.verbose)

    if args.wait_on_captcha and args.headless:
        LOG.error("--wait-on-captcha can only be used with a visible browser; remove --headless.")
        sys.exit(2)
    if args.wait_on_captcha:
        from examtopic import config as app_config
        app_config.WAIT_ON_CAPTCHA = True

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
    error_records_loaded = bool(error_records)
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
    failed_gated = []
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

        # Nap chi muc URL discussion tu trang liet ke cua vendor (thay cho
        # "anchor question_id" cua ban cu, da chet vi `data-id` nay la hang so).
        # Loi o buoc nay khong lam dung phien: khong co chi muc thi tool quay ve
        # dung search nhu truoc.
        LOG.info("Nap chi muc URL discussion (vendor listing)...")
        try:
            resolver.load_index()
            resolver.seed_from_exam_page(search_code)
            # Dap an chinh thuc tu trang exam (chi q1..q10 mien phi) - nguon dang
            # tin nhat, uu tien hon viec suy tu binh luan.
            resolver.exam_answer_key(search_code)
        except Exception as e:
            LOG.warning(f"  Khong nap duoc chi muc URL: {e}")

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
                    if result is NO_DISCUSSION_GATED:
                        no_link_reason = ("Link tim duoc tra HTTP 404 (bi go/paywall, "
                                          "hoac chan tam; second pass se thu lai cham)")
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
                    # Xoa ban ghi loi cu cua chinh cau nay: lan truoc khong lay duoc
                    # (vd search bo sot link) nhung lan nay da lay duoc. Khong xoa thi
                    # file .errors.json vinh vien bao cau da lay duoc la loi.
                    kept = [r for r in error_records if not _same_question(r, topic, qnum)]
                    if len(kept) != len(error_records):
                        error_records[:] = kept
                        LOG.info(f"  Da xoa ban ghi loi cu cua cau {qnum} khoi {error_filename}")
                else:
                    failed.append(qnum)
                    if result is NO_DISCUSSION_BLOCKED:
                        failed_blocked.append(qnum)
                    elif result is NO_DISCUSSION_MISSING:
                        failed_missing.append(qnum)
                    elif result is NO_DISCUSSION_GATED:
                        failed_gated.append(qnum)
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

        # SECOND PASS: thu lai cac cau that bai voi toc do CHAM (xem docstring
        # `second_pass`). Bo qua khi nguoi dung Ctrl+C, khi khong co cau nao
        # that bai, hoac khi SECOND_PASS_ATTEMPTS=0.
        if not interrupted and failed and SECOND_PASS_ATTEMPTS > 0:
            retry_qs = [q for q in failed if q not in failed_blocked]
            newly = second_pass(
                page, search_code, topic, retry_qs, all_data, filename,
                failed, failed_blocked, failed_missing, failed_gated,
                error_records,
            )
            added += len(newly)

        LOG.info("\n"+"="*60)
        status_label = "Tam dung!" if interrupted else ("Dung som vi bi chan!" if aborted else "Hoan tat!")
        LOG.info(f"{status_label} Lay duoc {added}/{total} cau trong phien nay (tong file: {len(all_data)}).")
        if failed:
            LOG.info(f"Khong lay duoc {len(failed)} cau: {', '.join(str(q) for q in failed)}")
        if failed_blocked:
            LOG.info(f"  Vi search bi chan/CAPTCHA: {', '.join(map(str, failed_blocked))}")
        if failed_missing:
            # Khong khang dinh "thuc su khong co discussion": search engine co the
            # bo sot (da gap that voi ccaak cau 108/98/85...). Chi bao dung su that
            # la khong tim thay link nao khop cau.
            LOG.info(f"  Vi khong tim thay link discussion khop cau: {', '.join(map(str, failed_missing))}")
        if failed_gated:
            # Link tim duoc tra 404. Phan lon la cau bi go/paywall, NHUNG mot so
            # co the chi bi chan tam (da do duoc: 404 roi sau do 200). Second
            # pass o tren da thu lai mot lan cham; neu van 404 thi kha nang cao
            # la cau da bi go that.
            LOG.info(f"  Vi link tra HTTP 404 (bi go/paywall, hoac chan tam da thu lai o second pass): "
                     f"{', '.join(map(str, failed_gated))}")
        LOG.info(f"Ket qua: output/{filename}")
        # Ghi ca khi danh sach loi rong: neu lan nay da lay duoc het cac cau tung
        # loi thi file .errors.json phai duoc rong theo, khong giu lai ban ghi cu.
        if error_records or error_records_loaded:
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
