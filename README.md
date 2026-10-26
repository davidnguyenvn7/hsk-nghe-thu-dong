# HSK Nghe Thụ Động

Bộ dữ liệu từ vựng **HSK 3.0 cấp 2–3** và **mẫu câu theo 12 chủ đề công việc** (tiền, ngân hàng, thuê nhà, văn phòng, toà nhà, thi công, sửa chữa, vận chuyển, đàm phán giá, giao thông). Kèm script tạo audio để nghe thụ động, và đặc tả plugin WordPress.

## Có gì trong này

| | Số lượng | Ghi chú |
|---|---|---|
| Từ vựng HSK 3.0 cấp 2 | 750 | danh sách chính thức, nghĩa Việt, pinyin, từ loại, nghĩa Anh |
| Từ vựng HSK 3.0 cấp 3 | 953 | như trên |
| Câu ví dụ cho từng từ | 1.070 / 1.703 | đủ HSK2; HSK3 còn thiếu 633 từ, xem `data/build/missing_examples.tsv` |
| Mẫu câu theo chủ đề | 480 | 12 chủ đề × (30 câu đơn + 5 hội thoại 2 lượt), có nghĩa Việt và điểm ngữ pháp |
| Từ chuyên ngành | ~215 | từ ngoài HSK3 nhưng cần cho công việc (押金, 合同, 转账, 承重墙…) |

Mọi câu đều được tự động:

- gắn **pinyin** theo quy ước giáo trình: biến điệu 一/不, 个 đọc nhẹ, nhi hoá, số đếm gộp;
- **tách từ** và gắn **cấp HSK cho từng từ**;
- liên kết ngược: mỗi từ HSK biết nó xuất hiện trong câu nào, thuộc chủ đề nào.

## Chạy nhanh

```bash
pip install -r requirements.txt     # + ffmpeg (chỉ cần một lần để tạo clips/silence.mp3)
python scripts/generate.py …        # (tuỳ chọn) sinh chủ đề / từ / câu mới bằng DeepSeek, xem docs/wordpress-plugin.md mục 13
python scripts/build.py             # source → data/build/*.json, *.csv
python scripts/make_audio.py        # → audio/clips/*.mp3 + audio/manifest.json
python scripts/pack.py              # → dist/hskn-pack-YYYY.MM.DD.zip cho plugin WordPress hsk-nghe
```

Mở `data/build/csv/*.csv` bằng Excel hoặc Google Sheets nếu chỉ cần xem danh sách.

## Cấu trúc

```
data/
  source/                 ← CHỈ SỬA Ở ĐÂY
    topics.json             12 chủ đề
    vocab_vi/hsk2.txt       nghĩa Việt:  chữ Hán|nghĩa|pinyin(tuỳ chọn, để ép âm đọc)
    vocab_vi/hsk3.txt
    examples/hsk*.txt       câu ví dụ:  chữ Hán|câu|nghĩa
    sentences/NN-*.txt      mẫu câu theo chủ đề:  S|03-S12|câu|nghĩa|ngữ pháp   D|03-D2-1|A|câu|nghĩa|ngữ pháp
    topic_words/NN-*.txt    từ của chủ đề + câu theo từ:  W|H2-123|chữ Hán   E|13-E007|H2-123|câu|nghĩa|en|ngữ pháp
    topic_terms.txt         từ chuyên ngành:  T03-001|chữ Hán|pin yin|nghĩa|en   (nhóm theo "## 03")
    pinyin_phrases.txt      sửa pinyin cụm từ:  还给|huán gěi
    seg_fixes.txt           sửa tách từ:  可以|来
  vendor/hsk30/             danh sách HSK 3.0 gốc (MIT, drkameleon/complete-hsk-vocabulary)
  build/                  ← sinh tự động, đừng sửa tay
    vocab.json  sentences.json  topics.json  topic_terms.json  stats.json  missing_examples.tsv
    csv/
scripts/
  build.py                  dựng dữ liệu, gắn pinyin, tách từ, thống kê
  generate.py               sinh nội dung bằng DeepSeek API (kiểm tra HSK, độ dài, từ đích)
  make_audio.py             tạo clip audio bằng edge-tts (giọng Edge, miễn phí, cần mạng)
  pack.py                   đóng gói content pack cho plugin
  migrate_ids.py            (đã chạy) chuyển file nguồn sang ID tường minh
docs/
  wordpress-plugin.md       đặc tả plugin WordPress
  ke-hoach-hoc.md           kế hoạch học 4 tuần
  ngu-phap.md               chỉ mục ngữ pháp (sinh tự động)
schema/                     JSON Schema cho dữ liệu build
```

## Quy trình sửa nội dung

1. Sửa file trong `data/source/`.
2. Chạy `python scripts/build.py` và đọc cảnh báo: từ chưa có trong HSK lẫn topic_terms, câu ví dụ không chứa từ đích, nghĩa bị thiếu.
3. Pinyin sai thì thêm dòng vào `pinyin_phrases.txt`. Tách từ sai thì thêm dòng vào `seg_fixes.txt`. Sau đó build lại.
4. Chạy `python scripts/make_audio.py`. Chỉ những clip có nội dung đổi mới bị tạo lại.

## Giới hạn đã biết

- Pinyin câu do máy gán (pypinyin + từ điển soạn tay). Phần lớn đúng, nhưng chữ đa âm trong ngữ cảnh lạ vẫn có thể sai. Hãy rà khi nghe và sửa bằng `pinyin_phrases.txt`.
- Nghĩa Việt viết ngắn gọn cho việc nghe; không phải từ điển đầy đủ.
- ID câu/từ ghi tường minh trong file nguồn; không đổi, không tái sử dụng (xem `docs/wordpress-plugin.md` mục 13.2).
- `edge-tts` dùng dịch vụ đọc của Microsoft Edge, cần mạng và có thể thay đổi bất cứ lúc nào. Nếu ngừng hoạt động, thay hàm `Studio.clip` bằng Azure TTS hoặc Google TTS.
