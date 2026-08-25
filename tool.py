import time
import json
import os
import re
import random
import html
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
    return html.escape(str(text or ""), quote=True)


def build_html(questions, exam_code):
    parts = []
    exam_payload = json.dumps(questions, ensure_ascii=False).replace("</", "<\\/")
    nav_items = []
    for index, question in enumerate(questions, 1):
        number = question.get("question_num", index)
        question_key = f"{question.get('topic', 1)}:{number}"
        nav_items.append(
            f'<a href="#q-{index}" data-key="{escape_html(question_key)}" '
            f'aria-label="Go to question {escape_html(number)}">{escape_html(number)}</a>'
        )

    css = r""":root {
    --bg: #f7f7fb;
    --surface: #ffffff;
    --surface-soft: #f1f1f7;
    --text: #181825;
    --muted: #626275;
    --border: #dedee8;
    --primary: #6941c6;
    --primary-hover: #5934ad;
    --primary-soft: #f1ecff;
    --success: #117a62;
    --success-soft: #e9f8f3;
    --danger: #b8324b;
    --danger-soft: #fff0f3;
    --warning: #9a5b13;
    --header: rgba(247, 247, 251, .92);
    --shadow: 0 16px 42px -34px rgba(26, 24, 48, .55);
    color-scheme: light;
}
@media (prefers-color-scheme: dark) {
    :root {
        --bg: #101018;
        --surface: #191923;
        --surface-soft: #22222f;
        --text: #f4f2fa;
        --muted: #b2aec1;
        --border: #343343;
        --primary: #a88bfa;
        --primary-hover: #b9a3ff;
        --primary-soft: #2a2440;
        --success: #69d6b4;
        --success-soft: #17372f;
        --danger: #ff8799;
        --danger-soft: #40222a;
        --warning: #f2bd70;
        --header: rgba(16, 16, 24, .9);
        --shadow: 0 18px 48px -34px rgba(0, 0, 0, .9);
        color-scheme: dark;
    }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 84px; }
body {
    min-height: 100vh; margin: 0; color: var(--text); background: var(--bg);
    font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
}
button, input, summary { font: inherit; }
button, label, summary, a { touch-action: manipulation; }
button, summary { cursor: pointer; }
a { color: inherit; }
.hidden, [hidden] { display: none !important; }
.skip-link {
    position: fixed; top: 8px; left: 8px; z-index: 100; padding: 10px 14px;
    border-radius: 10px; background: var(--text); color: var(--bg); transform: translateY(-150%);
}
.skip-link:focus { transform: translateY(0); }
:is(button, input, summary, a):focus-visible {
    outline: 3px solid var(--primary); outline-offset: 3px;
}
.topbar {
    position: sticky; top: 0; z-index: 50; border-bottom: 1px solid var(--border);
    background: var(--header); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
}
.topbar-inner {
    width: min(1180px, calc(100% - 32px)); min-height: 64px; margin: auto;
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.brand-mark {
    width: 36px; height: 36px; display: grid; place-items: center; flex: 0 0 auto;
    border-radius: 10px; background: var(--primary); color: white; font-weight: 850; letter-spacing: -.03em;
}
.brand-copy { display: grid; min-width: 0; line-height: 1.15; }
.brand-copy strong { font-size: .93rem; white-space: nowrap; }
.brand-copy small { color: var(--muted); font-size: .75rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mode-switch {
    display: flex; flex: 0 0 auto; gap: 4px; padding: 4px; border: 1px solid var(--border);
    border-radius: 12px; background: var(--surface-soft);
}
.mode-btn, .button, .review-btn, .answer-reveal {
    min-height: 44px; border: 1px solid transparent; border-radius: 10px; padding: 9px 14px;
    background: transparent; color: var(--muted); font-weight: 700;
    transition: background-color .18s ease, border-color .18s ease, color .18s ease, box-shadow .18s ease;
}
.mode-btn { white-space: nowrap; }
.mode-btn:hover, .button:hover, .review-btn:hover, .answer-reveal:hover { color: var(--text); border-color: var(--border); }
.mode-btn.active { background: var(--surface); color: var(--primary); box-shadow: var(--shadow); }
.button { background: var(--surface); border-color: var(--border); color: var(--text); }
.button.primary { background: var(--primary); border-color: var(--primary); color: white; }
.button.primary:hover { background: var(--primary-hover); border-color: var(--primary-hover); color: white; }
.study-shell {
    width: min(1180px, calc(100% - 32px)); margin: 32px auto 72px;
    display: grid; grid-template-columns: 264px minmax(0, 780px); justify-content: center; gap: 32px;
}
.study-sidebar { position: sticky; top: 88px; align-self: start; display: grid; gap: 16px; max-height: calc(100vh - 108px); overflow: auto; padding: 2px; }
.panel, .question-card, .setup-card, .result-card {
    border: 1px solid var(--border); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow);
}
.panel { padding: 18px; }
.eyebrow { margin: 0 0 8px; color: var(--primary); font-size: .72rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 8px; font-size: clamp(1.7rem, 4vw, 2.35rem); line-height: 1.05; letter-spacing: -.045em; overflow-wrap: anywhere; }
h2 { margin-bottom: 8px; font-size: clamp(1.35rem, 3vw, 1.75rem); line-height: 1.2; letter-spacing: -.025em; }
.summary-copy, .page-intro p, .setup-card > p, .result-copy { margin-bottom: 0; color: var(--muted); }
.summary-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 18px; }
.summary-stat { padding: 12px; border-radius: 12px; background: var(--surface-soft); }
.summary-stat strong { display: block; font-size: 1.2rem; line-height: 1.15; font-variant-numeric: tabular-nums; }
.summary-stat span { color: var(--muted); font-size: .76rem; }
.tool-panel { display: grid; gap: 14px; }
.field { display: grid; gap: 7px; color: var(--muted); font-size: .8rem; font-weight: 750; }
.field input[type="search"], .field input[type="number"] {
    width: 100%; min-height: 44px; border: 1px solid var(--border); border-radius: 10px;
    padding: 0 12px; background: var(--bg); color: var(--text); outline: none;
}
.field input:focus { border-color: var(--primary); }
.filter-check {
    min-height: 44px; display: flex; align-items: center; gap: 10px; padding: 9px 11px;
    border: 1px solid var(--border); border-radius: 10px; background: var(--surface); color: var(--text); cursor: pointer;
}
input[type="checkbox"], input[type="radio"] { accent-color: var(--primary); }
.tool-panel .button { width: 100%; text-align: left; }
.question-picker { border-top: 1px solid var(--border); padding-top: 14px; }
.question-picker summary { min-height: 44px; display: flex; align-items: center; justify-content: space-between; font-size: .84rem; font-weight: 800; }
.question-picker summary::after { content: "+"; color: var(--muted); }
.question-picker[open] summary::after { content: "−"; }
.question-nav { display: grid; grid-template-columns: repeat(auto-fill, minmax(40px, 1fr)); gap: 7px; padding-top: 10px; }
.question-nav a {
    min-height: 40px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 9px;
    color: var(--muted); text-decoration: none; font-size: .78rem; font-weight: 750; font-variant-numeric: tabular-nums;
}
.question-nav a:hover { border-color: var(--primary); color: var(--primary); }
.question-nav a.needs-review { border-color: var(--danger); color: var(--danger); }
.question-nav a.active { border-color: var(--primary); background: var(--primary); color: white; }
.study-content { min-width: 0; }
.page-intro { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.page-intro p { max-width: 56ch; }
.visible-status { flex: 0 0 auto; color: var(--muted); font-size: .82rem; font-weight: 750; font-variant-numeric: tabular-nums; }
.question-list { display: grid; gap: 16px; }
.question-card { padding: clamp(20px, 3vw, 28px); scroll-margin-top: 84px; page-break-inside: avoid; }
.question-card.needs-review { border-left: 4px solid var(--danger); }
.q-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.q-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.q-num, .answer-chip, .status-badge {
    min-height: 30px; display: inline-flex; align-items: center; padding: 4px 10px;
    border-radius: 999px; font-size: .76rem; font-weight: 800; white-space: nowrap;
}
.q-num { background: var(--primary-soft); color: var(--primary); }
.answer-chip { position: relative; background: var(--surface-soft); color: var(--muted); }
.review-btn { min-height: 38px; padding: 7px 10px; display: inline-flex; align-items: center; gap: 7px; border-color: var(--border); background: var(--surface); color: var(--muted); font-size: .78rem; }
.review-dot { width: 8px; height: 8px; border: 2px solid currentColor; border-radius: 50%; }
.review-btn[aria-pressed="true"] { border-color: var(--danger); background: var(--danger-soft); color: var(--danger); }
.review-btn[aria-pressed="true"] .review-dot { background: currentColor; }
.q-text { max-width: 74ch; margin-bottom: 0; font-size: 1.02rem; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.q-images { display: grid; gap: 12px; margin-top: 18px; }
.q-images img, .option-copy img {
    display: block; max-width: 100%; height: auto; margin-top: 10px;
    border: 1px solid var(--border); border-radius: 12px; background: white;
}
.options { list-style: none; margin: 20px 0 0; padding: 0; display: grid; gap: 9px; }
.options li {
    min-width: 0; display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px;
    border: 1px solid var(--border); border-radius: 12px; background: var(--surface-soft); line-height: 1.55;
}
.opt-letter {
    width: 30px; height: 30px; display: grid; place-items: center; flex: 0 0 auto;
    border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--primary); font-weight: 850;
}
.option-copy { min-width: 0; flex: 1; overflow-wrap: anywhere; }
.correct-badge, .option-result { display: inline-flex; align-items: center; min-height: 24px; margin-left: 9px; padding: 2px 8px; border-radius: 999px; font-size: .7rem; font-weight: 800; }
.correct-badge { background: var(--success); color: white; }
.options li.correct, .options li.right { border-color: var(--success); background: var(--success-soft); }
.options li.wrong-choice { border-color: var(--danger); background: var(--danger-soft); }
.option-result.right { background: var(--success); color: white; }
.option-result.wrong { background: var(--danger); color: white; }
.option-label { min-width: 0; flex: 1; display: flex; align-items: flex-start; gap: 11px; cursor: pointer; }
.option-label input { width: 20px; height: 20px; flex: 0 0 auto; margin-top: 5px; cursor: pointer; }
.options li.chosen { border-color: var(--primary); background: var(--primary-soft); }
.study-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border); }
.answer-reveal { border-color: var(--border); background: var(--surface); color: var(--primary); font-size: .8rem; }
.source-link { min-height: 44px; display: inline-flex; align-items: center; padding: 9px 2px; color: var(--muted); font-size: .8rem; font-weight: 750; text-underline-offset: 3px; }
.discussion { margin-top: 14px; border-top: 1px solid var(--border); }
.discussion summary { min-height: 46px; display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--muted); font-size: .82rem; font-weight: 800; }
.discussion summary span { padding: 2px 8px; border-radius: 999px; background: var(--surface-soft); font-variant-numeric: tabular-nums; }
.comment { padding: 12px 14px; margin: 0 0 9px; border-left: 3px solid var(--primary); border-radius: 4px 10px 10px 4px; background: var(--surface-soft); color: var(--muted); font-size: .88rem; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
.error-tag { display: inline-block; margin-top: 14px; padding: 7px 10px; border-radius: 9px; background: var(--danger-soft); color: var(--danger); font-size: .8rem; font-weight: 750; }
body.answers-hidden .study-content .question-card:not(.revealed) .answer-chip .answer-prefix,
body.answers-hidden .study-content .question-card:not(.revealed) .answer-chip .answer-value { display: none; }
body.answers-hidden .study-content .question-card:not(.revealed) .answer-chip::after { content: "Answer hidden"; }
body.answers-hidden .study-content .question-card:not(.revealed) .options li.correct { border-color: var(--border); background: var(--surface-soft); }
body.answers-hidden .study-content .question-card:not(.revealed) .correct-badge,
body.answers-hidden .study-content .question-card:not(.revealed) .discussion { display: none; }
body:not(.answers-hidden) .answer-reveal { display: none; }
.empty-state { padding: 32px; border: 1px dashed var(--border); border-radius: 16px; text-align: center; color: var(--muted); }
.exam-shell { width: min(820px, calc(100% - 32px)); margin: 32px auto 72px; }
.setup-card, .result-card { padding: clamp(22px, 4vw, 34px); }
.setup-card > p { margin-bottom: 22px; max-width: 62ch; }
.setup-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.setup-grid .button { align-self: end; }
.checkbox-field { min-height: 44px; display: flex; align-items: center; gap: 10px; padding: 9px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg); cursor: pointer; }
#exam-area { display: grid; gap: 16px; }
.timer {
    position: sticky; top: 78px; z-index: 20; min-height: 48px; display: grid; place-items: center;
    border: 1px solid var(--border); border-radius: 12px; background: var(--surface); box-shadow: var(--shadow);
    font-weight: 800; font-variant-numeric: tabular-nums;
}
.timer.warning { border-color: var(--danger); color: var(--danger); }
.submit-row { position: sticky; bottom: 0; z-index: 20; display: flex; justify-content: center; padding: 14px; background: linear-gradient(transparent, var(--bg) 30%); }
.submit-row .button { min-width: 220px; }
.result-card { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 28px; }
.score-ring {
    width: 150px; aspect-ratio: 1; display: grid; place-items: center; border-radius: 50%;
    background: conic-gradient(var(--success) var(--score), var(--surface-soft) 0); position: relative;
}
.score-ring::after { content: ""; position: absolute; width: 116px; aspect-ratio: 1; border-radius: 50%; background: var(--surface); }
.score-ring div { position: relative; z-index: 1; text-align: center; }
.score-ring strong { display: block; font-size: 2rem; line-height: 1; letter-spacing: -.04em; }
.score-ring span { color: var(--muted); font-size: .76rem; }
.result-stats { display: flex; gap: 14px; flex-wrap: wrap; margin: 18px 0 0; }
.result-stats span { color: var(--muted); font-size: .86rem; }
.result-stats strong { color: var(--text); }
.result-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 20px; }
.answer-line { margin: 16px 0 0; color: var(--muted); font-size: .88rem; }
.status-badge.pass { background: var(--success-soft); color: var(--success); }
.status-badge.fail { background: var(--danger-soft); color: var(--danger); }
@media (max-width: 860px) {
    .study-shell { grid-template-columns: minmax(0, 780px); gap: 22px; }
    .study-sidebar { position: static; max-height: none; overflow: visible; }
    .tool-panel { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: end; }
    .question-picker { grid-column: 1 / -1; }
}
@media (max-width: 600px) {
    html { scroll-padding-top: 74px; }
    .topbar-inner, .study-shell, .exam-shell { width: min(100% - 24px, 780px); }
    .topbar-inner { min-height: 58px; }
    .brand-copy { display: none; }
    .mode-btn { min-width: 76px; min-height: 40px; padding: 7px 10px; }
    .study-shell, .exam-shell { margin-top: 20px; }
    .tool-panel, .setup-grid { grid-template-columns: 1fr; }
    .page-intro { display: block; }
    .visible-status { display: block; margin-top: 10px; }
    .question-card { padding: 18px; scroll-margin-top: 74px; }
    .q-head { align-items: flex-start; }
    .review-btn { min-height: 40px; }
    .options li { padding: 11px; }
    .result-card { grid-template-columns: 1fr; justify-items: center; text-align: center; }
    .result-actions, .result-stats { justify-content: center; }
    .timer { top: 68px; }
}
@media (prefers-reduced-motion: reduce) {
    html { scroll-behavior: auto; }
    *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
}
@media print {
    :root { color-scheme: light; }
    body { background: white; color: black; }
    .topbar, .study-sidebar, #exam-setup, #exam-area, .study-actions, .discussion { display: none !important; }
    .study-shell { display: block; width: 100%; margin: 0; }
    .page-intro { display: block; }
    .question-card { box-shadow: none; break-inside: avoid; }
    body.answers-hidden .study-content .question-card .answer-chip .answer-prefix,
    body.answers-hidden .study-content .question-card .answer-chip .answer-value,
    body.answers-hidden .study-content .question-card .correct-badge { display: inline-flex !important; }
    body.answers-hidden .study-content .question-card .answer-chip::after { content: none; }
    body.answers-hidden .study-content .question-card .options li.correct { border-color: var(--success); background: var(--success-soft); }
}"""

    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{escape_html(exam_code.upper())} - Study</title>
<style>{css}</style>
</head>
<body class="answers-hidden" data-exam-code="{escape_html(exam_code)}">
<a class="skip-link" href="#main-content">Skip to main content</a>
<header class="topbar">
<div class="topbar-inner">
<div class="brand">
<span class="brand-mark" aria-hidden="true">DR</span>
<span class="brand-copy"><strong>Dump Review</strong><small>{escape_html(exam_code.upper())}</small></span>
</div>
<nav class="mode-switch" aria-label="Study mode">
<button id="study-mode" class="mode-btn active" type="button" aria-pressed="true">Study</button>
<button id="exam-mode" class="mode-btn" type="button" aria-pressed="false">Mock exam</button>
</nav>
</div>
</header>
<main id="main-content" tabindex="-1">
<section id="study-shell" class="study-shell">
<aside class="study-sidebar" aria-label="Study tools">
<section class="panel">
<p class="eyebrow">Question set</p>
<h1>{escape_html(exam_code.upper())}</h1>
<p class="summary-copy">Review actively, flag uncertain questions, and return to what needs work.</p>
<div class="summary-grid">
<div class="summary-stat"><strong>{len(questions)}</strong><span>Questions</span></div>
<div class="summary-stat"><strong id="review-count">0</strong><span>Review</span></div>
</div>
</section>
<section class="panel tool-panel">
<label class="field" for="question-search">Search questions
<input id="question-search" type="search" placeholder="Number or keyword" autocomplete="off">
</label>
<button id="toggle-answers" class="button" type="button" aria-pressed="false">Show all answers</button>
<label class="filter-check" for="only-review"><input id="only-review" type="checkbox"> Review only</label>
<button id="clear-reviews" class="button" type="button">Clear all reviews</button>
<details class="question-picker">
<summary>Jump to question</summary>
<nav class="question-nav" aria-label="Question list">{''.join(nav_items)}</nav>
</details>
</section>
</aside>
<section class="study-content" aria-labelledby="study-title">
<header class="page-intro">
<div>
<p class="eyebrow">Study mode</p>
<h2 id="study-title">Answer first, reveal later</h2>
<p>Answers stay hidden by default to encourage active recall. Missed exam questions are added to your review list.</p>
</div>
<span id="visible-status" class="visible-status" role="status" aria-live="polite">{len(questions)} / {len(questions)} questions</span>
</header>
<div id="question-list" class="question-list">
""")

    for index, question in enumerate(questions, 1):
        number = question.get("question_num", index)
        question_key = f"{question.get('topic', 1)}:{number}"
        question_text = escape_html(question.get("question", ""))
        suggested = question.get("suggested_answers", [])
        answer_text = ", ".join(suggested) if suggested else "Unavailable"
        raw_search = " ".join(" ".join([
            str(number),
            question.get("question", ""),
            *[option.get("text", "") for option in question.get("options", [])],
        ]).split()).lower()

        image_html = "".join(
            f'<img src="{escape_html(url)}" alt="Illustration for question {escape_html(number)}" loading="lazy">'
            for url in question.get("question_images", [])
        )

        options_html = []
        for option in question.get("options", []):
            letter = option.get("letter", "")
            correct = option.get("is_correct", False)
            option_images = "".join(
                f'<img src="{escape_html(url)}" alt="Illustration for answer {escape_html(letter)}" loading="lazy">'
                for url in option.get("images", [])
            )
            badge = '<span class="correct-badge">Correct answer</span>' if correct else ""
            options_html.append(
                f'<li class="{"correct" if correct else ""}">'
                f'<span class="opt-letter">{escape_html(letter)}</span>'
                f'<span class="option-copy">{escape_html(option.get("text", ""))}{badge}{option_images}</span>'
                '</li>'
            )

        comments_html = ""
        comments = question.get("answers", [])
        if comments:
            comment_items = "".join(f'<div class="comment">{escape_html(comment)}</div>' for comment in comments)
            comments_html = (
                f'<details class="discussion"><summary>Community discussion <span>{len(comments)}</span></summary>'
                f'<div>{comment_items}</div></details>'
            )

        error_html = ""
        if question.get("error"):
            error_html = f'<div class="error-tag">Data error: {escape_html(question["error"])}</div>'

        source_html = ""
        if question.get("url"):
            source_html = (
                f'<a class="source-link" href="{escape_html(question["url"])}" target="_blank" '
                'rel="noopener noreferrer">Open source page</a>'
            )

        parts.append(f"""
<article class="question-card" id="q-{index}" data-study-question data-key="{escape_html(question_key)}" data-search="{escape_html(raw_search)}">
<header class="q-head">
<div class="q-meta">
<span class="q-num">Question {escape_html(number)}</span>
<span class="answer-chip"><span class="answer-prefix">Answer: </span><span class="answer-value">{escape_html(answer_text)}</span></span>
</div>
<button class="review-btn" type="button" data-action="toggle-review" data-key="{escape_html(question_key)}" aria-pressed="false" aria-label="Mark question {escape_html(number)} for review">
<span class="review-dot" aria-hidden="true"></span><span data-review-label>Review</span>
</button>
</header>
<p class="q-text">{question_text}</p>
{'<div class="q-images">' + image_html + '</div>' if image_html else ''}
<ul class="options">{''.join(options_html)}</ul>
{error_html}
<div class="study-actions">
<button class="answer-reveal" type="button" data-action="toggle-answer" aria-expanded="false">Show answer</button>
{source_html}
</div>
{comments_html}
</article>""")

    parts.append(f"""
</div>
<div id="empty-state" class="empty-state hidden">No matching questions. Try another keyword or clear the filter.</div>
</section>
</section>
<section id="exam-setup" class="exam-shell setup-card hidden" aria-labelledby="exam-title">
<p class="eyebrow">Mock exam</p>
<h1 id="exam-title">Build a quick practice session</h1>
<p>Choose the question count and time limit. Results are graded instantly, and missed questions are added to your review list.</p>
<div class="setup-grid">
<label class="field" for="exam-count">Number of questions<input id="exam-count" type="number" min="1" value="20" inputmode="numeric"></label>
<label class="field" for="exam-minutes">Time limit (minutes)<input id="exam-minutes" type="number" min="1" value="60" inputmode="numeric"></label>
<label class="checkbox-field" for="exam-shuffle"><input id="exam-shuffle" type="checkbox" checked> Shuffle questions</label>
<button id="start-exam" class="button primary" type="button">Start exam</button>
</div>
</section>
<section id="exam-area" class="exam-shell hidden" aria-live="polite"></section>
</main>
<script id="exam-data" type="application/json">{exam_payload}</script>
""")
    parts.append(r"""<script>
const questions = JSON.parse(document.getElementById('exam-data').textContent);
const examCode = document.body.dataset.examCode || 'exam';
const storageKey = `examtopic-wrong:${examCode}`;
const studyMode = document.getElementById('study-mode');
const examMode = document.getElementById('exam-mode');
const studyShell = document.getElementById('study-shell');
const setup = document.getElementById('exam-setup');
const area = document.getElementById('exam-area');
const questionList = document.getElementById('question-list');
const studyCards = [...document.querySelectorAll('[data-study-question]')];
const navLinks = [...document.querySelectorAll('.question-nav a')];
const navByKey = new Map(navLinks.map(link => [link.dataset.key, link]));
const searchInput = document.getElementById('question-search');
const onlyReview = document.getElementById('only-review');
const toggleAnswers = document.getElementById('toggle-answers');
const visibleStatus = document.getElementById('visible-status');
const reviewCount = document.getElementById('review-count');
const emptyState = document.getElementById('empty-state');
const questionPicker = document.querySelector('.question-picker');
const clearReviewsBtn = document.getElementById('clear-reviews');
let examQuestions = [];
let examDuration = 0;
let timerId = null;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function getReviewKeys() {
  try { return new Set(JSON.parse(localStorage.getItem(storageKey) || '[]')); }
  catch { return new Set(); }
}

function saveReviewKeys(keys) {
  try { localStorage.setItem(storageKey, JSON.stringify([...keys].sort())); }
  catch {}
}

function questionKey(question) {
  return `${question.topic || 1}:${question.question_num}`;
}

function images(urls, alt) {
  return (urls || []).map(url => `<img src="${esc(url)}" alt="${esc(alt)}" loading="lazy">`).join('');
}

function comments(list) {
  if (!list || !list.length) return '';
  return `<details class="discussion"><summary>Community discussion <span>${list.length}</span></summary><div>${
    list.map(comment => `<div class="comment">${esc(comment)}</div>`).join('')
  }</div></details>`;
}

function setMode(mode) {
  const exam = mode === 'exam';
  studyMode.classList.toggle('active', !exam);
  examMode.classList.toggle('active', exam);
  studyMode.setAttribute('aria-pressed', String(!exam));
  examMode.setAttribute('aria-pressed', String(exam));
  studyShell.classList.toggle('hidden', exam);
  setup.classList.toggle('hidden', !exam);
  area.classList.add('hidden');
  area.innerHTML = '';
  stopTimer();
  if (!exam) applyStudyFilters();
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
}

function syncReviewState(keys) {
  studyCards.forEach(card => {
    const marked = keys.has(card.dataset.key);
    card.classList.toggle('needs-review', marked);
    const button = card.querySelector('[data-action="toggle-review"]');
    button.setAttribute('aria-pressed', String(marked));
    button.querySelector('[data-review-label]').textContent = marked ? 'Marked' : 'Review';
    navByKey.get(card.dataset.key)?.classList.toggle('needs-review', marked);
  });
  reviewCount.textContent = keys.size;
}

function applyStudyFilters() {
  const query = searchInput.value.trim().toLocaleLowerCase('vi').replace(/\s+/g, ' ');
  const reviewKeys = getReviewKeys();
  let visible = 0;
  syncReviewState(reviewKeys);
  studyCards.forEach(card => {
    const matchesSearch = !query || card.dataset.search.includes(query);
    const matchesReview = !onlyReview.checked || reviewKeys.has(card.dataset.key);
    const show = matchesSearch && matchesReview;
    card.classList.toggle('hidden', !show);
    navByKey.get(card.dataset.key)?.toggleAttribute('hidden', !show);
    if (show) visible += 1;
  });
  visibleStatus.textContent = `${visible} / ${studyCards.length} questions`;
  emptyState.classList.toggle('hidden', visible !== 0);
}

function setAllAnswers(show) {
  document.body.classList.toggle('answers-hidden', !show);
  toggleAnswers.setAttribute('aria-pressed', String(show));
  toggleAnswers.textContent = show ? 'Hide all answers' : 'Show all answers';
  if (!show) {
    studyCards.forEach(card => {
      card.classList.remove('revealed');
      const button = card.querySelector('[data-action="toggle-answer"]');
      button.setAttribute('aria-expanded', 'false');
      button.textContent = 'Show answer';
    });
  }
}

function toggleQuestionAnswer(button) {
  const card = button.closest('.question-card');
  const show = !card.classList.contains('revealed');
  card.classList.toggle('revealed', show);
  button.setAttribute('aria-expanded', String(show));
  button.textContent = show ? 'Hide answer' : 'Show answer';
}

function toggleReviewQuestion(button) {
  const keys = getReviewKeys();
  if (keys.has(button.dataset.key)) keys.delete(button.dataset.key);
  else keys.add(button.dataset.key);
  saveReviewKeys(keys);
  applyStudyFilters();
}

function startExam() {
  const pool = questions.filter(question => question.options?.length && question.suggested_answers?.length);
  if (!pool.length) return alert('No questions are eligible for the mock exam.');
  const countInput = document.getElementById('exam-count');
  const minutesInput = document.getElementById('exam-minutes');
  const count = Math.max(1, Math.min(pool.length, Number(countInput.value) || pool.length));
  examDuration = Math.max(1, Number(minutesInput.value) || 60) * 60;
  examQuestions = [...pool];
  if (document.getElementById('exam-shuffle').checked) examQuestions.sort(() => Math.random() - .5);
  examQuestions = examQuestions.slice(0, count);
  renderExam();
  startTimer(examDuration);
}

function renderExam() {
  setup.classList.add('hidden');
  area.innerHTML = `
    <div class="timer" id="timer" role="timer"></div>
    ${examQuestions.map((question, questionIndex) => {
      const multiple = question.suggested_answers.length > 1;
      return `<article class="question-card">
        <header class="q-head"><div class="q-meta"><span class="q-num">Question ${questionIndex + 1} / ${examQuestions.length}</span><span class="answer-chip">Source question ${esc(question.question_num)}</span></div></header>
        <p class="q-text">${esc(question.question)}</p>
        ${question.question_images?.length ? `<div class="q-images">${images(question.question_images, `Illustration for question ${question.question_num}`)}</div>` : ''}
        <ul class="options">${question.options.map(option => `
          <li><label class="option-label">
            <input type="${multiple ? 'checkbox' : 'radio'}" name="answer-${questionIndex}" value="${esc(option.letter)}">
            <span class="opt-letter">${esc(option.letter)}</span>
            <span class="option-copy">${esc(option.text)}${option.images?.length ? images(option.images, `Illustration for answer ${option.letter}`) : ''}</span>
          </label></li>`).join('')}
        </ul>
      </article>`;
    }).join('')}
    <div class="submit-row"><button class="button primary" type="button" data-action="submit-exam">Submit exam</button></div>`;
  area.classList.remove('hidden');
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
}

function selectedLetters(index) {
  return [...document.querySelectorAll(`input[name="answer-${index}"]:checked`)]
    .map(input => input.value).sort();
}

function resultMessage(percent) {
  if (percent >= 80) return 'Strong foundation. Review the few missed questions to lock it in.';
  if (percent >= 60) return 'Good progress. Focus on the questions just added to your review list.';
  return 'Take it step by step. Review each missed question, then retry a shorter session.';
}

function submitExam(auto = false) {
  const unanswered = examQuestions.filter((_, index) => !selectedLetters(index).length).length;
  if (!auto && unanswered && !confirm(`${unanswered} unanswered questions. Submit anyway?`)) return;
  stopTimer();
  const reviewKeys = getReviewKeys();
  let score = 0;
  const review = examQuestions.map((question, index) => {
    const chosen = selectedLetters(index);
    const correct = [...question.suggested_answers].sort();
    const passed = chosen.join(',') === correct.join(',');
    if (passed) { score += 1; reviewKeys.delete(questionKey(question)); }
    else reviewKeys.add(questionKey(question));
    return { question, chosen, correct, passed };
  });
  saveReviewKeys(reviewKeys);
  syncReviewState(reviewKeys);
  const percent = Math.round(score * 100 / examQuestions.length);
  const wrong = examQuestions.length - score;
  area.innerHTML = `
    <section class="result-card" aria-labelledby="result-title">
      <div class="score-ring" style="--score:${percent * 3.6}deg"><div><strong>${percent}%</strong><span>${score}/${examQuestions.length} correct</span></div></div>
      <div>
        <p class="eyebrow">${auto ? 'Time expired' : 'Exam completed'}</p>
        <h1 id="result-title">Practice result</h1>
        <p class="result-copy">${resultMessage(percent)}</p>
        <div class="result-stats"><span><strong>${score}</strong> correct</span><span><strong>${wrong}</strong> incorrect</span><span><strong>${unanswered}</strong> unanswered</span></div>
        <div class="result-actions">
          <button class="button primary" type="button" data-action="retry-exam">Retry this exam</button>
          <button class="button" type="button" data-action="back-to-study">Review missed questions</button>
        </div>
      </div>
    </section>
    ${review.map(({ question, chosen, correct, passed }, index) => `
      <article class="question-card">
        <header class="q-head">
          <div class="q-meta"><span class="status-badge ${passed ? 'pass' : 'fail'}">${passed ? 'Correct' : 'Incorrect'}</span><span class="answer-chip">Question ${index + 1}</span></div>
        </header>
        <p class="q-text">${esc(question.question)}</p>
        ${question.question_images?.length ? `<div class="q-images">${images(question.question_images, `Illustration for question ${question.question_num}`)}</div>` : ''}
        <ul class="options">${question.options.map(option => {
          const isCorrect = correct.includes(option.letter);
          const isWrongChoice = chosen.includes(option.letter) && !isCorrect;
          const className = isCorrect ? 'right' : (isWrongChoice ? 'wrong-choice' : '');
          const label = isCorrect
            ? '<span class="option-result right">Correct answer</span>'
            : (isWrongChoice ? '<span class="option-result wrong">Your choice</span>' : '');
          return `<li class="${className}"><span class="opt-letter">${esc(option.letter)}</span><span class="option-copy">${esc(option.text)}${label}${option.images?.length ? images(option.images, `Illustration for answer ${option.letter}`) : ''}</span></li>`;
        }).join('')}</ul>
        <p class="answer-line">Answer: <strong>${correct.join(', ')}</strong> · Your answer: ${chosen.join(', ') || 'Not answered'}</p>
        ${comments(question.answers)}
      </article>`).join('')}`;
  window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
}

function startTimer(seconds) {
  stopTimer();
  let remaining = seconds;
  const node = document.getElementById('timer');
  if (!node) return;
  const tick = () => {
    const minute = String(Math.floor(remaining / 60)).padStart(2, '0');
    const second = String(remaining % 60).padStart(2, '0');
    node.textContent = `Time remaining: ${minute}:${second}`;
    node.classList.toggle('warning', remaining <= 60);
    if (remaining <= 0) { stopTimer(); submitExam(true); return; }
    remaining -= 1;
  };
  tick();
  timerId = setInterval(tick, 1000);
}

function stopTimer() {
  clearInterval(timerId);
  timerId = null;
}

studyMode.addEventListener('click', () => setMode('study'));
examMode.addEventListener('click', () => setMode('exam'));
document.getElementById('start-exam').addEventListener('click', startExam);
searchInput.addEventListener('input', applyStudyFilters);
onlyReview.addEventListener('change', applyStudyFilters);
toggleAnswers.addEventListener('click', () => setAllAnswers(document.body.classList.contains('answers-hidden')));
questionList.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  if (button.dataset.action === 'toggle-answer') toggleQuestionAnswer(button);
  if (button.dataset.action === 'toggle-review') toggleReviewQuestion(button);
});
area.addEventListener('change', () => {
  area.querySelectorAll('.option-label input').forEach(input => {
    input.closest('li').classList.toggle('chosen', input.checked);
  });
});
area.addEventListener('click', event => {
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'submit-exam') submitExam();
  if (action === 'retry-exam') { renderExam(); startTimer(examDuration); }
  if (action === 'back-to-study') { onlyReview.checked = true; setMode('study'); }
});
navLinks.forEach(link => link.addEventListener('click', () => {
  navLinks.forEach(item => item.classList.remove('active'));
  link.classList.add('active');
}));
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => {
    const current = entries.find(entry => entry.isIntersecting);
    if (!current) return;
    navLinks.forEach(link => link.classList.toggle('active', link.getAttribute('href') === `#${current.target.id}`));
  }, { rootMargin: '-20% 0px -65% 0px' });
  studyCards.forEach(card => observer.observe(card));
}
document.addEventListener('keydown', event => {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
  if (event.key === '/' && !typing && !studyShell.classList.contains('hidden')) {
    event.preventDefault();
    searchInput.focus();
  }
});
document.getElementById('exam-count').max = questions.length;
clearReviewsBtn.addEventListener('click', () => {
  saveReviewKeys(new Set());
  syncReviewState(new Set());
  applyStudyFilters();
});
const desktopLayout = window.matchMedia('(min-width: 861px)');
const syncQuestionPicker = event => { questionPicker.open = event.matches; };
syncQuestionPicker(desktopLayout);
desktopLayout.addEventListener?.('change', syncQuestionPicker);
applyStudyFilters();
</script>
</body>
</html>""")
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
                # Chi ghi error record neu CHUA co du lieu tot cho cau nay.
                # Tranh truong hop re-crawl fail tam thoi lam mat du lieu tot da crawl tu lan truoc.
                failed.append(qnum)
                error_msg = "Khong tim thay link discussion" if no_link else "Khong lay duoc cau hoi"
                has_good_data = any(
                    isinstance(rec, dict)
                    and rec.get("topic") == topic
                    and rec.get("question_num") == qnum
                    and rec.get("question")
                    for rec in all_data
                )
                if not has_good_data:
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
                else:
                    print(f"  Khong lay duoc cau {qnum} nhung giu du lieu tot tu lan truoc.")
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
