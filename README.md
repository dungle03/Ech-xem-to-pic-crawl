# ExamTopics Crawler

Tự động thu thập câu hỏi từ ExamTopics, lưu kết quả dưới dạng JSON, sau đó chuyển sang HTML và DOCX để ôn tập.

## Tính năng

* Tìm kiếm qua DuckDuckGo (ít CAPTCHA), tự chuyển sang Google khi DuckDuckGo không ra kết quả.
* Mặc định mở trang chủ công cụ tìm kiếm và gõ query từng ký tự với độ trễ ngẫu nhiên như người dùng thật; DuckDuckGo gõ nhanh, Google gõ và submit chậm hơn để giảm CAPTCHA.
* Thu hẹp truy vấn bằng `site:examtopics.com` để tăng độ chính xác.
* Tái sử dụng session/cookie xuyên suốt phiên crawl.
* Fingerprint macOS nhất quán qua CloakBrowser.
* Lọc link chính xác theo slug — bỏ qua trang tổng hợp, câu/mã đề khác và link wrapper.
* Thu thập đầy đủ: đề bài, hình ảnh, các lựa chọn (A/B/C/D...), đáp án gợi ý và đáp án bình chọn của cộng đồng (Community Most Voted & Vote breakdown).
* Đồng bộ User-Agent động và session cookies từ Playwright sang httpx đảm bảo tính nhất quán và chống chặn Cloudflare.
* Lấy cả URL hình trong đề bài và trong từng lựa chọn (nếu có).
* Chuyển kết quả sang HTML tự chứa CSS/JS và DOCX (ảnh nhúng sẵn) sau khi crawl xong.
* Trang HTML có hai chế độ: ôn tập chủ động (tìm kiếm, che/mở đáp án, đánh dấu câu cần ôn) và thi thử có hẹn giờ/chấm điểm.
* Tải ảnh song song khi convert DOCX (10 luồng).
* Nạp nội dung thảo luận siêu tốc qua HTTP-first (~1s thay vì 15s chờ tải quảng cáo/tracker).
* **Đáp án cộng đồng**: suy ra từ badge `Selected Answer: X` của từng bình luận, cộng dồn theo số upvote (site đã bỏ `.voted-answers-tally`).
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
2. **Giải tất định từ trang liệt kê của vendor**: Tool tìm category thật của mã đề qua `/search/?q=<mã đề>` (category BẮT BUỘC — `/exams/<mã>/<mã>/` trả 404), rồi quét `/discussions/<category>/<n>/` để lấy URL discussion thật. Nhờ đó phần lớn câu được giải **không cần search engine**. Kết quả lưu ở `output/.discussion_urls.json` nên các lần chạy sau không phải dò lại.
3. **Tìm kiếm thông minh**: Câu không có trong danh sách trên mới cần search. Tool chỉ dùng một query có `site:examtopics.com`, gõ nhanh trên DuckDuckGo; nếu không có link khớp mới chuyển sang Google và gõ chậm hơn. Không còn lượt thử query bỏ `site:`/bọc mã đề trong ngoặc kép. Trong quá trình này, tool tự động gom các link câu hỏi khác xuất hiện trên trang tìm kiếm để dùng lại cho các câu sau.
4. **Nạp nội dung siêu tốc (Fast HTTP-first)**: Dùng `httpx` nạp trực tiếp mã nguồn HTML đã bypass Cloudflare vào tab (~1s) thay vì chờ 15s tải quảng cáo/tracker. **Chỉ fallback sang điều hướng trình duyệt khi lỗi TẠM THỜI** (429/503/lỗi mạng): nếu HTTP trả **404** thì thoát ngay và báo "câu bị paywall/gỡ bỏ" — mở browser cho link 404 chỉ tạo `ERR_HTTP_RESPONSE_CODE_FAILURE` rồi treo ~15s.
5. **Giãn nhịp & chống chặn**: Mọi request HTTP đi qua `resolver.fetch_html` để được giãn nhịp toàn cục. Đo trên trang thật: 8 worker song song → ~6 req/s, 0×429; 24 worker → 24×429 ngay lập tức. **Chỉ 429/503 mới thử lại** (tôn trọng header `Retry-After`); **404 là tất định** (cặp `id`+`slug` sai hoặc câu bị gỡ/paywall) nên kết thúc ngay, không đốt 28s backoff. Link 404 được ghi nhớ có thời hạn để không đâm lại.
6. **Bóc lựa chọn & đáp án**: Trang discussion không còn markup `.multi-choice-item`, nên lựa chọn được tách từ text đề bài (chỉ tách khi thấy A, B, C… liên tiếp từ A). Với q1–q10, tool lấy thêm **đáp án chính thức** từ trang exam (`Correct Answer: AD`). Với câu không có A/B/C/D (HOTSPOT, DRAG DROP…), tool gắn `question_type` và hiển thị lý do thay vì để trống im lặng.
7. **Đáp án cộng đồng**: `.voted-answers-tally` và `.most-voted-answer-badge` đã bị site bỏ, nên tool suy ra `community_most_voted` từ badge `Selected Answer: X` của từng bình luận, **cộng dồn theo số upvote** (`Selected Answer: B` trên bình luận 21 upvote → B). Chỉ kết luận khi tổng ≥ 2 để tránh một bình luận lẻ.

### Giới hạn đã biết

ExamTopics chỉ trả công khai một phần đề. Với `hqt-4180` (đề ghi 108 câu), phần truy cập được là **45 câu** có discussion trong trang liệt kê của vendor; q11+ trên trang exam và các câu mới thêm bị chặn sau đăng nhập (trả 404 với khách vãng lai). Đã kiểm chứng: 11 câu còn thiếu (32, 36, 39, 40, 42, 43, 46, 47, 49, 52, 54) trả 404 với **mọi** biến thể slug và từ nhiều IP — đây là paywall/gỡ bỏ, **không cứu được bằng cách đoán id**. Tool lấy tối đa phần công khai và ghi các câu còn thiếu vào `output/{exam_code}_errors.json`.

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
  * `resolver.py`: Giải URL discussion **không cần search engine**. Tìm category
    thật của mã đề qua `/search/?q=<mã đề>` (category BẮT BUỘC — `/exams/<mã>/<mã>/`
    trả 404), rồi quét trang liệt kê của vendor `/discussions/<category>/<n>/` để
    lấy URL discussion thật. Đáp án chính thức (q1–q10) lấy từ trang exam. Chi mục
    lưu ở `output/.discussion_urls.json`.
  * `crawler.py`: Điều phối tìm kiếm, nạp discussion, đồng bộ session và bóc dữ liệu.
    Mọi request HTTP đi qua `resolver.fetch_html` để được **giãn nhịp toàn cục** —
    ~9–11 request nhanh liên tiếp là Cloudflare chặn, và khi bị chặn trang còn trả
    **404 rỗng cho URL đúng**, nên 404 phải coi là "chưa chắc" và thử lại.
  * `exporters/`: Dựng HTML ôn tập/thi thử (`html.py`) và Word kèm Answer Key (`docx.py`).
* `tool.py`: CLI entrypoint điều phối chính, re-export 100% tương thích ngược.
* `test_tool.py`: Bộ unit tests tự động kiểm thử toàn bộ luồng xử lý (hiện có 156 test).
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
| `REQUEST_INTERVAL` | Nghỉ tối thiểu giữa hai request HTTP (giây) | 1 |
| `THROTTLE_ATTEMPTS` | Số lần thử lại khi gặp 429/503 | 3 |
| `THROTTLE_BACKOFF` | Backoff gốc giữa các lần thử lại (giây) | 4 |
| `DEFAULT_OP_TIMEOUT` | Timeout thao tác trình duyệt (ms) | 30000 |
| `OUTPUT_DIR` | Thư mục lưu kết quả | `output` |

Ví dụ — crawl chậm và thận trọng hơn để né rate-limit:

```bash
MIN_DELAY=6 MAX_DELAY=12 RETRY_LIMIT=5 python3 tool.py -e az-104 -r 1-100 -y
```

Giá trị thiếu hoặc không hợp lệ sẽ tự động rơi về mặc định (không làm crash tool).

## License

Dự án phục vụ mục đích học tập và nghiên cứu cá nhân.
