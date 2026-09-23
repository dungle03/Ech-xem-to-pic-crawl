# ExamTopics Crawler

Tự động thu thập câu hỏi từ ExamTopics, lưu kết quả dưới dạng JSON, sau đó chuyển sang HTML và DOCX để ôn tập.

## Tính năng

* Tìm kiếm qua DuckDuckGo (ít CAPTCHA), tự chuyển sang Google khi DuckDuckGo không ra kết quả.
* Thu hẹp truy vấn bằng `site:examtopics.com` để tăng độ chính xác.
* Tái sử dụng session/cookie xuyên suốt phiên crawl.
* Gõ query vào ô tìm kiếm như người dùng thật (humanize).
* Fingerprint macOS nhất quán qua CloakBrowser.
* Lọc link chính xác theo slug — bỏ qua trang tổng hợp, câu/mã đề khác và link wrapper.
* Thu thập đầy đủ: đề bài, hình ảnh, các lựa chọn (A/B/C/D...), đáp án gợi ý và đáp án bình chọn của cộng đồng (Community Most Voted & Vote breakdown).
* Đồng bộ User-Agent động và session cookies từ Playwright sang httpx đảm bảo tính nhất quán và chống chặn Cloudflare.
* Lấy cả URL hình trong đề bài và trong từng lựa chọn (nếu có).
* Chuyển kết quả sang HTML tự chứa CSS/JS và DOCX (ảnh nhúng sẵn) sau khi crawl xong.
* Trang HTML có hai chế độ: ôn tập chủ động (tìm kiếm, che/mở đáp án, đánh dấu câu cần ôn) và thi thử có hẹn giờ/chấm điểm.
* Tải ảnh song song khi convert DOCX (10 luồng).
* Nạp nội dung thảo luận siêu tốc qua HTTP-first (~1s thay vì 15s chờ tải quảng cáo/tracker).
* Nạp **đầy đủ bình luận**: trang ExamTopics chỉ render sẵn ~20-25 bình luận đầu, phần còn lại nằm sau nút "Load full discussion..." — tool tự gọi AJAX để lấy hết thay vì cắt cụt thảo luận.
* Cơ chế Opportunistic Link Harvester: tự động gom và nhớ các link discussion xuất hiện trên trang tìm kiếm để tái sử dụng, bỏ qua tìm kiếm khi đã có sẵn link.
* Hỗ trợ tham số `--proxy` (HTTP/SOCKS5) bảo vệ IP và hỗ trợ crawl quy mô lớn.
* Fallback tải trang qua HTTP khi trình duyệt load trang discussion bị treo.
* Dọn tab sau mỗi câu, chỉ giữ lại một tab tìm kiếm.
* Hỗ trợ mã đề nhiều định dạng: gạch nối, gạch dưới, dấu chấm (`sk0-005`, `az-104`, `FCSS_NST_SE-7.6`).
* Lưu liên tục sau mỗi câu, tiếp tục được từ lần chạy trước (không mất dữ liệu khi dừng giữa chừng).
* Retry tự động khi gặp lỗi.

## Yêu cầu

* Python 3.9+
* Kết nối Internet
* Linux/macOS hoặc Windows (WSL2 khuyến nghị)
* Màn hình hiển thị (khuyến nghị): mặc định tool chạy trình duyệt ở chế độ headed để giảm CAPTCHA. Trên server/CI không có màn hình, dùng thêm `--headless`.

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

### Chạy tương tác (Interactive)

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

Sau khi crawl xong, tool hỏi:

```
Convert sang HTML + DOCX? (y/N): y
HTML: output/sk0005_questions.html
DOCX: output/sk0005_questions.docx
```

### Chạy bằng tham số dòng lệnh (CLI Arguments)

```bash
# Crawl tự động và tự convert sau khi hoàn thành (-y)
python3 tool.py -e FCSS_NST_SE-7.6 -t 1 -r 1-50 -y

# Crawl qua Proxy HTTP hoặc SOCKS5
python3 tool.py -e az-104 -t 1 -r 1-100 -p http://127.0.0.1:8080 -y

# Chỉ convert file JSON đã có sang HTML + DOCX (không cần mở browser)
python3 tool.py --convert-only output/sk0005_questions.json

# Chạy ẩn cửa sổ trình duyệt (dùng trên server/CI không có màn hình)
python3 tool.py -e az-104 -t 1 -r 1-50 --headless -y

# Ẩn đáp án trong file DOCX để tự luyện (đáp án chỉ còn ở bảng Answer Key)
python3 tool.py --convert-only output/sk0005_questions.json --hide-answers

# Chỉ in cảnh báo/lỗi, tắt tiến độ (hợp với CI hoặc khi ghi log ra file)
python3 tool.py -e az-104 -r 1-100 -y --quiet

# In thêm chi tiết chẩn đoán (retry, cache, tiến độ tải ảnh...) để debug
python3 tool.py -e az-104 -r 1-10 --verbose
```

### Mức độ log

| Flag | Mức | Hiển thị |
|---|---|---|
| (mặc định) | INFO | Tiến độ + cảnh báo + lỗi, **giữ nguyên như trước** |
| `-q`, `--quiet` | WARNING | Chỉ cảnh báo và lỗi |
| `-v`, `--verbose` | DEBUG | Thêm chi tiết chẩn đoán |

Output mặc định không đổi so với các phiên bản trước; `--quiet`/`--verbose` chỉ để tinh chỉnh khi cần.
Hai flag loại trừ nhau (dùng cùng lúc sẽ báo lỗi).

## Cách hoạt động

Với mỗi câu hỏi, tool vận hành theo luồng tối ưu:

1. **Kiểm tra bộ nhớ đệm (Link Cache)**: Nếu câu hỏi đã có link trong cache (từ file JSON cũ hoặc được thu thập từ các lần tìm kiếm trước), tool dùng ngay mà không cần tìm kiếm.
2. **Tìm kiếm thông minh**: Nếu chưa có trong cache, tool gõ query vào DuckDuckGo (kèm `site:examtopics.com`). Trong quá trình này, tool tự động gom tất cả các link câu hỏi khác xuất hiện trên trang tìm kiếm để dùng lại cho các câu sau. Nếu DuckDuckGo không ra link khớp, tự chuyển sang Google.
3. **Nạp nội dung siêu tốc (Fast HTTP-first)**: Dùng `httpx` nạp trực tiếp mã nguồn HTML đã bypass Cloudflare vào tab (~1s) thay vì chờ 15s tải quảng cáo/tracker; tự động fallback sang điều hướng thông thường trong trình duyệt nếu HTTP gặp lỗi.
4. **Nạp đầy đủ bình luận**: ExamTopics chỉ render sẵn ~20-25 bình luận đầu và giấu phần còn lại sau nút "Load full discussion...". Tool gọi AJAX `load-complete` để thay khối bình luận bằng bản đầy đủ trước khi bóc dữ liệu. Nếu trang không có nút (nghĩa là đã đầy đủ) thì bỏ qua, không tốn request. Bước này chỉ thay `.outer-discussion-container` — đề bài, lựa chọn, đáp án và bảng vote nằm ngoài container đó nên không bị ảnh hưởng; nếu AJAX lỗi thì DOM giữ nguyên.

## Kết quả

Crawl lưu tại `output/{exam_code}_questions.json`. Convert sinh thêm `.html` và `.docx` cùng thư mục.

JSON mỗi câu có dạng:

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
  "community_most_voted": ["B"],
  "community_votes": [{"voted_answers": "B", "vote_count": 12, "is_most_voted": true}],
  "answers": ["Definitely B and D...", "..."],
  "url": "https://www.examtopics.com/discussions/..."
}
```

Ghi chú:

* `question_images` và `options[].images` chỉ lưu URL trong JSON; HTML tự nhúng ảnh base64 nên mở offline không cần mạng.
* `suggested_answers` là danh sách — hỗ trợ câu "Choose two/three".
* Câu không có hình thì các trường ảnh là mảng rỗng.

### Cấu trúc mã nguồn

* `examtopic/`: Gói module lõi phân tách theo trách nhiệm:
  * `config.py`: Quản lý cấu hình engine, hằng số, proxy và cache ảnh 2 tầng.
  * `parser.py`: Chuẩn hóa mã đề, so khớp slug, unwrap redirect và lưu JSON atomic.
  * `resolver.py`: Giải URL discussion **không cần search engine** bằng `question_id`
    + AJAX của ExamTopics (có verify title trước khi dùng). Anchor đến từ trang exam
    và từ mỗi câu đã crawl, lưu ở `output/.anchors.json`.
  * `crawler.py`: Điều phối tìm kiếm, nạp discussion, đồng bộ session và bóc dữ liệu.
  * `exporters/`: Dựng HTML ôn tập/thi thử (`html.py`) và Word kèm Answer Key (`docx.py`).
* `tool.py`: CLI entrypoint điều phối chính, re-export 100% tương thích ngược.
* `test_tool.py`: Bộ unit tests tự động kiểm thử toàn bộ luồng xử lý (hiện có 146 test).
* `docs/crawl-flow.html`: Sơ đồ tương tác luồng crawl (nguồn: `crawl-flow.workflow.json`).

### Kiểm thử

Chạy bộ unit test để xác minh tính toàn vẹn:

```bash
python3 -m unittest test_tool.py
```

### File đầu ra

| File | Mô tả |
|---|---|
| `{exam}_questions.json` | Dữ liệu gốc |
| `{exam}_questions.html` | Trang ôn tập tự chứa (ảnh base64), đáp án che mặc định, có tìm kiếm/đánh dấu câu cần ôn và chế độ thi thử |
| `{exam}_questions.docx` | Mở bằng Word/LibreOffice, đáp án in đậm xanh + dấu ✓, ảnh nhúng sẵn, kèm bảng tra đáp án nhanh (Answer Key) ở cuối tài liệu |
| `{exam}_errors.json` | Danh sách câu không lấy được (tách riêng để số record file chính khớp số câu convert được). Được **nạp lại và merge** khi chạy tiếp, không bị ghi đè mất |

## Cấu hình

Các giá trị dưới đây đọc từ **biến môi trường** khi khởi động, không cần sửa code:

| Biến | Mô tả | Mặc định |
|---|---|---|
| `MIN_DELAY` | Nghỉ tối thiểu giữa các câu (giây) | 2 |
| `MAX_DELAY` | Nghỉ tối đa giữa các câu (giây) | 5 |
| `RETRY_LIMIT` | Số lần retry khi lỗi | 3 |
| `BLOCKED_ABORT_STREAK` | Số câu bị chặn liên tiếp thì dừng phiên | 3 |
| `RETRY_HTTP_ATTEMPTS` | Số lần thử lại HTTP khi gặp 429/503 | 2 |
| `RETRY_HTTP_BACKOFF` | Backoff giữa các lần thử lại (giây) | 1 |
| `DEFAULT_OP_TIMEOUT` | Timeout thao tác trình duyệt (ms) | 30000 |
| `OUTPUT_DIR` | Thư mục lưu kết quả | `output` |

Ví dụ — crawl chậm và thận trọng hơn để né rate-limit:

```bash
MIN_DELAY=6 MAX_DELAY=12 RETRY_LIMIT=5 python3 tool.py -e az-104 -r 1-100 -y
```

Giá trị thiếu hoặc không hợp lệ sẽ tự động rơi về mặc định (không làm crash tool).

## License

Dự án phục vụ mục đích học tập và nghiên cứu cá nhân.
