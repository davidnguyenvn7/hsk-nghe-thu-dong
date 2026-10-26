# Kế hoạch học 4 tuần

Mục tiêu: nắm từ vựng HSK 2–3 (chuẩn HSK 3.0) và mẫu câu cho các tình huống công việc: tiền, ngân hàng, thuê nhà, văn phòng, toà nhà, thi công, giao thông. Cách học chính là **nghe thụ động** hằng ngày, kèm vài phút học chủ động.

## Lịch chủ đề

Mỗi tuần học 3 chủ đề. Mỗi chủ đề học trong 2 ngày, ngày thứ 7 ôn cả tuần.

| Tuần | Nhóm | Chủ đề |
|---|---|---|
| 1 | Tiền bạc | 01 Giao dịch tiền · 02 Chuyển khoản ngân hàng · 11 Đàm phán giá |
| 2 | Nhà ở | 03 Cho thuê bất động sản · 05 Căn hộ · 07 Mô tả toà nhà |
| 3 | Văn phòng & đi lại | 04 Văn phòng · 06 Vị trí & đường đi · 12 Giao thông đô thị |
| 4 | Thi công & hậu cần | 08 Thi công xây dựng · 09 Sửa đồ văn phòng · 10 Vận chuyển đồ đạc |

Song song với lịch chủ đề, mỗi ngày nghe **1 bài từ vựng** (50 từ/bài, có câu ví dụ). HSK2 gồm 15 bài (750 từ), xong HSK2 thì chuyển sang HSK3. Theo nhịp này, sau 4 tuần sẽ nghe hết HSK2 và khoảng 13 bài đầu HSK3.

## Một ngày học

| Lúc | Thời lượng | Việc |
|---|---|---|
| Sáng | 15 phút | **Chủ động**: đọc to từ chuyên ngành của chủ đề, đọc 30 câu đơn kèm pinyin, để ý cột ngữ pháp |
| Trong ngày | 30–60 phút | **Thụ động**: nghe bài chủ đề (Trung → Việt → Trung chậm) lúc chạy xe, làm việc, nấu ăn |
| Trong ngày | 20 phút | **Thụ động**: nghe 1 bài từ vựng |
| Tối | 10 phút | **Shadowing**: ẩn nghĩa, nghe một câu rồi nói lặp lại ngay; đóng vai 5 hội thoại |
| Ngày 7 | 45 phút | Nghe lại 3 chủ đề của tuần ở chế độ **chỉ tiếng Trung** (`--mode zh`) |

## Sau tuần 4

- Nghe hết các bài từ vựng HSK3 còn lại.
- Nghe xoay vòng 12 chủ đề ở chế độ chỉ tiếng Trung, lặp 3 lần (`--mode zh --repeat 3`).
- Tự kiểm tra: nghe một câu mà hiểu ngay thì đánh dấu đã thuộc (trên plugin là nút ✓).

## Lệnh tạo audio tương ứng

```bash
python scripts/make_audio.py --only topics                  # 12 bài chủ đề
python scripts/make_audio.py --only vocab --level 2         # 15 bài từ vựng HSK2
python scripts/make_audio.py --only topics --mode zh --repeat 3 --out audio-zh   # bản ôn chỉ tiếng Trung
```
