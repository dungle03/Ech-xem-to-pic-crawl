# ExamTopics Crawler

Công cụ tự động thu thập câu hỏi từ ExamTopics thông qua Google Search và lưu kết quả dưới dạng JSON.

## Tính năng

* Tìm kiếm câu hỏi theo mã đề, topic và số câu.
* Tự động truy cập trang ExamTopics từ kết quả Google.
* Loại bỏ popup/overlay.
* Thu thập nội dung câu hỏi và phần thảo luận.
* Lưu dữ liệu liên tục để tránh mất dữ liệu khi gián đoạn.
* Hỗ trợ tiếp tục từ lần chạy trước.
* Tự động retry khi gặp lỗi.
* Xuất dữ liệu JSON vào thư mục `output/`.

## Yêu cầu

* Python 3.8+
* Kết nối Internet
* Linux/macOS hoặc Windows (khuyến nghị WSL2)

## Cài đặt

### Ubuntu / Debian

```bash
sudo apt update

sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libasound2t64 \
    libatk-bridge2.0-0t64 \
    libgtk-3-0t64 \
    libgbm1 \
    libxkbcommon0
```

### Clone project

```bash
git clone <repository-url>
cd crawl_exam
```

### Tạo môi trường ảo

```bash
python3 -m venv venv
source venv/bin/activate
```

### Cài đặt dependencies

```bash
pip install -r requirements.txt
```

## Sử dụng

```bash
source venv/bin/activate
python3 tool.py
```

Thoát môi trường ảo:

```bash
deactivate
```

## Kết quả

Dữ liệu được lưu tại:

```text
output/{exam_code}_questions.json
```

Ví dụ:

```json
{
  "exam_code": "ex200",
  "topic": 1,
  "question_num": 1,
  "question": "...",
  "answers": ["..."],
  "url": "https://..."
}
```

## Cấu hình

| Biến          | Mô tả                          |
| ------------- | ------------------------------ |
| `DELAY`       | Thời gian chờ giữa các request |
| `RETRY_LIMIT` | Số lần retry khi lỗi           |
| `OUTPUT_DIR`  | Thư mục lưu kết quả            |

## License

Dự án phục vụ mục đích học tập và nghiên cứu cá nhân.
