import os
import json
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from PIL import Image as PILImage

from ..config import LOG, _preload_images, _fetch_image
from ..parser import as_int, record_topic

# Bang mau dung chung (dong bo voi HTML: xanh la dam cho dap an dung).
COLOR_HEADING = RGBColor(0x16, 0x21, 0x3E)   # xanh dam
COLOR_CORRECT = RGBColor(0x1B, 0x5E, 0x20)   # xanh la dam
COLOR_MUTED = RGBColor(0x66, 0x66, 0x66)     # xam
COLOR_NOTE = RGBColor(0x55, 0x55, 0x55)      # xam nhat
COLOR_ERROR = RGBColor(0xC6, 0x28, 0x28)     # do
SHADE_CORRECT = "E6F4EA"                     # nen xanh nhat cho dap an dung

DEFAULT_FONT = "Calibri"


def _set_default_font(doc, name=DEFAULT_FONT):
    """Dat font mac dinh cho ca tai lieu de hien thi on dinh moi may.

    Khong dat thi Word tu chon font theo he thong, khien file trong khac nhau
    tren tung may. Dong thoi set font cho cac style Heading de dong bo.
    """
    for style_name in ("Normal", "Heading 1", "Heading 2", "Heading 3"):
        try:
            style = doc.styles[style_name]
        except KeyError:
            continue
        style.font.name = name
        # python-docx khong tu set font cho ky tu CJK/complex script -> set XML.
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attr), name)


def _shade_paragraph(paragraph, fill_hex):
    """To mau nen cho mot doan van bang XML (python-docx khong co API san)."""
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    p_pr.append(shd)


def _add_page_number_footer(section, exam_label):
    """Them footer: ten de ben trai, so trang ben phai."""
    footer = section.footer
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = paragraph.add_run(f"{exam_label}  -  Trang ")
    run.font.size = Pt(9)
    run.font.color.rgb = COLOR_MUTED

    # Truong PAGE tu dong cap nhat so trang khi mo Word.
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    num_run = paragraph.add_run()
    num_run.font.size = Pt(9)
    num_run.font.color.rgb = COLOR_MUTED
    num_run._r.append(fld_begin)
    num_run._r.append(instr)
    num_run._r.append(fld_end)


def _add_header(section, exam_label):
    """Them header nho o goc phai voi ten de."""
    header = section.header
    paragraph = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run(exam_label)
    run.font.size = Pt(9)
    run.font.color.rgb = COLOR_MUTED
    run.italic = True


def _add_separator(doc):
    """Them duong ke ngang phan cach giua cac cau hoi."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    p_pr = p._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "D0D0DC")
    borders.append(bottom)
    p_pr.append(borders)


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


def _add_question_docx(doc, q, num, show_topic=False, hide_answers=False):
    """Ghi mot cau hoi vao tai lieu Word.

    hide_answers=True se BO QUA khoi dap an de nguoi hoc tu luyen, dap an chi
    con o bang Answer Key cuoi file.
    """
    suggested = q.get("suggested_answers") or []
    most_voted = q.get("community_most_voted") or []

    heading_text = f"Câu {num}"
    if show_topic and q.get("topic"):
        heading_text += f"  (Topic {q.get('topic')})"
    heading = doc.add_heading(heading_text, level=2)
    heading.paragraph_format.space_before = Pt(10)
    heading.paragraph_format.space_after = Pt(4)
    for run in heading.runs:
        run.font.color.rgb = COLOR_HEADING
        run.font.size = Pt(13.5)
        run.bold = True

    if not hide_answers:
        answer_str = ", ".join(str(s) for s in suggested) if suggested else "N/A"
        if most_voted and set(str(s) for s in most_voted) != set(str(s) for s in suggested):
            answer_str += f"  (Cộng đồng: {', '.join(str(s) for s in most_voted)})"
        answer_p = doc.add_paragraph()
        answer_p.paragraph_format.space_after = Pt(6)
        label_run = answer_p.add_run("Đáp án: ")
        label_run.bold = True
        label_run.font.color.rgb = COLOR_CORRECT
        value_run = answer_p.add_run(answer_str)
        value_run.bold = True
        value_run.font.color.rgb = COLOR_CORRECT

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
            text_run.font.color.rgb = COLOR_CORRECT
            check = p.add_run("  \u2713")
            check.bold = True
            check.font.color.rgb = COLOR_CORRECT
            # To nen nhat giup dap an dung noi bat ca khi in mau lan doc man hinh.
            _shade_paragraph(p, SHADE_CORRECT)

        for img_url in (opt.get("images") or []):
            buf = _fetch_image(img_url)
            if buf:
                _add_picture_fitted(doc, buf, max_width_inches=4.0)

    answers = q.get("answers") or []
    if answers:
        doc.add_paragraph("Bình luận:", style="List Bullet")
        for comment in answers[:5]:
            p = doc.add_paragraph(comment[:500])
            p.paragraph_format.left_indent = Inches(0.5)
            p.paragraph_format.space_after = Pt(6)
            for run in p.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = COLOR_NOTE

    if q.get("error"):
        p = doc.add_paragraph(f"[Lỗi] {q['error']}")
        for run in p.runs:
            run.font.color.rgb = COLOR_ERROR
            run.font.size = Pt(9)

    _add_top_comments_docx(doc, q)
    _add_separator(doc)


def _add_top_comments_docx(doc, q):
    """In binh luan noi bat cho cau KHONG co dap an A/B/C/D (HOTSPOT, DRAG DROP...).

    Sap theo so luot upvote THAT lay tu ExamTopics. Ghi ro day la y kien cong
    dong, khong phai dap an chinh thuc -- tool khong tu suy ra dap an vi binh
    luan hay mau thuan nhau.
    """
    if (q.get("suggested_answers") or []) or (q.get("options") or []):
        return
    top = [c for c in (q.get("top_comments") or []) if isinstance(c, dict)]
    if not top:
        return
    head = doc.add_paragraph()
    head.paragraph_format.space_before = Pt(4)
    run = head.add_run("Không có đáp án A/B/C/D cho dạng câu này. "
                       "Bình luận nổi bật (theo lượt bình chọn của cộng đồng):")
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = COLOR_HEADING
    for c in top:
        votes = as_int(c.get("votes"), 0)
        badge = str(c.get("badge") or "").strip()
        user = str(c.get("user") or "").strip()
        bits = [b for b in (
            f"{votes} upvote" + ("s" if votes != 1 else "") if votes else "",
            badge,
            user,
        ) if b]
        meta = doc.add_paragraph(" · ".join(bits))
        meta.paragraph_format.left_indent = Inches(0.3)
        meta.paragraph_format.space_after = Pt(2)
        for r in meta.runs:
            r.font.size = Pt(8)
            r.bold = True
            r.font.color.rgb = COLOR_CORRECT
        body = doc.add_paragraph(str(c.get("text") or "")[:800])
        body.paragraph_format.left_indent = Inches(0.3)
        body.paragraph_format.space_after = Pt(8)
        for r in body.runs:
            r.font.size = Pt(9)
            r.font.color.rgb = COLOR_NOTE
    note = doc.add_paragraph("Đây là ý kiến cộng đồng, không phải đáp án chính thức. "
                             "Bình luận có thể mâu thuẫn nhau — hãy tự đối chiếu.")
    note.paragraph_format.left_indent = Inches(0.3)
    for r in note.runs:
        r.font.size = Pt(8)
        r.italic = True
        r.font.color.rgb = COLOR_MUTED


def convert_to_docx(json_path, hide_answers=False):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("File JSON khong phai danh sach cau hoi.")
    questions = [q for q in data if isinstance(q, dict) and q.get("question")]
    if not questions:
        raise ValueError("Khong co cau hoi hop le trong file.")

    questions = sorted(questions, key=lambda q: (record_topic(q), as_int(q.get("question_num"), 0)))
    show_topic = len(set(record_topic(q) for q in questions)) > 1

    _preload_images(questions)

    exam_code = questions[0].get("exam_code", "exam")
    exam_label = str(exam_code).upper()
    doc = Document()
    _set_default_font(doc)

    section = doc.sections[0]
    _add_header(section, exam_label)
    _add_page_number_footer(section, exam_label)

    title = doc.add_heading(exam_label, level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.color.rgb = COLOR_HEADING
        run.font.size = Pt(24)

    meta = doc.add_paragraph(f"{len(questions)} câu hỏi  -  ExamTopics")
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in meta.runs:
        run.font.size = Pt(11)
        run.font.color.rgb = COLOR_MUTED

    if hide_answers:
        note = doc.add_paragraph("Chế độ tự luyện: đáp án đã được ẩn, xem bảng tra cứu ở cuối tài liệu.")
        note.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in note.runs:
            run.font.size = Pt(10)
            run.italic = True
            run.font.color.rgb = COLOR_MUTED

    doc.add_page_break()

    total_q = len(questions)
    LOG.info(f"  Dang tao tai lieu Word ({total_q} cau)...")
    step = max(50, total_q // 10)
    for i, q in enumerate(questions, 1):
        _add_question_docx(doc, q, q.get("question_num", i),
                           show_topic=show_topic, hide_answers=hide_answers)
        if i % step == 0 or i == total_q:
            LOG.info(f"    Ghi noi dung: {i}/{total_q} cau")

    _add_answer_key_table(doc, questions)

    out_path = os.path.splitext(json_path)[0] + ".docx"
    LOG.info("  Dang luu file DOCX vao dia...")
    doc.save(out_path)
    LOG.info(f"DOCX: {out_path}")
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
    heading = doc.add_heading("BẢNG ĐÁP ÁN TRA CỨU NHANH", level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in heading.runs:
        run.font.color.rgb = COLOR_HEADING
        run.font.size = Pt(16)
        run.bold = True

    sub = doc.add_paragraph("Bảng tổng hợp đáp án gợi ý toàn bộ câu hỏi")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in sub.runs:
        run.font.size = Pt(10)
        run.font.color.rgb = COLOR_MUTED

    COLS_PER_ROW = 4
    num_q = len(valid_q)
    rows_needed = (num_q + COLS_PER_ROW - 1) // COLS_PER_ROW

    table = doc.add_table(rows=rows_needed + 1, cols=COLS_PER_ROW * 2)
    table.autofit = False
    table.style = "Table Grid"

    # Header
    hdr_cells = table.rows[0].cells
    for c in range(COLS_PER_ROW):
        idx_q = c * 2
        idx_a = c * 2 + 1
        hdr_cells[idx_q].text = "Câu"
        hdr_cells[idx_a].text = "ĐA"
        for idx in (idx_q, idx_a):
            p = hdr_cells[idx].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(9)
                r.font.color.rgb = COLOR_HEADING
            _shade_paragraph(p, "EDEEF5")

    # Data
    multiple_topics = len(set(record_topic(x) for x in valid_q)) > 1
    for i, q in enumerate(valid_q):
        row_idx = (i % rows_needed) + 1
        col_group = i // rows_needed
        col_q = col_group * 2
        col_a = col_group * 2 + 1

        topic = record_topic(q)
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
            r.font.color.rgb = COLOR_CORRECT
