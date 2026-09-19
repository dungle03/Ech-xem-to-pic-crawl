import os
import json
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image as PILImage

from ..config import _preload_images, _fetch_image

def _add_picture_fitted(doc, buf, max_width_inches=5.5):
    try:
        with PILImage.open(buf) as img:
            w_px, _ = img.size
        w_in = w_px / 96.0
        width = min(Inches(max_width_inches), Inches(w_in)) if w_in > 0 else Inches(max_width_inches)
        buf.seek(0)
        doc.add_picture(buf, width=width)
        return True
    except Exception:
        try:
            buf.seek(0)
            doc.add_picture(buf, width=Inches(max_width_inches))
            return True
        except Exception:
            return False

def _add_question_docx(doc, q, num, show_topic=False):
    suggested = q.get("suggested_answers") or []
    answer_str = ", ".join(str(s) for s in suggested) if suggested else "N/A"

    heading_text = f"Cau {num} (Topic {q.get('topic', 1)})" if show_topic else f"Cau {num}"
    heading = doc.add_heading(heading_text, level=2)
    for run in heading.runs:
        run.font.color.rgb = RGBColor(0x16, 0x21, 0x3E)
        run.font.size = Pt(14)

    answer_p = doc.add_paragraph()
    most_voted = q.get("community_most_voted") or []
    if most_voted and set(str(s) for s in most_voted) != set(str(s) for s in suggested):
        answer_str += f" (Cộng đồng: {', '.join(str(s) for s in most_voted)})"
    answer_run = answer_p.add_run(f"Dap an: {answer_str}")
    answer_run.bold = True
    answer_run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)

    question_text = str(q.get("question", "") or "")
    p = doc.add_paragraph(question_text)
    p.paragraph_format.space_after = Pt(8)

    for url in (q.get("question_images") or []):
        buf = _fetch_image(url)
        if not buf or not _add_picture_fitted(doc, buf, max_width_inches=5.5):
            doc.add_paragraph(url)

    for opt in (q.get("options") or []):
        if not isinstance(opt, dict):
            continue
        letter = str(opt.get("letter", "") or "")
        text = str(opt.get("text", "") or "")
        is_correct = bool(opt.get("is_correct", False))
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

        for img_url in (opt.get("images") or []):
            buf = _fetch_image(img_url)
            if buf:
                _add_picture_fitted(doc, buf, max_width_inches=4.0)

    answers = q.get("answers") or []
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

    questions = sorted(questions, key=lambda q: (int(q.get("topic") or 1), int(q.get("question_num") or 0)))
    show_topic = len(set(q.get("topic", 1) for q in questions)) > 1

    _preload_images(questions)

    exam_code = questions[0].get("exam_code", "exam")
    doc = Document()

    title = doc.add_heading(exam_code.upper(), level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph(f"{len(questions)} cau hoi - Topic dump ExamTopics")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_page_break()

    total_q = len(questions)
    print(f"  Dang tao tai lieu Word ({total_q} cau)...")
    step = max(50, total_q // 10)
    for i, q in enumerate(questions, 1):
        _add_question_docx(doc, q, q.get("question_num", i), show_topic=show_topic)
        if i % step == 0 or i == total_q:
            print(f"    Ghi noi dung: {i}/{total_q} cau")

    _add_answer_key_table(doc, questions)

    out_path = os.path.splitext(json_path)[0] + ".docx"
    print("  Dang luu file DOCX vao dia...")
    doc.save(out_path)
    print(f"DOCX: {out_path}")
    return out_path

def _add_answer_key_table(doc, questions):
    """Them bang phu luc tra cuu dap an nhanh (Answer Key) o cuoi file Word.

    Xep theo luoi 4 cot (moi cot gom 2 cot con: Cau | Dap an) giup nguoi hoc
    tien in an va tra cuu nhanh sau khi tu giai de.
    """
    valid_q = [q for q in questions if isinstance(q, dict) and (q.get("question") or q.get("suggested_answers"))]
    if not valid_q:
        return

    doc.add_page_break()
    heading = doc.add_heading("BẢNG ĐÁP ÁN TRA CỨU NHANH (ANSWER KEY)", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in heading.runs:
        run.font.color.rgb = RGBColor(0x16, 0x21, 0x3E)
        run.font.size = Pt(16)
        run.bold = True

    sub = doc.add_paragraph("Bang tong hop dap an goi y toan bo cau hoi")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in sub.runs:
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    COLS_PER_ROW = 4
    num_q = len(valid_q)
    rows_needed = (num_q + COLS_PER_ROW - 1) // COLS_PER_ROW

    table = doc.add_table(rows=rows_needed + 1, cols=COLS_PER_ROW * 2)
    table.autofit = False

    # Header
    hdr_cells = table.rows[0].cells
    for c in range(COLS_PER_ROW):
        idx_q = c * 2
        idx_a = c * 2 + 1
        hdr_cells[idx_q].text = "Cau"
        hdr_cells[idx_a].text = "D/A"
        for idx in (idx_q, idx_a):
            p = hdr_cells[idx].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(0x16, 0x21, 0x3E)

    # Data
    multiple_topics = len(set(x.get("topic", 1) for x in valid_q)) > 1
    for i, q in enumerate(valid_q):
        row_idx = (i % rows_needed) + 1
        col_group = i // rows_needed
        col_q = col_group * 2
        col_a = col_group * 2 + 1

        topic = q.get("topic")
        qnum = q.get("question_num", i + 1)
        q_label = f"T{topic}#{qnum}" if (multiple_topics and topic) else f"#{qnum}"

        ans = ", ".join(str(s) for s in (q.get("suggested_answers") or []))
        if not ans and q.get("community_most_voted"):
            ans = ", ".join(str(s) for s in q.get("community_most_voted"))
        if not ans:
            ans = "-"

        row_cells = table.rows[row_idx].cells
        row_cells[col_q].text = q_label
        row_cells[col_a].text = ans

        p_q = row_cells[col_q].paragraphs[0]
        p_q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p_q.runs:
            r.font.size = Pt(8.5)

        p_a = row_cells[col_a].paragraphs[0]
        p_a.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p_a.runs:
            r.bold = True
            r.font.size = Pt(8.5)
            r.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)
