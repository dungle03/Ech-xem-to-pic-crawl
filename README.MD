# ExamTopics Crawler

Công cụ tự động thu thập câu hỏi từ ExamTopics thông qua Google Search và lưu kết quả dưới dạng JSON.

## Tính năng

* Tìm kiếm câu hỏi theo mã đề, topic và số câu.
* Tự động truy cập trang ExamTopics từ kết quả Google.
* Loại bỏ popup/overlay gây cản trở nội dung.
* Trích xuất câu hỏi và phần thảo luận.
* Lưu dữ liệu liên tục sau mỗi câu hỏi.
* Hỗ trợ tiếp tục từ lần chạy trước khi bị gián đoạn.
* Tự động retry khi gặp lỗi.
* Xuất dữ liệu JSON vào thư mục `output/`.

## Yêu cầu

* Python 3.8+
* Kết nối Internet
* Linux/macOS hoặc Windows (khuyến nghị WSL2)

## Cài đặt

```bash
git clone <repository-url>
cd crawl_exam

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

## Sử dụng

```bash
python3 tool.py
```

Sau đó nhập:

* Mã đề (ví dụ: `ex200`)
* Topic (mặc định: `1`)
* Phạm vi câu hỏi (ví dụ: `1-20`)

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

Các tham số có thể điều chỉnh trong `tool.py`:

| Biến          | Mô tả                          |
| ------------- | ------------------------------ |
| `DELAY`       | Thời gian chờ giữa các yêu cầu |
| `RETRY_LIMIT` | Số lần thử lại khi lỗi         |
| `OUTPUT_DIR`  | Thư mục lưu kết quả            |

## Lưu ý

* Không nên crawl với tốc độ quá cao để tránh bị Google giới hạn truy cập.
* Khuyến nghị tăng `DELAY` nếu gặp CAPTCHA hoặc rate limit.
* Nên crawl theo từng đợt nhỏ để đảm bảo tính ổn định.

## License

Dự án phục vụ mục đích học tập và nghiên cứu cá nhân. Người dùng chịu trách nhiệm tuân thủ điều khoản sử dụng của các dịch vụ liên quan.
