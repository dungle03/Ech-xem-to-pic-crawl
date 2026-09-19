# Jev — Hướng dẫn gọi từ Coding Agent

**Mục đích:** dùng Jev để lấy phán đoán có xác suất (noul / choice / score) và chấm điểm chất lượng code.
**Phạm vi:** dùng được cho mọi project, không phụ thuộc ngôn ngữ hay cấu trúc repo.

> **Mang sang project mới — chỉ cần 2 bước:**
> 1. Copy file này vào `<project>/AGENTS.md`
> 2. Đảm bảo project đã `trust_level = "trusted"` trong `~/.codex/config.toml` (nếu không, sandbox chặn mạng → xem **mục 5**)
>
> Key đọc tự động từ `~/.jev.env`, không cần cấu hình gì thêm.

---

## 1. QUY TẮC BẮT BUỘC

> **KHÔNG gọi MCP tool `mcp__jev__*`.** Codex core chặn các tool này bằng lỗi `unsupported call`.

MCP tool có thể **hiện** trong danh sách tool nhưng **không gọi được** — đây là bug của Codex
(`codex_core::tools::router`, nhánh `core/src/tools/handlers/dynamic.rs`), không phải lỗi cấu hình.
Các biến thể đã kiểm chứng đều fail: `unsupported call: mcp__jev`, `unsupported call: jev`,
`unsupported call: functions`. Bật/tắt `tool_search`, `js_repl`, `non_prefixed_mcp_tool_names`
đều **không** khắc phục được.

**Cách đúng:** gọi qua shell bằng `exec_command`:

```bash
rtk jev-eval   '<json_payload>'      # phán đoán noul / choice / score
rtk jev-review --task "<mô tả>"      # chấm điểm chất lượng code
```

> Quy tắc RTK: mọi lệnh shell trong repo này phải có tiền tố `rtk`.

---

## 2. `jev-eval` — PHÁN ĐOÁN NGỮ NGHĨA

### Cách truyền input (cả 3 đều hoạt động)

```bash
rtk jev-eval '{"state":{...},"questions":{...}}'   # inline JSON
rtk jev-eval /path/to/payload.json                 # từ file
cat payload.json | rtk jev-eval -                  # từ stdin
```

Payload **bắt buộc** có `state` và `questions`. Trường `model` là tùy chọn.

### Ba loại câu hỏi

| Loại | Trả về | Dùng khi |
|---|---|---|
| `noul` | xác suất 1 điều kiện đúng/sai | câu hỏi nhị phân |
| `choice` | 1 lựa chọn từ criteria map | phân loại |
| `score` | vị trí trên thang có thứ tự | đánh giá mức độ |

### Payload mẫu — đủ cả 3 loại

```bash
rtk jev-eval '{
  "state": {
    "user_prompt": "Mô tả yêu cầu người dùng",
    "target_files": ["src/foo.py"],
    "proposed_change": "Mô tả thay đổi agent định làm"
  },
  "questions": {
    "is_breaking_change": {
      "type": "noul",
      "instructions": "Đánh giá xác suất (Yes/No): thay đổi này có phá vỡ tương thích ngược không?"
    },
    "task_category": {
      "type": "choice",
      "instructions": "Phân loại bản chất thay đổi trong state.proposed_change.",
      "criteria": {
        "logic":         "Sửa thuật toán hoặc xử lý dữ liệu",
        "config":        "Đổi cấu hình, timeout, tham số môi trường",
        "performance":   "Tối ưu hiệu năng, tài nguyên",
        "docs_only":     "Chỉ sửa tài liệu, không đổi logic",
        "other":         "Không thuộc nhóm nào trên"
      }
    },
    "risk_score": {
      "type": "score",
      "instructions": "Đánh giá mức độ rủi ro khi áp dụng state.proposed_change.",
      "criteria": [
        "Mức 0: an toàn tuyệt đối, chỉ sửa doc hoặc refactor nội bộ vô hại",
        "Mức 1: rủi ro thấp, ảnh hưởng nhỏ, hệ thống vẫn ổn định",
        "Mức 2: rủi ro trung bình, có thể gây chậm hoặc lỗi tương thích nhẹ",
        "Mức 3: rủi ro cao, có thể hỏng dữ liệu hoặc treo hệ thống"
      ]
    }
  }
}'
```

### Kết quả trả về (đã kiểm chứng)

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "is_breaking_change": { "type": "noul", "noul": 0.07 },
    "task_category": {
      "type": "choice", "choice": "logic", "confidence": 0.76,
      "probabilities": { "logic": 0.82, "config": 0.18, "other": 0.0 }
    },
    "risk_score": {
      "type": "score", "score": 1.97, "confidence": 0.96,
      "legend": { "0": "...", "1": "...", "2": "..." },
      "probabilities": { "0": 0.0, "1": 0.02, "2": 0.98 }
    }
  },
  "usage": { "input_tokens": 434, "output_tokens": 79 }
}
```

**Lưu ý quan trọng về `confidence`:**

> Chỉ `choice` và `score` trả về `confidence`. **`noul` KHÔNG trả về `confidence`.**
> Vì vậy đừng viết điều kiện kiểu `confidence >= 0.8` áp cho kết quả `noul` — nó sẽ luôn false.
> Với `noul`, suy ra độ chắc chắn từ chính xác suất: `certainty = max(p, 1 - p)`.

### Bốn quy tắc viết câu hỏi

1. **Question ID không gửi cho model.** Chỉ code của bạn dùng ID. Toàn bộ ngữ nghĩa phải nằm
   trong `instructions` — viết đầy đủ, độc lập, không viết tắt.
2. **`state` phải là JSON object có tên field rõ ràng**, không truyền chuỗi text trần.
   Tham chiếu field lồng nhau bằng backtick, ví dụ `` `ticket.text` ``.
3. **`choice` bắt buộc có phương án bao quát** (`other`) để model không bị ép chọn sai.
4. **`score` cần ít nhất 2 mức**, mô tả tình huống cụ thể — không dùng "thấp/trung bình/cao" trống rỗng.

Có thể hỏi nhiều câu độc lập trong 1 lần gọi — chúng chạy song song và **không thấy kết quả của nhau**.

---

## 3. `jev-review` — CHẤM ĐIỂM CHẤT LƯỢNG CODE

Tự động lấy `git diff HEAD` (fallback `git diff --staged`) rồi chấm trên ~19 chiều.

```bash
rtk jev-review --task "Mô tả thay đổi vừa thực hiện"
```

Hoặc truyền diff thủ công:

```bash
rtk jev-review --task "..." --diff "diff nội dung..."
```

### Kết quả trả về (đã kiểm chứng)

```json
{
  "metrics": {
    "correctness":         { "applicable": false },
    "readability":         { "applicable": true, "score": 6.6, "confidence": 0.68, "summary": "..." },
    "cognitiveComplexity": { "applicable": false }
  },
  "priorities": [
    { "metric": "readability", "severity": "low", "reason": "..." }
  ]
}
```

**Cách đọc:**
- Chiều có `"applicable": false` nghĩa là diff quá nhỏ để chấm — **không phải lỗi**.
- Chỉ quan tâm chiều `applicable: true`.
- `priorities` liệt kê chiều yếu nhất cần cải thiện — đây là tín hiệu để agent sửa code.
- Jev **không** giải thích nguyên nhân gốc. Agent phải tự đọc code, chẩn đoán, sửa, rồi chấm lại.

> `jev-review` cần API key. Key đọc từ `~/.jev.env` (`JEV_API_KEY` hoặc `TYPESAFE_API_KEY`),
> fallback sang biến môi trường. Không cần export thủ công nếu `~/.jev.env` đã có.

---

## 4. QUY TRÌNH KHUYẾN NGHỊ

```text
Ý định thay đổi
  → jev-eval   (thẩm định rủi ro trước khi sửa)
  → sửa code
  → jev-review (chấm điểm sau khi sửa)
  → tinh chỉnh theo priority
  → jev-review (chấm lại để xác nhận cải thiện)
```

Với thay đổi không đáng kể (sửa typo, đổi comment), **bỏ qua** bước Jev để tiết kiệm thời gian.

---

## 5. SANDBOX MẠNG — ĐIỀU KIỆN TIÊN QUYẾT

> **Jev cần mạng. Trong Codex sandbox, mạng chỉ được mở cho project đã `trusted`.**

Đây là nguyên nhân hỏng phổ biến nhất khi mang hướng dẫn này sang project mới.
Triệu chứng: `Temporary failure in name resolution` hoặc `Errno -3`.

**Kiểm tra nhanh — chạy trong project hiện tại:**

```bash
rtk jev-eval '{"state":{"x":1},"questions":{"q":{"type":"noul","instructions":"is x positive"}}}'
```

| Kết quả | Nghĩa là |
|---|---|
| Trả về JSON có `noul` | ✅ sẵn sàng, dùng bình thường |
| `Temporary failure in name resolution` | ❌ sandbox chặn DNS → xem cách sửa bên dưới |
| `permission denied` / `Operation not permitted` trên socket | ❌ sandbox chặn network syscall |

**Cách sửa — thêm project vào danh sách trusted:**

Mở `~/.codex/config.toml`, thêm:

```toml
[projects."/duong/dan/tuyet-doi/toi/project"]
trust_level = "trusted"
```

Sau đó **khởi động lại Codex** (sandbox policy chỉ đọc lúc start).

Kiểm tra project đã trusted chưa:

```bash
grep '\[projects' ~/.codex/config.toml
```

> **Vì sao phải trusted?** Codex sandbox chặn network mặc định cho path chưa tin cậy.
> `jev-eval` gọi `https://api.typesafe.ai` nên bị chặn ở tầng DNS.
> Đây **không phải** lỗi của Jev, không phải lỗi key, và không sửa được từ trong phiên —
> agent không thể tự vượt sandbox nếu approval policy là `Never`.

**Với môi trường không dùng Codex sandbox** (Claude Code, Cursor, CI, chạy tay):
không cần bước này, `jev-eval` gọi mạng trực tiếp.

---

## 6. XỬ LÝ LỖI

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `unsupported call: mcp__jev` | bug Codex MCP router | dùng `rtk jev-eval` qua shell, đừng gọi MCP |
| `Temporary failure in name resolution` / `Errno -3` | sandbox chặn DNS | thêm project vào `trust_level = "trusted"`, xem mục 5 |
| `Could not reach the Jev API` | mạng bị chặn | như trên |
| `Error: Invalid JSON input` | payload sai cú pháp | kiểm tra quote/escape; dùng file hoặc stdin |
| `TYPESAFE_API_KEY not found` | thiếu key | kiểm tra `~/.jev.env` |
| `TypeSafe API HTTP 401` | key sai/hết hạn | rotate key tại console.typesafe.ai |
| mọi chiều `applicable: false` | diff rỗng hoặc quá nhỏ | không phải lỗi; thêm thay đổi thật rồi chấm lại |

---

## 7. KIỂM TRA NHANH

```bash
rtk jev-eval '{"state":{"x":1},"questions":{"q1":{"type":"noul","instructions":"is x positive"}}}'
```

Kỳ vọng: `{"model":"jev-1.13.0","answers":{"q1":{"type":"noul","noul":0.99}},...}`

Lệnh này chạy được nghĩa là Jev đã sẵn sàng: network OK, key OK, server OK.

Thứ tự chẩn đoán khi lệnh fail:
1. `Temporary failure in name resolution` → sandbox chặn mạng → **mục 5**
2. `TYPESAFE_API_KEY not found` → thiếu key → kiểm tra `~/.jev.env`
3. `HTTP 401` → key sai/hết hạn → rotate tại console.typesafe.ai
4. Còn lại → xem bảng **mục 6**
