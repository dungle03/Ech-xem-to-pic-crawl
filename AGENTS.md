# AGENTS.md — Quy Chuẩn Tích Hợp TypeSafe AI (Jev System One)

Tài liệu này là chỉ thị tối cao (system instructions) cho toàn bộ AI Coding Agent (Codex CLI, Claude Code, Cursor...) khi làm việc trong repository `examtopic-crawl`.

Tuân thủ trực tiếp các nguyên lý thiết kế từ **TypeSafe Skill** (`~/.codex/skills/typesafe-ai/SKILL.md`) và **Jev Review Skill** (`~/.codex/skills/jev-review/SKILL.md`).

---

## 1. NGUYÊN TẮC CỐT LÕI (CORE PRINCIPLES)

> **"Code owns the workflow; Jev supplies programmable common sense."**  
> *(Code làm chủ luồng điều khiển; Jev cung cấp các phán đoán ngữ nghĩa chuẩn xác).*

1. **Tuân thủ quy tắc RTK**: Mọi lệnh shell trong repository này **bắt buộc** phải có tiền tố `rtk` (ví dụ: `rtk git status`, `rtk pytest`, `rtk python tool.py`).
2. **Tuyệt đối không can thiệp code/tài liệu trước khi đánh giá**: Mọi hành vi sửa code trực tiếp khi chưa thực hiện phán đoán qua Jev đều bị coi là vi phạm quy chuẩn repo.
3. **Jev là System One Decision-maker**: Jev trả về quyết định chuẩn kiểu dữ liệu (`typed decisions`), phân phối xác suất và điểm tin cậy (`calibrated confidence`), không sinh code tự do.
4. **Phương Thức Gọi Đảm Bảo (Zero-Failure Execution)**:
   - Trong Codex CLI, các tool `mcp__*` bị chặn bởi nhân Rust với lỗi `unsupported call`.
   - Do đó, Agent **BẮT BUỘC sử dụng các tiện ích CLI trực tiếp qua `exec_command`**:
     - **`rtk jev-eval '<json_payload>'`**: Đánh giá các câu hỏi logic, điều kiện, rủi ro cụ thể (`noul`, `choice`, `score`).
     - **`rtk jev-review --task "..."`**: Tự động lấy `git diff` và chấm điểm chất lượng mã nguồn trên 19 chiều (độ phức tạp, bảo mật, tính module, kiểm thử...).

---

## 2. CHUẨN THIẾT KẾ STATE & QUESTIONS (THEO TYPESAFE SKILL)

### Quy Tắc Xây Dựng State:
- Luôn tổ chức `state` dưới dạng **JSON object có đặt tên rõ ràng** (`named fields`), không truyền một chuỗi text trần trụi.
- Bao gồm: nhiệm vụ người dùng yêu cầu, file mục tiêu, đoạn code liên quan và đề xuất thay đổi.

### Quy Tắc Thiết Kế Câu Hỏi:
- **Question ID** chỉ dùng cho code xử lý (Jev không nhìn thấy ID câu hỏi). Toàn bộ ngữ nghĩa và yêu cầu phải được viết đầy đủ, độc lập trong trường `instructions`.
- Luôn cung cấp tùy chọn bao quát (`other` / `no_material_issue`) trong `criteria` của `choice` để mô hình không bị ép chọn sai.
- Thang đo của `score` phải được mô tả rõ ràng, cụ thể theo từng mức độ ảnh hưởng thực tế đến crawler.

---

## 3. MẪU GỌI PHÁN ĐOÁN ĐIỀU KIỆN (SPECULATIVE FAN-OUT VỚI JEV-EVAL)

Khi nhận bất kỳ yêu cầu sửa code, tối ưu, hoặc thay đổi kiến trúc/tài liệu trong `examtopic-crawl`, Agent **BẮT BUỘC** chạy lệnh `rtk jev-eval` với cấu trúc Speculative Fan-out mẫu sau:

```bash
rtk jev-eval '{
  "state": {
    "user_prompt": "Nội dung yêu cầu của người dùng (ví dụ: tối ưu crawler, đổi cấu hình headless, sửa regex parser...)",
    "target_files": ["tool.py", "README.md"],
    "current_behavior": "Trình duyệt CloakBrowser chạy macOS fingerprint, crawl tuần tự qua DDG/Google, cache ảnh và xuất JSON/HTML/DOCX",
    "proposed_change": "Mô tả cụ thể hành động agent dự định thực hiện"
  },
  "questions": {
    "task_category": {
      "type": "choice",
      "instructions": "Phân loại bản chất của thay đổi được đề xuất trong `state.proposed_change` thuộc nhóm nào dưới đây?",
      "criteria": {
        "crawler_logic": "Sửa thuật toán bóc tách HTML, parser câu hỏi, xử lý JSON hoặc lưu file",
        "browser_network": "Thay đổi cấu hình trình duyệt, timeout, fingerprint, proxy hoặc cờ headless",
        "performance_opt": "Tối ưu đa luồng tải ảnh, dọn dẹp RAM/tab, giảm điểm nghẽn hiệu năng",
        "documentation_only": "Chỉ cập nhật tài liệu README/hướng dẫn, không thay đổi logic chạy",
        "other": "Các thay đổi khác không thuộc các nhóm trên"
      }
    },
    "risk_score": {
      "type": "score",
      "instructions": "Đánh giá mức độ rủi ro đối với độ ổn định của crawler và nguy cơ bị ExamTopics/Cloudflare chặn khi áp dụng `state.proposed_change`",
      "criteria": [
        "Mức 0: An toàn tuyệt đối, chỉ sửa doc hoặc refactor code nội bộ vô hại",
        "Mức 1: Rủi ro thấp, ảnh hưởng nhỏ đến UI hiển thị nhưng crawler chạy ổn định",
        "Mức 2: Rủi ro trung bình, có thể gây chậm tiến trình, tốn tài nguyên hoặc lỗi tương thích nhẹ",
        "Mức 3: Rủi ro cao, nguy cơ cao bị phát hiện bot, treo luồng hoặc làm hỏng dữ liệu crawl"
      ]
    },
    "is_breaking_change": {
      "type": "noul",
      "instructions": "Đánh giá xác suất (Yes/No): Thay đổi này có phá vỡ tính tương thích ngược với cấu trúc file JSON output (`sk0005_questions.json`) hoặc định dạng HTML/DOCX đã tạo trước đó không?"
    }
  }
}'
```

---

## 4. MA TRẬN PHÂN NHÁNH HÀNH ĐỘNG (CONFIDENCE-GATED MATRIX)

Agent sử dụng **`probabilities`** và **`confidence`** từ kết quả JSON của `jev-eval` để quyết định bước tiếp theo:

| Điều Kiện Phán Đoán Từ Jev | Hành Động Của Agent |
|---|---|
| **Rủi ro thấp** (`risk_score < 1.0`) **VÀ** `is_breaking_change < 0.2` **VÀ** `confidence >= 0.8` | **Tự động thực thi**: In tóm tắt phán đoán của Jev và tiến hành sửa file ngay. |
| **Rủi ro trung bình** (`1.0 <= risk_score < 2.0`) **HOẶC** `confidence < 0.8` | **Cảnh báo thận trọng**: In chi tiết điểm rủi ro của Jev, giải thích trade-off và yêu cầu người dùng xác nhận trước khi sửa code. |
| **Rủi ro cao** (`risk_score >= 2.0`) **HOẶC** `is_breaking_change >= 0.7` | **Chặn can thiệp trực tiếp**: Báo cáo nguy cơ vỡ crawler/chặn IP, đề xuất phương án an toàn hơn thay thế. |

---

## 5. QUY TRÌNH REVIEW VÀ CẢI TIẾN CODE (JEV REVIEW LOOP)

Khi thực hiện các thay đổi code trong `tool.py`:

```text
Ý định thay đổi ➔ jev-eval (thẩm định rủi ro) ➔ Sửa code ➔ jev-review (chấm điểm) ➔ Tinh chỉnh theo điểm yếu
```

1. **Bước 1 (Đánh giá trước khi sửa)**: Chạy `rtk jev-eval` với mẫu fan-out để kiểm tra rủi ro phá vỡ.
2. **Bước 2 (Thực hiện sửa code)**: Áp dụng code theo thiết kế đã được Jev thẩm định an toàn.
3. **Bước 3 (Chấm điểm sau khi sửa)**: Chạy lệnh audit chất lượng mã nguồn:
   ```bash
   rtk jev-review --task "Mô tả thay đổi vừa thực hiện"
   ```
4. **Bước 4 (Cải thiện theo điểm số)**: Xem các tiêu chí có điểm thấp (`cognitiveComplexity`, `reliability`, `modularity`...) hoặc warning trong JSON trả về để tinh chỉnh code trước khi báo hoàn thành cho người dùng.
