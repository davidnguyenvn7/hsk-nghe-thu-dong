# Đặc tả plugin WordPress: HSK Nghe Thụ Động

Tài liệu này mô tả cách plugin nên hoạt động, để code bằng Claude Code trong VS Code. Dữ liệu lấy từ repo này. Plugin không tự sinh nội dung mà chỉ **import gói nội dung** (JSON + audio) rồi phục vụ người học.

Slug đề xuất: `hsk-nghe` · Prefix PHP: `HSKN_` · REST namespace: `hskn/v1` · Prefix bảng: `{$wpdb->prefix}hskn_`

---

## 1. Luồng tổng thể

```
repo này (Python)                         WordPress (PHP + JS)
─────────────────                         ─────────────────────────────
data/source/*.txt ──build.py──► data/build/*.json ─┐
                                                   ├─► content pack (.zip) ──► wp hskn import
data/build/*.json ──make_audio.py──► audio/clips/*.mp3 + manifest.json ─┘                │
                                                                                          ▼
                                                   bảng hskn_* + wp-content/uploads/hskn/<pack>/clips/
                                                                                          │
                                         REST hskn/v1 ◄── trình phát JS (shortcode / Bricks element)
                                                                                          │
                                         hskn_progress, hskn_listen_log ──► do_action(...) → plugin gamification
```

Nguyên tắc:

1. **Nội dung soạn ở repo, không soạn trong WP Admin.** Admin chỉ xem, bật/tắt, import. Như vậy nội dung có git history, và build/audio chạy được offline.
2. **Audio là clip lẻ đặt tên theo hash nội dung** (`clips/<sha1-16>.mp3`). Sửa một câu thì chỉ câu đó đổi hash. Import lại chỉ upload clip mới. File có thể cache `immutable` vĩnh viễn trên Cloudflare.
3. **Bài nghe được ghép ở trình duyệt từ clip lẻ.** Nhờ vậy người dùng tự chọn chế độ (Trung–Việt / chỉ Trung), tốc độ, số lần lặp, khoảng lặng mà không phải render lại MP3. File ghép sẵn (`tracks/*.mp3`) chỉ dùng cho **chế độ nền / tải offline** (xem mục 6).

---

## 2. Gói nội dung (content pack)

Một file zip, tạo bằng `python scripts/pack.py` (cần viết, xem mục 11):

```
hskn-pack-2026.10.26.zip
├─ pack.json              { "version": "2026.10.26", "hsk_standard": "3.0", "created_at": "...", "counts": {...} }
├─ topics.json            data/build/topics.json
├─ vocab.json             data/build/vocab.json
├─ sentences.json         data/build/sentences.json
├─ topic_terms.json       data/build/topic_terms.json
├─ manifest.json          audio/manifest.json   (id → clip, tracks)
├─ clips/*.mp3
└─ tracks/*.mp3           (tuỳ chọn, cho chế độ nền / tải về)
```

ID ổn định, không bao giờ tái sử dụng:

| Loại | Mẫu ID | Ví dụ |
|---|---|---|
| Từ HSK | `H{cấp}-{stt}` theo danh sách chính thức | `H2-004` (安静) |
| Câu đơn | `{chủ đề}-S{nn}` | `03-S12` |
| Lượt hội thoại | `{chủ đề}-D{n}-{lượt}` | `11-D2-1` |
| Bài nghe | `topic-{id}`, `vocab-hsk{cấp}-{nn}` | `vocab-hsk3-07` |

> Lưu ý ID câu: ID đánh theo thứ tự dòng trong file nguồn. **Chèn câu vào giữa sẽ làm lệch ID** các câu sau, kéo theo tiến độ người dùng bị gán sai câu. Quy ước: chỉ thêm câu mới ở cuối file chủ đề. Muốn bỏ câu thì đánh dấu, không xoá dòng. Khi làm plugin, nên đổi sang ID tường minh trong file nguồn (`S|03-S12|…`), xem mục 11.

---

## 3. Cơ sở dữ liệu

Theo kiến trúc Controller → Service → Repository, dùng bảng riêng. Tạo bảng bằng `dbDelta` trong activation hook, có `hskn_db_version` để migrate.

### Nội dung (ghi đè khi import)

```sql
hskn_packs      (id PK, version UNIQUE, imported_at, counts JSON, is_active TINYINT)

hskn_topics     (id CHAR(2) PK, slug, name_vi, name_zh, description, sort, is_active)

hskn_words      (id VARCHAR(8) PK,            -- H2-004
                 hanzi, pinyin, level TINYINT, pos VARCHAR(64), vi, en,
                 freq_rank INT NULL,
                 example_zh, example_pinyin, example_vi,
                 content_hash CHAR(16),         -- phát hiện thay đổi khi import
                 KEY (level), KEY (hanzi))

hskn_sentences  (id VARCHAR(12) PK,           -- 03-S12, 11-D2-1
                 topic_id CHAR(2), type ENUM('S','D'), dialogue_id VARCHAR(10) NULL,
                 speaker CHAR(1) NULL, zh, pinyin, vi, grammar,
                 max_level TINYINT, tokens JSON, sort INT,
                 content_hash CHAR(16),
                 KEY (topic_id, sort), KEY (dialogue_id))

hskn_word_sentence (word_id, sentence_id, PRIMARY KEY (word_id, sentence_id), KEY (sentence_id))

hskn_terms      (id AUTO PK, topic_id, hanzi, pinyin, vi, level TINYINT, UNIQUE (topic_id, hanzi))

hskn_audio      (item_type ENUM('word','sentence','track'), item_id VARCHAR(16),
                 kind VARCHAR(16),              -- zh | zh_slow | vi | word | example | example_vi | track
                 file VARCHAR(64),              -- clips/ab12….mp3
                 duration_ms INT NULL,
                 PRIMARY KEY (item_type, item_id, kind))

hskn_tracks     (id VARCHAR(24) PK, type ENUM('topic','vocab','custom'), title, file NULL, items JSON, sort)
```

### Người học (không bao giờ ghi đè khi import)

```sql
hskn_progress   (user_id BIGINT, item_type ENUM('word','sentence'), item_id VARCHAR(16),
                 box TINYINT DEFAULT 0,          -- Leitner 0–5
                 listen_count INT DEFAULT 0,
                 last_listened_at DATETIME NULL,
                 due_at DATETIME NULL,
                 status ENUM('new','learning','known') DEFAULT 'new',
                 PRIMARY KEY (user_id, item_type, item_id), KEY (user_id, due_at))

hskn_listen_log (id BIGINT AUTO PK, user_id, track_id, session_id CHAR(36),
                 seconds INT, items_heard INT, started_at, ended_at,
                 KEY (user_id, started_at))

hskn_plan       (user_id PK, plan_key VARCHAR(32), start_date DATE, settings JSON)
```

Bài học từ lần review plugin gamification trước:

- **Cập nhật bộ đếm phải nguyên tử.** Dùng `INSERT … ON DUPLICATE KEY UPDATE listen_count = listen_count + 1`, không đọc → cộng → ghi.
- **Không dùng transient cho trạng thái quan trọng** (phiên nghe, tiến độ). Transient có thể biến mất khi bật Redis Object Cache. Transient/object cache chỉ dùng cho dữ liệu đọc nhiều mà tính lại được, như danh sách chủ đề hay thống kê.
- **Không dùng `ORDER BY RAND()`** khi trộn câu. Lấy danh sách ID rồi `shuffle()` trong PHP hoặc JS.
- **Không để N+1 query** khi trả playlist: lấy câu và audio của cả bài bằng 2 query `WHERE id IN (…)`.

---

## 4. Import

### WP-CLI (dùng chính)

```
wp hskn import /path/hskn-pack-2026.10.26.zip [--dry-run] [--skip-audio]
wp hskn status
wp hskn verify-audio          # kiểm tra mọi file trong hskn_audio có tồn tại
```

Thuật toán import (`ImportService`):

1. Giải nén vào thư mục tạm, đọc `pack.json`, so phiên bản.
2. Validate: mọi `sentence.topic` có trong topics, mọi id trong `manifest` có trong JSON, mọi file clip tồn tại.
3. Copy `clips/*.mp3` sang `wp-content/uploads/hskn/clips/`, **bỏ qua file đã có cùng tên** (tên là hash nên trùng tên tức trùng nội dung). **Không đưa vào Media Library**: ~8.000 clip sẽ làm nặng bảng `wp_posts`.
4. Upsert nội dung trong một transaction: `INSERT … ON DUPLICATE KEY UPDATE`. Chỉ ghi khi `content_hash` khác.
5. Mục không còn trong gói thì đặt `is_active = 0`, **không xoá**, vì `hskn_progress` còn tham chiếu.
6. Ghi `hskn_packs`, xoá cache đọc (`wp_cache_delete` các key `hskn_*`).
7. Chạy được lại nhiều lần mà kết quả như nhau (idempotent).

### Admin (phụ)

Trang **HSK Nghe → Import**: upload zip. Gói đầy đủ vài trăm MB, nên với hosting giới hạn upload, hướng dẫn upload qua SFTP rồi bấm "Import từ thư mục". Việc import chạy theo lô qua Action Scheduler hoặc WP-Cron, có thanh tiến độ, vì PHP `max_execution_time` không đủ cho 8.000 file.

---

## 5. REST API (`hskn/v1`)

Tất cả trả JSON. Endpoint `me/*` yêu cầu đăng nhập (cookie + nonce `wp_rest`, hoặc token nếu có app mobile sau này).

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/topics` | 12 chủ đề + thống kê; cache 1 giờ |
| GET | `/topics/{id}` | chủ đề + câu (gom hội thoại) + từ chuyên ngành |
| GET | `/words?level=2&topic=03&q=租&page=1&per_page=50` | tra từ; `q` tìm theo hán tự/pinyin/nghĩa |
| GET | `/words/{id}` | từ + ví dụ + các câu chủ đề có chứa từ đó |
| GET | `/tracks` | danh sách bài nghe |
| GET | `/tracks/{id}/playlist?mode=zh-vi&repeat=2` | **playlist đã dựng sẵn** cho trình phát (xem dưới) |
| GET | `/me/today` | việc hôm nay theo kế hoạch 4 tuần + mục đến hạn ôn |
| POST | `/me/listen` | heartbeat phiên nghe (mỗi 30 giây) |
| POST | `/me/progress` | `{item_type, item_id, action: heard|known|again}` |
| GET | `/me/stats` | tổng phút nghe, chuỗi ngày, số từ đã thuộc |
| PUT | `/me/plan` | bắt đầu / đổi kế hoạch, cài đặt nghe mặc định |

### Playlist

Server trả danh sách "bước". Trình phát chỉ việc chạy lần lượt, không cần biết logic:

```json
{
  "track": "topic-03",
  "title": "Cho thuê bất động sản",
  "settings": {"mode": "zh-vi", "repeat": 2, "gap_ms": 1200, "end_gap_ms": 2000},
  "steps": [
    {"item": "03-S01", "kind": "zh",      "src": "/wp-content/uploads/hskn/clips/9f2c….mp3",
     "text": "这套房子一个月房租多少钱？", "pinyin": "Zhè tào fángzi…", "vi": "Căn này…"},
    {"pause": 1200},
    {"item": "03-S01", "kind": "vi",      "src": ".../a71e….mp3"},
    {"pause": 1200},
    {"item": "03-S01", "kind": "zh_slow", "src": ".../c003….mp3"},
    {"pause": 2000}
  ]
}
```

`PlaylistService::build(track, settings)` là nơi duy nhất chứa quy tắc ghép, đúng như `make_audio.py`:

- Câu: Trung → (Việt) → Trung chậm × (repeat−1)
- Từ: từ → (nghĩa) → từ → ví dụ chậm → (nghĩa ví dụ)
- Hội thoại: lượt A giọng nữ, B giọng nam (đã nằm sẵn trong clip)

---

## 6. Trình phát (frontend)

Viết bằng JS thuần (hoặc Preact) bundle bằng Vite, enqueue chỉ ở trang có shortcode.

### Hai chế độ

| | **Chế độ học** (mặc định khi màn hình mở) | **Chế độ nền** (khoá màn hình / đang chạy xe) |
|---|---|---|
| Nguồn | clip lẻ theo playlist | 1 file `tracks/*.mp3` ghép sẵn |
| Hiển thị | câu đang đọc: hán tự, pinyin, nghĩa; highlight; bấm để nghe lại | chỉ tiêu đề bài |
| Tuỳ chỉnh | đổi mode/tốc độ/lặp ngay | theo bản đã render |
| Lý do | tương tác, chấm "đã thuộc" | iOS Safari hay dừng khi đổi `src` lúc màn hình khoá; một file dài thì phát nền ổn định |

Chi tiết:

- Dùng **một** phần tử `<audio>` cho cả playlist, đổi `src` từng bước. Khoảng lặng chạy bằng `setTimeout`.
- **Media Session API**: tiêu đề bài, nút next/prev trên màn hình khoá và tai nghe Bluetooth.
- Lưu vị trí đang nghe (`track`, `step`) vào `localStorage` để mở lại nghe tiếp. Đây chỉ là tiện ích phía máy; tiến độ thật nằm trên server.
- Gửi heartbeat `POST /me/listen` mỗi 30 giây với `{session_id, track_id, seconds, items_heard}`. Server cộng dồn và giới hạn tối đa 35 giây cho mỗi heartbeat để chống gian lận XP.
- Nút trên mỗi câu: 🔁 nghe lại, ✓ đã thuộc, ✗ chưa thuộc. Ngoài ra có toggle ẩn pinyin / ẩn nghĩa.
- Có thể tải trước (prefetch) 3 clip kế tiếp.

### Shortcode (dùng được trong Bricks bằng Shortcode element; về sau có thể làm Bricks element riêng)

```
[hskn_today]                         việc hôm nay: bài nghe + số mục cần ôn
[hskn_player track="topic-03"]       trình phát một bài
[hskn_topic id="03"]                 trang chủ đề: từ chuyên ngành + câu + nút nghe
[hskn_words level="2" per_page="50"] bảng từ có tìm kiếm, lọc chủ đề
[hskn_review]                        ôn tập ngắt quãng các mục đến hạn
[hskn_stats]                         thống kê cá nhân
```

---

## 7. Kế hoạch học & ôn tập ngắt quãng

### Kế hoạch 4 tuần (`plan_key = "re-4w"`)

Lấy từ `docs/ke-hoach-hoc.md`, khai báo trong code dạng mảng (không cần bảng):

```php
're-4w' => [
  1 => ['01','02','11'],  // Tiền bạc
  2 => ['03','05','07'],  // Nhà ở
  3 => ['04','06','12'],  // Văn phòng & đi lại
  4 => ['08','09','10'],  // Thi công & hậu cần
]
// Ngày 1–2: chủ đề A, 3–4: B, 5–6: C, ngày 7: ôn cả tuần (chế độ chỉ tiếng Trung)
// Song song: mỗi ngày 1 bài từ vựng HSK2 (15 bài × 50 từ), sau đó HSK3
```

`PlanService::today($user)` tính tuần/ngày từ `start_date` và trả về:

- bài nghe chính,
- bài từ vựng,
- số mục đến hạn ôn.

### Leitner 6 hộp

| Hộp | Ôn lại sau |
|---|---|
| 0 | mới |
| 1 | 1 ngày |
| 2 | 3 ngày |
| 3 | 7 ngày |
| 4 | 16 ngày |
| 5 | 35 ngày → `known` |

Quy tắc chuyển hộp:

- `heard` (nghe hết trong chế độ học) chỉ tăng `listen_count`, không đổi hộp. Nghe thụ động chưa chứng tỏ đã nhớ.
- `known` thì lên 1 hộp.
- `again` thì về hộp 1.
- Từ có `listen_count ≥ 10` mà vẫn ở hộp 0 thì được đưa vào `[hskn_review]` để người học tự chấm.

---

## 8. Kết nối plugin gamification HSK hiện có

Không gọi thẳng vào plugin kia. Chỉ phát action, phía gamification tự lắng nghe:

```php
do_action('hskn_listen_session_closed', $user_id, $track_id, $seconds, $items_heard);
do_action('hskn_item_known',          $user_id, $item_type, $item_id, $box);
do_action('hskn_daily_plan_completed', $user_id, $date);
do_action('hskn_streak_updated',      $user_id, $streak_days);
```

Bên gamification, ví dụ quy đổi 1 XP mỗi phút nghe (tối đa 60 XP/ngày) và cộng thưởng khi hoàn thành kế hoạch ngày. Cộng XP phải nguyên tử, đúng như đã sửa sau review.

---

## 9. Cấu trúc thư mục plugin

```
hsk-nghe/
├─ hsk-nghe.php                 header, autoload, bootstrap
├─ uninstall.php                xoá bảng nếu bật tuỳ chọn "xoá dữ liệu khi gỡ"
├─ src/
│  ├─ Plugin.php                đăng ký hook, REST, shortcode, CLI
│  ├─ Install/Schema.php        dbDelta + migrate theo hskn_db_version
│  ├─ Repository/               TopicRepo, WordRepo, SentenceRepo, AudioRepo, ProgressRepo, ListenLogRepo
│  ├─ Service/                  ImportService, PlaylistService, PlanService, SrsService, StatsService
│  ├─ Rest/                     TopicsController, WordsController, TracksController, MeController
│  ├─ Cli/HsknCommand.php       wp hskn import|status|verify-audio
│  ├─ Admin/                    trang Import, Tổng quan, Cài đặt
│  └─ Shortcode/                Today, Player, Topic, Words, Review, Stats
├─ assets/src/                  player.ts, store.ts, ui/*.ts  (Vite)
├─ assets/dist/                 build output (commit vào bản release)
└─ tests/                       PHPUnit cho Playlist/Plan/Srs/Import
```

---

## 10. Hiệu năng, bảo mật, vận hành

**Hiệu năng & lưu trữ**

- **Audio**: Nginx phục vụ trực tiếp `/wp-content/uploads/hskn/clips/` với `Cache-Control: public, max-age=31536000, immutable`. Cloudflare cache theo đó. Không đi qua PHP.
- **Dung lượng ước tính**: clip 64 kbps mono. Khoảng 1.703 từ × 4 clip + 480 câu × 3 clip ≈ 8.250 clip, cỡ 150–250 MB. Các track ghép thêm khoảng 300 MB.

**Bảo mật**

- Endpoint `me/*` kiểm tra `is_user_logged_in()` và chỉ thao tác trên `get_current_user_id()`. Không nhận `user_id` từ client.
- Validate `item_id` theo regex (`^H[23]-\d{3}$`, `^\d{2}-(S\d{2}|D\d+-\d+)$`).
- **Nội dung trả phí** (nếu bán khoá): chuyển clips ra ngoài webroot và phục vụ qua URL ký có hạn (HMAC + expires). Nginx kiểm bằng `secure_link`, không stream qua PHP.

**Vận hành**

- **Đa ngôn ngữ**: text domain `hsk-nghe`. UI mặc định tiếng Việt.

---

## 11. Việc cần làm ở repo nội dung trước khi viết plugin

1. **ID tường minh** trong file câu (`S|03-S12|…`). `build.py` cảnh báo nếu ID trùng hoặc bị đổi so với lần build trước (so với `data/build/sentences.json` cũ).
2. **`scripts/pack.py`** đóng gói `data/build/*.json` + `audio/` thành zip theo mục 2, kèm `pack.json`.
3. **`make_audio.py` ghi thêm `duration_ms`** cho mỗi clip vào manifest (dùng `ffprobe`), để trình phát hiện tổng thời lượng.
4. **Viết nốt câu ví dụ** cho 633 từ HSK3 còn thiếu (danh sách trong `data/build/missing_examples.tsv`).

## 12. Thứ tự triển khai đề xuất

| Giai đoạn | Nội dung | Xong khi |
|---|---|---|
| 1 | Schema + `wp hskn import` + `GET /topics`, `/topics/{id}` | Import gói, gọi API thấy đủ 12 chủ đề, 480 câu |
| 2 | `PlaylistService` + `[hskn_player]` chế độ học | Nghe được một chủ đề trên điện thoại, đổi mode/tốc độ |
| 3 | Chế độ nền (track ghép) + Media Session | Khoá màn hình iPhone vẫn nghe hết một bài |
| 4 | `hskn_progress`, `/me/listen`, `/me/progress`, `[hskn_words]` | Đánh dấu đã thuộc, thống kê phút nghe |
| 5 | `PlanService` + `[hskn_today]` + `[hskn_review]` | Mở trang "hôm nay" là biết nghe gì |
| 6 | Hook sang plugin gamification, trang Admin, PHPUnit | XP cộng đúng, không trùng |

---

## 13. Yêu cầu bổ sung (2026-10-26)

Các mục dưới đây **thay thế** phần tương ứng ở trên khi có mâu thuẫn.

### 13.1 Tạo nội dung bằng DeepSeek (chạy ở repo, không chạy trong WP)

`scripts/generate.py` gọi DeepSeek API (OpenAI-compatible, `https://api.deepseek.com/chat/completions`, model mặc định `deepseek-flash`, tắt thinking). Key đặt trong biến môi trường `DEEPSEEK_API_KEY` hoặc file `.env` ở gốc repo (đã gitignore).

```
python scripts/generate.py topic --name "Nhà hàng" --desc "Gọi món, thanh toán" --words 20 --per-word 2
python scripts/generate.py words --topic 03 --count 10 --per-word 2      # thêm từ vào chủ đề có sẵn
python scripts/generate.py words --topic 03 --list 押金,合同              # thêm đúng các từ này
python scripts/generate.py sentences --topic 13 --per-word 2             # sinh bù câu cho từ còn thiếu
python scripts/generate.py examples --level 3 --limit 100                # câu ví dụ HSK còn thiếu
```

Mọi kết quả của DeepSeek được kiểm tra trước khi ghi vào `data/source/`: câu phải chứa từ đích, độ dài tối đa (mặc định 18 chữ Hán), chỉ dùng từ HSK 1–3 hoặc từ chuyên ngành. Câu không đạt sẽ được gửi lại kèm lý do (tối đa 2 vòng). Pinyin và tách từ vẫn do `build.py` làm. Quy trình sau đó không đổi: `build.py` → `make_audio.py` → `pack.py` → `wp hskn import`.

### 13.2 ID tường minh và từ vựng theo chủ đề

| File nguồn | Định dạng |
|---|---|
| `sentences/NN-*.txt` | `S|03-S12|câu|nghĩa|ngữ pháp`, `D|03-D2-1|A|câu|nghĩa|ngữ pháp` |
| `topic_terms.txt` | `T03-001|押金|yā jīn|tiền cọc|deposit` (nhóm theo `## 03`) |
| `topic_words/NN-*.txt` (mới) | `W|H2-123|服务员` (từ thuộc chủ đề, theo thứ tự), `E|13-E007|H2-123|câu|nghĩa Việt|nghĩa Anh|ngữ pháp` (câu của từ) |

- Từ trong danh sách HSK 2–3 dùng ID `H…`. Các từ khác (HSK1, chuyên ngành) dùng ID `T{chủ đề}-{nnn}`.
- Câu theo từ có loại `E`, ID là `{chủ đề}-E{nnn}`. Vì ID tường minh nên có thể chèn câu ở bất cứ đâu, nhưng **không được tái sử dụng ID**.
- `build.py` cảnh báo khi ID bị trùng, hoặc khi một ID có trong lần build trước biến mất.
- Bảng `hskn_terms` bỏ đi: từ chuyên ngành nằm chung bảng `hskn_words` (`level` = 4 nếu ngoài HSK 1–3). Thêm bảng `hskn_topic_words (topic_id, word_id, sort)`. `hskn_sentences` thêm cột `word_id`, `en`, `type` có thêm `E`.

### 13.3 Chế độ nghe và cài đặt chung

Trong WP Admin, trang **HSK Nghe → Cài đặt** có các tuỳ chọn. Người học có thể ghi đè trong trình phát nếu admin cho phép.

| Cài đặt | Mặc định | |
|---|---|---|
| `word_repeat` | 2 | số lần đọc từ bằng tiếng Trung |
| `meaning_lang` | `vi` | đọc nghĩa của từ 1 lần: `vi`, `en` hoặc `none` |
| `sentence_repeat` | 2 | số lần đọc mỗi câu |
| `sentence_meaning` | bật | đọc nghĩa câu 1 lần sau lần đọc đầu |
| `slow_repeat` | bật | các lần lặp sau đọc chậm |
| `gap_ms`, `end_gap_ms` | 1000, 1800 | khoảng lặng giữa các bước và cuối mỗi mục |
| `chunk_size` | 30 | số từ mỗi bài từ vựng |
| `auto_next` | bật | hết bài thì tự chuyển sang bài kế tiếp (đọc liên tục) |

Thứ tự đọc một từ: **từ × `word_repeat`** → **nghĩa × 1** → với mỗi câu của từ: **câu** → (nghĩa câu) → **câu (chậm) × (`sentence_repeat` − 1)**.

Các loại bài nghe (sinh động từ dữ liệu, không cần bảng `hskn_tracks`):

- `topic-NN`: mẫu câu chủ đề (S, D);
- `words-NN-kk`: từ vựng chủ đề kèm câu E;
- `vocab-hsk2-kk`: từ HSK kèm câu ví dụ.

### 13.4 Phát nền khi tắt màn hình: PHP ghép MP3, bỏ chế độ "clip lẻ"

Thay cho hai chế độ ở mục 6, **trình phát luôn phát một file MP3 duy nhất cho mỗi bài**:

- `AudioRenderer` ghép các frame MP3 của clip lẻ (cùng định dạng 24 kHz mono 48 kbps của edge-tts) và chèn khoảng lặng bằng frame im lặng. Bước này không cần ffmpeg trên server.
- File ghép được cache ở `uploads/hskn/cache/{track}-{hash}.mp3`, với hash = bài + cài đặt + nội dung.
- Cùng lúc PHP sinh danh sách **cue** (mốc ms của từng bước). Trình phát dựa vào `timeupdate` để hiện câu đang đọc, và bấm "nghe lại" thì tua về cue.
- Màn hình khoá vẫn phát được vì chỉ có một file. Tốc độ chỉnh bằng `playbackRate`. Hết bài, sự kiện `ended` kích hoạt bài kế tiếp (đã tải trước playlist JSON).
- Media Session: tiêu đề, play/pause, bài trước/sau, tua ±10 giây.
- `make_audio.py` không còn bắt buộc phải ghép track (`--tracks` là tuỳ chọn).

### 13.5 Thêm nội dung trực tiếp trong WP Admin (2026-10-26)

Trang **HSK Nghe → Thêm nội dung**: chọn chủ đề mới hoặc chủ đề có sẵn → DeepSeek đề xuất từ → duyệt → DeepSeek sinh câu (theo lô 8 từ) → duyệt, sửa nghĩa → lưu → tạo giọng đọc (theo lô 40 clip).

- **Không đụng repo**: nội dung có `source = 'wp'` ở các bảng topics, words, topic_words, sentences, word_sentence, audio. Import gói chỉ ghi đè hoặc ngừng dùng các dòng `source = 'pack'`.
- **Dải ID riêng** để không trùng với `generate.py`: chủ đề 50–99, từ `T{chủ đề}-501…`, câu `{chủ đề}-E5001…`.
- **Pinyin và tách từ** do DeepSeek trả về; PHP (`Author\Checker`) kiểm tra như `generate.py`, dựa trên danh sách HSK 1–3 nhúng trong `data/hsk-levels.json` cộng với từ chuyên ngành trong DB. Chữ Hán được nhận theo dải U+3400–4DBF, U+4E00–9FFF, không dùng `\p{Han}` (vì PCRE tính cả dấu 。 là chữ Hán).
- **Giọng đọc** (`Author\Tts`): Azure Speech (chính thức, chạy được trên hosting, cần key + region) hoặc Python + edge-tts trên chính máy chạy WP (chỉ cho site dev). Không chép giao thức Edge sang PHP, vì phải lách cơ chế token của Microsoft. Tên clip dùng cùng công thức hash với `make_audio.py`, nên clip trùng nội dung được dùng lại.
- **Key** lưu ở option `hskn_api`, không gửi xuống trình duyệt. Ô key để trống khi lưu thì giữ key cũ.
- **Máy dev có Avast quét HTTPS**: mu-plugin `wp-content/mu-plugins/hskn-local-ca.php` (kèm file `.pem`) cho WP tin chứng chỉ gốc Avast khi gọi deepseek.com / microsoft.com. Không đưa mu-plugin này lên hosting.
- Nội dung tạo trong WP chưa xuất ngược về repo được (việc còn lại).

### 13.6 Quản lý nội dung trong WP Admin (2026-10-26)

Người dùng chỉ làm việc online, nên mọi chỉnh sửa đều làm được trong trang **HSK Nghe → Quản lý nội dung**:

- Tab **Chủ đề**: danh sách chủ đề (ẩn/hiện) → mở chủ đề → sửa tên, mô tả; từ vựng (pinyin, nghĩa; bỏ khỏi chủ đề; DeepSeek viết thêm câu → chọn câu → thêm); câu theo từ, mẫu câu, hội thoại (sửa câu chữ Hán, pinyin, nghĩa, ngữ pháp; ẩn/hiện).
- Tab **Từ HSK 2 / HSK 3**: tìm kiếm, sửa nghĩa, sửa câu ví dụ, hoặc nhờ DeepSeek viết câu ví dụ khác.
- Sửa câu chữ Hán → `Generator::analyze()` nhờ DeepSeek tách từ và gắn pinyin → `Checker` kiểm tra. Câu không đạt (thiếu từ đích, ngoài HSK…) chỉ được lưu khi bấm "Vẫn lưu".
- Dòng đã sửa chuyển sang `source = 'wp'`, nên import gói về sau không ghi đè.
- **Giọng đọc tự đồng bộ**: `AudioService::plan()` tính clip phải có cho mọi từ và câu đang dùng (cùng công thức hash với `make_audio.py`), so với bảng audio, rồi báo "N clip cần tạo lại". Nút **Tạo giọng đọc** tạo theo lô. Đã kiểm tra: với 14.000 clip từ gói thì kết quả là 0 việc.
