# Báo cáo debug `examtopic/` + nghiên cứu `arvind88765/examtopics-scraper`

Ngày: 2026-09-29 · Nguồn: 5 session log trong
`~/.dsh/sessions/--home-lee-projects-examtopic-crawl--/`, tài liệu Mnemon
`d9651102`, repo `arvind88765/examtopics-scraper` (clone `/tmp/ets`, HEAD `09a1362`),
repo gốc `swarnava-dutta/Free-Exam-Dumps` (`/tmp/fedl`, HEAD `b3c6785`),
và kiểm chứng trực tiếp trên site sống.

---

## 1. Session cũ đã làm gì

Session lớn `fbc532e5` (6 turn, 1609 event) chẩn đoán lỗi "crawl `hqt-4180` bắt HTTP
rất nhiều". Kết quả chốt trong tài liệu `d9651102` — 7 nguyên nhân gốc:

| # | Nguyên nhân gốc (đã xác minh) |
|---|---|
| 1 | `EXAM_VIEW_URL` nhét slug đề vào **cả hai** path slot → `/exams/hqt-4180/hqt-4180/` = 404, đúng phải là `/exams/hitachi/hqt-4180/` |
| 2 | `canonical_exam_code()` xoá gạch ngang → sinh slug chết; gạch ngang **phải giữ** |
| 3 | Endpoint `ajax/discussion/exam-question/` đã chết |
| 4 | Anchor `data-id` giờ là **hằng số `825909`** cho mọi câu/mọi đề → mọi suy diễn id vô nghĩa |
| 5 | Id từ DuckDuckGo **cũ/stale** → tool tìm thấy link rồi 404 |
| 6 | 429 bị gộp chung với lỗi |
| 7 | Bản ghi "thành công" vẫn rỗng (`options: []`, `suggested_answers: []`) |

Các session sau **viết lại `resolver.py`** (harvest listing vendor thay cho AJAX) nhưng
**chưa commit**: `git status` cho 7 file sửa, +942/−538.

Tin nhắn cuối session (yêu cầu hiện tại): *"đến câu 32 thì không còn cache hay link đã
harvest nữa, dùng search, thấy link rồi, nhưng chỉ mở link blank và cứ chờ như vậy xong
lỗi."* → đúng đường `safe_goto` treo 15s trên link 404.

---

## 2. Repo `arvind88765` áp dụng thế nào — và nó đã lỗi thời

Repo (bản 22/09/2026) build trên `Free-Exam-Dumps`, chạy **HTTP thuần + 64 worker**,
Camoufox chỉ là fallback. Cơ chế:

- Harvest link từ `/discussions/<provider>/<n>/` — **trùng hướng `resolver.py` đã làm**.
- **"ID walk"**: probe `view/<id>-x/` quanh id đã biết để phục hồi câu thiếu trong listing.
- Đáp án gợi ý qua class `correct-hidden`; vote cộng đồng qua `voted-answers-tally`.
- README khẳng định "site hiện popup JS khoá nội dung".

### Kiểm chứng live: 4 giả định trung tâm của repo đều đã chết

| Giả định | Kiểm chứng | Kết luận |
|---|---|---|
| `view/<id>-x/` (slug trang trí) | `99394-x/`→404, `99394/`→404, `99394-anything/`→404 | ❌ ID walk chết |
| `correct-hidden` | 0 lần xuất hiện | ❌ chết |
| `voted-answers-tally` / `most-voted-answer-badge` | 0 lần xuất hiện | ❌ chết |
| Popup `notRemoverPopup`/`createPopup` | 0 lần xuất hiện | ❌ không có |

### Phát hiện then chốt: site khoá theo CẶP `(id, slug)`

```
99394-exam-hqt-4180-topic-1-question-5-discussion/   → 200 (shown_q=5)
99394-exam-hqt-4180-topic-1-question-99-discussion/  → 404
99394-exam-hqt-4420-topic-1-question-5-discussion/   → 404
99394-exam-xyz-topic-1-question-1-discussion/        → 404
```

→ Mọi kỹ thuật "đoán id" (cả repo và session cũ) **về cấu trúc không thể hoạt động**.
Không phải site chặn — mà khoá theo slug.

**Kết luận:** tool hiện tại **không thua** repo này; nó đang đi trước (đã harvest listing,
đã dùng `Correct Answer` từ trang exam). Repo chỉ còn giá trị ở vài ý tưởng *phương pháp*.

---

## 3. Vì sao 11 câu `hqt-4180` không lấy được

Harvest **toàn bộ** 3 trang listing vendor `hitachi`: chỉ **45 câu** `hqt-4180`
(thiếu 32,36,39,40,42,43,46,47,49,52,54 — khớp đúng `output/hqt4180_errors.json`).

Kiểm tra id mà search trả về (`289309` q32, `337650` q36…):

- Mọi biến thể slug (hqt-4180 / hqt4180 / hqt_4180 / sai qnum / sai code / sai topic) → **404 tất cả**.
- Từ **IP khác** (`r.jina.ai`) → 404.
- Trên **category khác** (microsoft/amazon/cisco) → 404.
- **Probe ±190 id quanh `289309`** → 0 hit. Probe `337625–337670` → 0 hit.

→ Câu **bị gỡ hoặc paywall**, không phải "bị chặn tạm", không phải "listing giấu".
Trang exam ghi **108 Questions**, chỉ 45 câu công khai. **ID walk không cứu được.**

---

## 4. Lỗi trong tool — tái xác minh trên site sống

### P0 — đúng bug đã báo (28s chờ + blank)

- `resolver.fetch_html` coi **404 là "chưa chắc"** → retry backoff 4→8→16s = **28s/lần**.
  Lý thuyết "bị chặn thì trả 404 rỗng" **đã bị phủ định**: đo 24 request song song lúc bị
  chặn → **100% 429, không 404 nào**. 404 tất định cho cặp `(id,slug)` sai.
- Sau khi HTTP fail, code **vẫn mở browser** `safe_goto` → `ERR_HTTP_RESPONSE_CODE_FAILURE`,
  treo thêm 15s. Đây là "mở link blank và chờ".

### P1 — mất dữ liệu thật (đo được)

| Trường | hqt4180 (45) | ms700 (417) |
|---|---|---|
| `community_most_voted` | **0/45** | **0/417** |
| `community_votes` | **0/45** | **0/417** |
| `top_comments` | 45/45 | 0/417 |
| `options` | 45/45 | 242/417 |

`community_*` chết vì phụ thuộc `.voted-answers-tally`. `load_full_comments` gọi
`ajax/discussion/load-complete/` → **404**, là dead code (trang hiện render đủ bình luận
inline, không còn nút "Load full discussion").

---

## 5. Đề xuất cải tiến (ưu tiên)

### P0 — sửa bug vừa gặp

1. **404 là terminal**: bỏ 404 khỏi danh sách retry trong `fetch_html` (chỉ retry 429/503).
   Xoá luôn backoff 28s.
2. **Không fallback browser khi URL đã chết**: HTTP trả 404 → thoát ngay, không mở tab.
3. **Phân loại "gated/removed"** khác "không tìm thấy": vắng trong listing đã harvest đủ
   **và** probe slug dẫn xuất 404 → `"Câu bị paywall/gỡ bỏ (cần đăng nhập)"`.

### P1 — khôi phục dữ liệu

4. **Tally "Selected Answer" từ badge bình luận, trọng số upvote.** Prototype đã chạy:
   - Mỗi comment có `Selected Answer: <span><strong>ABC</strong></span>` +
     `upvoted <span class="upvote-count">N</span>`.
   - ms-700 q1 → `{B:14}` → đáp án **B** (đúng).
   - hqt-4180 q5 → `{A:1,B:1,C:1}` (yếu, weight theo upvote để cải thiện).
   Đây là cách repo `arvind88765` làm — **vẫn sống**, khác `voted-answers-tally`.
5. **`question_type`** cho HOTSPOT/DRAG-DROP: 140/382 bản ghi ms-700 thiếu options vì
   hotspot → gắn nhãn thay vì để `options: []` im lặng.
6. Đáp án q1–q10 từ trang exam giữ nguyên; q11+ đánh dấu
   `"community-derived, chưa xác minh"`.

### P2 — thông lượng & bền vững (số đo thật)

7. **Pool 4–8 worker + rate limiter ~5 req/s.** Đo: 8 worker = **6.2 req/s, 0×429**;
   24 worker = **0/24, 100% 429**. (Repo dùng 64 worker — sai với rate limit hiện tại.)
8. **Honor `Retry-After`** trên 429 (cả hai bên đều chưa làm).
9. **Match theo text link, không chỉ URL** (URL bị cắt cụt trước `-topic-`).
10. **Phát hiện chặn dựa vào thiếu nav site**, không substring cả trang (`_BLOCK_TEXT`
    của bạn có cùng rủi ro; repo đo được substring xoá oan 2/1019 câu thật).
11. **Second pass chậm** cho câu sót, báo `[WARN]`, không bỏ im lặng.
12. **Xoá code chết gây nhiễu**: `load_full_comments`, `question_id_from_tab`,
    `correct-hidden`.

### P3 — quy trình

13. **Commit ngay working tree** (7 file sửa chưa vào git).
14. **Regression test** cho fact đã xác minh: khoá cặp `(id,slug)`, 404 terminal,
    không có vote marker, badge tally.

---

## 6. Phụ lục — lệnh kiểm chứng

```bash
# khoá theo cặp (id,slug)
curl -s -o /dev/null -w '%{http_code}\n' \
  https://www.examtopics.com/discussions/hitachi/view/99394-exam-hqt-4180-topic-1-question-5-discussion/   # 200
curl -s -o /dev/null -w '%{http_code}\n' \
  https://www.examtopics.com/discussions/hitachi/view/99394-x/                                             # 404
# rate limit
# 8 worker  -> 6.2 req/s, 0×429 ;  24 worker -> 0/24, 100% 429
# AJAX chết
curl -s -o /dev/null -w '%{http_code}\n' \
  'https://www.examtopics.com/ajax/discussion/load-complete/?discussion-id=99394'                          # 404
```
