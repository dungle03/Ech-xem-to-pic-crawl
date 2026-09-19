import os
import json
import base64

from ..config import _preload_images, _fetch_image_bytes
from ..parser import escape_html, as_int

def build_html(questions, exam_code, embed_images=True):
    questions = sorted(questions, key=lambda q: (as_int(q.get("topic"), 1) or 1, as_int(q.get("question_num"), 0)))
    multiple_topics = len(set(q.get("topic", 1) for q in questions)) > 1

    if embed_images:
        _preload_images(questions)

    def _url_to_src(url):
        """Tra ve src cho <img>: base64 data URI neu embed_images=True, URL neu False."""
        if not embed_images:
            return str(url or '')
        data = _fetch_image_bytes(url)
        if data:
            b64 = base64.b64encode(data).decode("ascii")
            if data.startswith(b"\x89PNG"):
                return f"data:image/png;base64,{b64}"
            if data.startswith(b"\xff\xd8"):
                return f"data:image/jpeg;base64,{b64}"
            if data.startswith(b"GIF8"):
                return f"data:image/gif;base64,{b64}"
            return f"data:image/png;base64,{b64}"
        return str(url or '')

    parts = []
    if embed_images:
        payload_questions = []
        for q in questions:
            qc = dict(q)
            if qc.get("question_images"):
                qc["question_images"] = [_url_to_src(u) for u in qc["question_images"]]
            if qc.get("options"):
                opts = []
                for opt in qc["options"]:
                    if isinstance(opt, dict):
                        oc = dict(opt)
                        if oc.get("images"):
                            oc["images"] = [_url_to_src(u) for u in oc["images"]]
                        opts.append(oc)
                    else:
                        opts.append(opt)
                qc["options"] = opts
            payload_questions.append(qc)
        exam_payload = json.dumps(payload_questions, ensure_ascii=False).replace("</", "<\\/")
    else:
        exam_payload = json.dumps(questions, ensure_ascii=False).replace("</", "<\\/")
    nav_items = []
    for index, question in enumerate(questions, 1):
        number = question.get("question_num", index)
        topic_num = question.get("topic", 1)
        question_key = f"{topic_num}:{number}"
        nav_label = f"T{topic_num} #{number}" if multiple_topics else str(number)
        nav_items.append(
            f'<a href="#q-{index}" data-key="{escape_html(question_key)}" '
            f'aria-label="Go to Topic {escape_html(topic_num)} question {escape_html(number)}" '
            f'title="Topic {escape_html(topic_num)} - Question {escape_html(number)}">{escape_html(nav_label)}</a>'
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
.q-num, .answer-chip, .status-badge, .topic-chip {
    min-height: 30px; display: inline-flex; align-items: center; padding: 4px 10px;
    border-radius: 999px; font-size: .76rem; font-weight: 800; white-space: nowrap;
}
.topic-chip { background: var(--surface-soft); color: var(--text); border: 1px solid var(--border); }
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
        suggested = question.get("suggested_answers") or []
        answer_text = ", ".join(str(s) for s in suggested) if suggested else "Unavailable"
        opt_list = [o for o in (question.get("options") or []) if isinstance(o, dict)]
        raw_search = " ".join(" ".join([
            str(number),
            str(question.get("question", "") or ""),
            *[str(option.get("text", "") or "") for option in opt_list],
        ]).split()).lower()

        image_html = "".join(
            f'<img src="{escape_html(_url_to_src(url))}" alt="Illustration for question {escape_html(number)}" loading="lazy">'
            for url in (question.get("question_images") or [])
        )

        options_html = []
        for option in opt_list:
            letter = option.get("letter", "") or ""
            correct = bool(option.get("is_correct", False))
            option_images = "".join(
                f'<img src="{escape_html(_url_to_src(url))}" alt="Illustration for answer {escape_html(letter)}" loading="lazy">'
                for url in (option.get("images") or [])
            )
            badge = '<span class="correct-badge">Correct answer</span>' if correct else ""
            options_html.append(
                f'<li class="{"correct" if correct else ""}">'
                f'<span class="opt-letter">{escape_html(letter)}</span>'
                f'<span class="option-copy">{escape_html(option.get("text", "") or "")}{badge}{option_images}</span>'
                '</li>'
            )

        comments_html = ""
        comments = question.get("answers") or []
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
{f'<span class="topic-chip">Topic {escape_html(question.get("topic", 1))}</span>' if multiple_topics else ''}
<span class="q-num">Question {escape_html(number)}</span>
<span class="answer-chip"><span class="answer-prefix">Answer: </span><span class="answer-value">{escape_html(answer_text)}</span></span>
{f'<span class="topic-chip" style="background:#e8f5e9;color:#2e7d32;border-color:#c8e6c9" title="Community Most Voted">Most Voted: {escape_html(", ".join(str(s) for s in question.get("community_most_voted")))}</span>' if question.get("community_most_voted") and set(str(s) for s in question.get("community_most_voted", [])) != set(str(s) for s in question.get("suggested_answers", [])) else ''}
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
  if (document.getElementById('exam-shuffle').checked) {
    for (let i = examQuestions.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [examQuestions[i], examQuestions[j]] = [examQuestions[j], examQuestions[i]];
    }
  }
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


def convert_to_html(json_path, embed_images=True):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("File JSON khong phai danh sach cau hoi.")
    questions = [q for q in data if isinstance(q, dict) and q.get("question")]
    if not questions:
        raise ValueError("Khong co cau hoi hop le trong file.")
    questions = sorted(questions, key=lambda q: (as_int(q.get("topic"), 1) or 1, as_int(q.get("question_num"), 0)))
    exam_code = questions[0].get("exam_code", "exam")
    html = build_html(questions, exam_code, embed_images=embed_images)
    out_path = os.path.splitext(json_path)[0] + ".html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML: {out_path}")
    return out_path
