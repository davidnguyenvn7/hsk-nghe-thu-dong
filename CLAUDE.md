# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này. Người dùng giao tiếp bằng tiếng Việt.

## Repo này là gì

Repo nội dung cho việc học tiếng Trung qua nghe thụ động:

- từ vựng HSK 3.0 cấp 2–3 có nghĩa Việt và câu ví dụ;
- 480 mẫu câu theo 12 chủ đề công việc (bất động sản, văn phòng, ngân hàng, xây dựng, giao thông);
- pipeline Python build dữ liệu + tạo audio.

Plugin WordPress nằm ở `../app/public/wp-content/plugins/hsk-nghe/` (site Local "Chinese listening") và import gói nội dung này. Đặc tả ở `docs/wordpress-plugin.md`, **mục 13 thay thế các phần cũ khi mâu thuẫn**. Đọc file đó trước khi sửa code plugin.

## Lệnh

```bash
pip install -r requirements.txt
python scripts/generate.py topic --name "Nhà hàng" --words 20 --per-word 2   # sinh nội dung bằng DeepSeek (cần DEEPSEEK_API_KEY trong .env)
python scripts/build.py          # luôn chạy sau khi sửa data/source
python scripts/make_audio.py --only words --topics 13    # clip audio (cần mạng; ffmpeg chỉ để tạo silence.mp3 lần đầu)
python scripts/pack.py           # → dist/hskn-pack-*.zip   (--no-audio: chỉ chữ, plugin giữ nguyên audio cũ)
wp hskn import dist/hskn-pack-….zip    # hoặc WP Admin → HSK Nghe → Import
```

Trên Windows: đặt `PYTHONIOENCODING=utf-8` (console cp1252 không in được tiếng Việt). Python không xác thực được SSL (antivirus chèn chứng chỉ) → `truststore` đã được dùng trong make_audio.py và generate.py.

## Quy tắc dữ liệu

- **Chỉ sửa `data/source/`.** `data/build/` và `docs/ngu-phap.md` là file sinh ra; sửa xong source thì chạy lại `build.py`.
- **Không sửa `data/vendor/hsk30/`.** Đó là danh sách HSK chính thức, nguồn MIT.
- Định dạng file nguồn là text phân tách bằng `|`, mỗi dòng một mục, dòng `#` là chú thích. Giữ đúng định dạng này. Không chuyển sang JSON/YAML.
- **ID tường minh trong file nguồn** (`S|03-S12|…`, `D|03-D2-1|A|…`, `T03-001|…`, `E|13-E007|…`). Không bao giờ đổi hay tái sử dụng ID: tiến độ người học trong plugin gắn với ID. `build.py` báo lỗi khi ID trùng và cảnh báo khi ID của lần build trước biến mất.
- `topic_words/NN-*.txt`: danh sách từ của chủ đề (`W|ID|chữ Hán`) + câu theo từ (`E|ID câu|ID từ|câu|nghĩa Việt|nghĩa Anh|ngữ pháp`). Từ HSK 2–3 dùng ID `H…`, từ khác dùng ID `T…` khai báo trong `topic_terms.txt`.
- Câu mới chỉ dùng từ HSK 1–3 cộng với từ đã có trong `topic_terms.txt`. Sau khi build, xem dòng "Từ chưa có trong HSK 1–3 lẫn topic_terms". Gặp từ chuyên ngành mới thì thêm vào `topic_terms.txt`, kèm pinyin có dấu cách giữa các âm tiết.
- Câu ví dụ (`examples/`) phải chứa đúng từ đích. `build.py` sẽ cảnh báo nếu không.
- Pinyin sai: thêm vào `pinyin_phrases.txt`, không sửa tay trong `data/build`.
- Nghĩa Việt: ngắn gọn, tự nhiên, ưu tiên nghĩa trong ngữ cảnh công việc.

## Việc còn dở (theo thứ tự ưu tiên)

1. Câu ví dụ cho 633 từ HSK3 còn thiếu: `python scripts/generate.py examples --level 3 --limit 100` (ghi vào `examples/hsk3b.txt`, định dạng `từ|câu|nghĩa|nghĩa Anh`).
2. Sinh câu E cho từ của 12 chủ đề có sẵn: `python scripts/generate.py sentences --topic 01 --per-word 2` (lặp cho 01–12).
3. Tạo audio đầy đủ (`make_audio.py` không tham số, ~11.000 clip), đóng gói và import.
4. Plugin: giai đoạn 4–6 của đặc tả (tiến độ/Leitner, `/me/*`, kế hoạch 4 tuần, hook gamification, PHPUnit).

Đã xong (2026-10-26): ID tường minh, `pack.py`, `generate.py` (DeepSeek), plugin giai đoạn 1–3 (import, REST, trình phát ghép MP3 phát nền được). `duration_ms` do plugin tự đọc từ frame MP3 khi import, không cần ffprobe.

## Quy ước code plugin (khi tới bước đó)

- Kiến trúc Controller → Service → Repository, bảng riêng tạo bằng `dbDelta`, REST namespace `hskn/v1`, CLI `wp hskn`.
- Bộ đếm (lượt nghe, XP, hộp Leitner) cập nhật nguyên tử bằng `INSERT … ON DUPLICATE KEY UPDATE x = x + 1`.
- Không dùng transient cho trạng thái quan trọng. Không dùng `ORDER BY RAND()`. Không để N+1 query khi dựng playlist.
- Endpoint `me/*` chỉ dùng `get_current_user_id()`, không nhận `user_id` từ client.
- Kết nối gamification qua `do_action('hskn_…')`, không gọi trực tiếp plugin khác.
