#!/usr/bin/env python3
"""
Đóng gói content pack cho plugin WordPress (đặc tả mục 2).

    python scripts/pack.py                    # → dist/hskn-pack-2026.10.26.zip
    python scripts/pack.py --no-audio         # chỉ JSON (import nhanh khi chỉ sửa chữ)
    python scripts/pack.py --dir              # → dist/hskn-pack-2026.10.26/ (thư mục, để upload SFTP)

Chỉ đóng những clip mà manifest có tham chiếu. Câu/từ chưa có audio vẫn được import; trình phát sẽ bỏ qua.
"""
import argparse, json, shutil, zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, AUDIO, DIST = ROOT / "data/build", ROOT / "audio", ROOT / "dist"
FILES = ["topics.json", "vocab.json", "sentences.json", "topic_terms.json"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--dir", action="store_true", help="xuất thư mục thay vì zip")
    ap.add_argument("--version", help="mặc định YYYY.MM.DD(.n)")
    args = ap.parse_args()

    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    data = {n: load(BUILD / n) for n in FILES}
    mpath = AUDIO / "manifest.json"
    manifest = load(mpath) if mpath.exists() and not args.no_audio else {"format": 2, "sentences": {}, "vocab": {}}

    clips = set()
    if not args.no_audio:
        for group in ("sentences", "vocab"):
            for entry in manifest[group].values():
                clips.update(entry.values())
        if manifest.get("silence"):
            clips.add(manifest["silence"])
        missing = sorted(c for c in clips if not (AUDIO / c).exists())
        if missing:
            raise SystemExit(f"Manifest trỏ tới {len(missing)} clip không tồn tại, ví dụ {missing[:3]}. Chạy lại make_audio.py.")

    DIST.mkdir(exist_ok=True)
    version = args.version or datetime.now().strftime("%Y.%m.%d")
    n = 1
    while not args.version and ((DIST / f"hskn-pack-{version}.zip").exists() or (DIST / f"hskn-pack-{version}").exists()):
        n += 1; version = f"{datetime.now():%Y.%m.%d}.{n}"
    sents = data["sentences.json"]
    pack = {"version": version, "hsk_standard": "3.0", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "counts": {"topics": len(data["topics.json"]), "vocab": len(data["vocab.json"]),
                       "terms": len(data["topic_terms.json"]), "sentences": len(sents),
                       "word_sentences": sum(s["type"] == "E" for s in sents),
                       "audio_sentences": len(manifest["sentences"]), "audio_words": len(manifest["vocab"]),
                       "clips": len(clips)}}
    # không có manifest → plugin hiểu là gói chỉ có chữ và giữ nguyên audio đang có
    payload = {"pack.json": pack} | ({} if args.no_audio else {"manifest.json": manifest}) | data

    name = f"hskn-pack-{version}"
    if args.dir:
        out = DIST / name
        (out / "clips").mkdir(parents=True)
        for k, v in payload.items():
            (out / k).write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        for c in sorted(clips):
            shutil.copy2(AUDIO / c, out / c)
    else:
        out = DIST / f"{name}.zip"
        with zipfile.ZipFile(out, "w") as z:
            for k, v in payload.items():
                z.writestr(k, json.dumps(v, ensure_ascii=False), compress_type=zipfile.ZIP_DEFLATED)
            for c in sorted(clips):                      # mp3 đã nén sẵn → lưu nguyên (nhanh hơn)
                z.write(AUDIO / c, c, compress_type=zipfile.ZIP_STORED)
    print(f"✓ {out}")
    print("  " + " · ".join(f"{k}: {v}" for k, v in pack["counts"].items()))


if __name__ == "__main__":
    main()
