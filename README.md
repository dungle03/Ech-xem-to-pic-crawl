# ExamTopics Crawler

Tự động thu thập câu hỏi từ ExamTopics qua DuckDuckGo và lưu kết quả dưới dạng JSON.

## Tính năng

* Tìm kiếm qua DuckDuckGo (không dùng Google, tránh CAPTCHA).
* Tái sử dụng session/cookie xuyên suốt phiên crawl.
* Gõ query vào ô tìm kiếm như người dùng thật (humanize).
* Fingerprint macOS nhất quán qua CloakBrowser.
* Lọc link chính xác theo slug — bỏ qua trang tổng hợp và câu/mã đề khác.
* Thu thập đầy đủ: đề bài, các lựa chọn (A/B/C/D...), đáp án gợi ý, bình luận cộng đồng.
* Hỗ trợ mã đề có dấu gạch nối (`sk0-005`, `az-104`...).
* Lưu liên tục sau mỗi câu, tiếp tục được từ lần chạy trước (không mất dữ liệu khi dừng giữa chừng).
* Retry tự động khi gặp lỗi.

## Yêu cầu

* Python 3.8+
* Kết nối Internet
* Linux/macOS hoặc Windows (WSL2 khuyến nghị)

## Cài đặt

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y \
    python3 python3-pip python3-venv \
    libnspr4 libnss3 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxi6 libxtst6 libxrandr2 libasound2t64 \
    libatk-bridge2.0-0t64 libgtk-3-0t64 libgbm1 libxkbcommon0

git clone <repository-url>
cd examtopic-crawl

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Sử dụng

```bash
source venv/bin/activate
python3 tool.py
```

Nhập theo hướng dẫn:

```
Nhap ma de (ex200, ex300): sk0-005
Nhap topic (mac dinh 1): 1
Nhap pham vi cau (vd: 1-10, hoac de trong lay 1-120): 1-50
```

## Kết quả

Lưu tại `output/{exam_code}_questions.json`, mỗi câu có dạng:

```json
{
  "exam_code": "sk0-005",
  "topic": 1,
  "question_num": 57,
  "question": "A systems administrator is performing maintenance...",
  "options": [
    { "letter": "A", "text": "Remote desktop",   "is_correct": true  },
    { "letter": "B", "text": "IP KVM",            "is_correct": true  },
    { "letter": "C", "text": "A console connection", "is_correct": false },
    { "letter": "D", "text": "A virtual administration console", "is_correct": false }
  ],
  "suggested_answers": ["A", "B"],
  "answers": ["Definitely B and D...", "..."],
  "url": "https://www.examtopics.com/discussions/..."
}
```

`suggested_answers` là danh sách — hỗ trợ câu "Choose two/three".

## Cấu hình

| Biến | Mô tả | Mặc định |
|---|---|---|
| `MIN_DELAY` | Nghỉ tối thiểu giữa các câu (giây) | 2 |
| `MAX_DELAY` | Nghỉ tối đa giữa các câu (giây) | 5 |
| `RETRY_LIMIT` | Số lần retry khi lỗi | 3 |
| `OUTPUT_DIR` | Thư mục lưu kết quả | `output` |

## License

Dự án phục vụ mục đích học tập và nghiên cứu cá nhân.
