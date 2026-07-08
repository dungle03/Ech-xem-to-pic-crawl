# ExamTopics Crawler

Tự động thu thập câu hỏi từ ExamTopics và lưu kết quả dưới dạng JSON.

## Tính năng

* Tìm kiếm qua DuckDuckGo (ít CAPTCHA), tự chuyển sang Google khi DuckDuckGo không ra kết quả.
* Thu hẹp truy vấn bằng `site:examtopics.com` để tăng độ chính xác.
* Tái sử dụng session/cookie xuyên suốt phiên crawl.
* Gõ query vào ô tìm kiếm như người dùng thật (humanize).
* Fingerprint macOS nhất quán qua CloakBrowser.
* Lọc link chính xác theo slug — bỏ qua trang tổng hợp, câu/mã đề khác và link wrapper.
* Thu thập đầy đủ: đề bài, hình ảnh, các lựa chọn (A/B/C/D...), đáp án gợi ý, bình luận cộng đồng.
* Lấy cả URL hình trong đề bài và trong từng lựa chọn (nếu có).
* Fallback tải trang qua HTTP khi trình duyệt load trang discussion bị treo.
* Dọn tab sau mỗi câu, chỉ giữ lại một tab tìm kiếm.
* Hỗ trợ mã đề nhiều định dạng: gạch nối, gạch dưới, dấu chấm (`sk0-005`, `az-104`, `FCSS_NST_SE-7.6`).
* Lưu liên tục sau mỗi câu, tiếp tục được từ lần chạy trước (không mất dữ liệu khi dừng giữa chừng).
* Retry tự động khi gặp lỗi.

## Yêu cầu

* Python 3.8+
* Kết nối Internet
* Linux/macOS hoặc Windows (WSL2 khuyến nghị)
* Màn hình hiển thị (tool chạy trình duyệt ở chế độ headed)

## Cài đặt

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y \
    python3 python3-pip python3-venv \
    libnspr4 libnss3 libcups2 libdrm2 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libxkbcommon0 libasound2t64 \
    libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 \
    libpango-1.0-0 libcairo2 libx11-6 libxcb1 libxext6 libxi6

git clone <repository-url>
cd examtopic-crawl

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Lần chạy đầu, CloakBrowser tự tải Chromium (~697MB) về `~/.cloakbrowser/`. Cần mạng thông và đủ dung lượng đĩa.

## Sử dụng

```bash
source venv/bin/activate
python3 tool.py
```

Nhập theo hướng dẫn:

```
Nhap ma de (ex200, ex300): FCSS_NST_SE-7.6
Nhap topic (mac dinh 1): 1
Nhap pham vi cau (vd: 1-10, hoac de trong lay 1-120): 1-50
```

## Cách hoạt động

Với mỗi câu hỏi, tool tra URL trang discussion theo thứ tự:

1. Tìm trên DuckDuckGo (kèm `site:examtopics.com`).
2. Nếu không thấy link khớp đúng câu, tìm lại trên Google.
3. Mở trang discussion tìm được; nếu trình duyệt load treo, tải nội dung qua HTTP rồi bóc dữ liệu.

## Kết quả

Lưu tại `output/{exam_code}_questions.json`, mỗi câu có dạng:

```json
{
  "exam_code": "sk0-005",
  "topic": 1,
  "question_num": 57,
  "question": "A systems administrator is performing maintenance...",
  "question_images": ["https://img.examtopics.com/.../image1.png"],
  "options": [
    { "letter": "A", "text": "Remote desktop", "images": [], "is_correct": true  },
    { "letter": "B", "text": "IP KVM",         "images": [], "is_correct": true  },
    { "letter": "C", "text": "A console connection", "images": [], "is_correct": false },
    { "letter": "D", "text": "A virtual administration console", "images": [], "is_correct": false }
  ],
  "suggested_answers": ["A", "B"],
  "answers": ["Definitely B and D...", "..."],
  "url": "https://www.examtopics.com/discussions/..."
}
```

Ghi chú:

* `question_images` và `options[].images` chỉ lưu URL, không tải file ảnh về máy.
* `suggested_answers` là danh sách — hỗ trợ câu "Choose two/three".
* Câu không có hình thì các trường ảnh là mảng rỗng.

## Cấu hình

| Biến | Mô tả | Mặc định |
|---|---|---|
| `MIN_DELAY` | Nghỉ tối thiểu giữa các câu (giây) | 2 |
| `MAX_DELAY` | Nghỉ tối đa giữa các câu (giây) | 5 |
| `RETRY_LIMIT` | Số lần retry khi lỗi | 3 |
| `OUTPUT_DIR` | Thư mục lưu kết quả | `output` |

## License

Dự án phục vụ mục đích học tập và nghiên cứu cá nhân.
