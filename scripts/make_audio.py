#!/usr/bin/env python3
"""
Tạo clip audio lẻ từ data/build/*.json bằng giọng Microsoft Edge (edge-tts, miễn phí, cần mạng).

Cài 1 lần:   pip install -r requirements.txt   +   ffmpeg (winget install Gyan.FFmpeg | brew install ffmpeg)
Chạy trước:  python scripts/build.py

Ví dụ:
  python scripts/make_audio.py                          # tất cả
  python scripts/make_audio.py --only topics --topics 03 11
  python scripts/make_audio.py --only words --topics 03 # từ vựng chủ đề + câu theo từ (E)
  python scripts/make_audio.py --only vocab --level 2 --limit 30

Đầu ra (audio/):
  clips/<sha1-16>.mp3    clip lẻ, đặt tên theo (giọng, tốc độ, nội dung) → chạy lại chỉ tạo clip mới
  clips/silence.mp3      2 giây im lặng cùng định dạng (plugin cắt frame từ file này để chèn khoảng lặng)
  manifest.json          id câu/từ → clip theo từng loại (plugin WordPress đọc file này khi import)

Bài nghe KHÔNG ghép ở đây nữa: plugin ghép frame MP3 theo cài đặt của người học (xem đặc tả mục 13.4).
Mọi clip phải cùng định dạng edge-tts (MPEG-2 Layer III, 24 kHz, mono, 48 kbps) để ghép được.
"""
import argparse, asyncio, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "data/build"

try:
    import edge_tts
except ImportError:
    sys.exit("Thiếu thư viện: pip install edge-tts")
try:                                  # dùng kho chứng chỉ của hệ điều hành (antivirus / proxy chèn chứng chỉ)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

VOICE = {"zh_f": "zh-CN-XiaoxiaoNeural", "zh_m": "zh-CN-YunxiNeural",
         "vi": "vi-VN-HoaiMyNeural", "en": "en-US-JennyNeural"}
WORD_RATE = "-10%"


class Studio:
    def __init__(self, out, slow, concurrency):
        self.out, self.slow = out, slow
        self.clips = out / "clips"; self.clips.mkdir(parents=True, exist_ok=True)
        self.sem = asyncio.Semaphore(concurrency)
        self.made = self.cached = 0

    def key(self, text, voice, rate):
        return hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]

    async def clip(self, text, voice, rate="+0%"):
        path = self.clips / f"{self.key(text, voice, rate)}.mp3"
        if path.exists() and path.stat().st_size > 0:
            self.cached += 1
            return self.rel(path)
        async with self.sem:
            err = None
            for attempt in range(4):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
                    if path.stat().st_size > 0:
                        self.made += 1
                        return self.rel(path)
                except Exception as e:      # mạng chập chờn → thử lại
                    err = e
                await asyncio.sleep(2 * (attempt + 1))
        raise RuntimeError(f"TTS lỗi: {text} ({err})")

    def rel(self, p):
        return p.relative_to(self.out).as_posix()

    def silence(self):
        p = self.clips / "silence.mp3"
        if not p.exists():
            ff = shutil.which("ffmpeg")
            if not ff:
                sys.exit("Thiếu ffmpeg (chỉ cần một lần để tạo clips/silence.mp3).")
            subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "2",
                            "-c:a", "libmp3lame", "-b:a", "48k", "-write_xing", "0", "-id3v2_version", "0", str(p)],
                           check=True)
        return self.rel(p)


def short_en(en):
    """'modal particle ending sentence, showing …; xyz' → 'modal particle ending sentence' (đọc cho gọn)."""
    first = re.sub(r"\(.*?\)", "", (en or "").split(";")[0]).strip()
    words = first.split(",")[0].split()
    return " ".join(words[:6])


async def sentence_entry(st, s):
    voice = VOICE["zh_m"] if s.get("speaker") == "B" else VOICE["zh_f"]
    jobs = {"zh": st.clip(s["zh"], voice), "zh_slow": st.clip(s["zh"], voice, st.slow),
            "vi": st.clip(s["vi"], VOICE["vi"])}
    if s.get("en"):
        jobs["en"] = st.clip(s["en"], VOICE["en"])
    return dict(zip(jobs, await asyncio.gather(*jobs.values())))


async def word_entry(st, w):
    jobs = {"word": st.clip(w["hanzi"], VOICE["zh_f"], WORD_RATE), "vi": st.clip(w["vi"], VOICE["vi"])}
    en = short_en(w.get("en"))
    if en:
        jobs["en"] = st.clip(en, VOICE["en"])
    ex = w.get("example")
    if ex:
        jobs |= {"example": st.clip(ex["zh"], VOICE["zh_m"]), "example_slow": st.clip(ex["zh"], VOICE["zh_m"], st.slow),
                 "example_vi": st.clip(ex["vi"], VOICE["vi"])}
        if ex.get("en"):
            jobs["example_en"] = st.clip(ex["en"], VOICE["en"])
    return dict(zip(jobs, await asyncio.gather(*jobs.values())))


async def run_all(label, items, fn, st, target):
    """Gộp vào manifest (không ghi đè các loại clip đã có của cùng mục, ví dụ clip câu ví dụ của từ HSK)."""
    done = 0
    for i in range(0, len(items), 40):
        chunk = items[i:i + 40]
        for it, entry in zip(chunk, await asyncio.gather(*(fn(st, it) for it in chunk))):
            target[it["id"]] = target.get(it["id"], {}) | entry
        done += len(chunk)
        print(f"\r  {label}: {done}/{len(items)}  (mới {st.made}, có sẵn {st.cached})", end="", flush=True)
    if items:
        print()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "audio"))
    ap.add_argument("--only", choices=["topics", "words", "vocab"], help="chỉ tạo một loại")
    ap.add_argument("--topics", nargs="*", help="mã chủ đề, ví dụ 01 03 11 (áp dụng cho topics và words)")
    ap.add_argument("--level", type=int, choices=[2, 3], help="chỉ từ vựng HSK cấp này")
    ap.add_argument("--limit", type=int, help="chỉ N từ đầu mỗi cấp (để thử)")
    ap.add_argument("--slow", default="-25%")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    load = lambda n: json.loads((BUILD / n).read_text(encoding="utf-8"))
    topics, sentences, vocab, terms = load("topics.json"), load("sentences.json"), load("vocab.json"), load("topic_terms.json")
    out = Path(args.out); st = Studio(out, args.slow, args.concurrency)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    manifest.setdefault("sentences", {}); manifest.setdefault("vocab", {})
    manifest.pop("tracks", None); manifest.pop("settings", None)
    manifest |= {"format": 2, "voices": VOICE, "rates": {"word": WORD_RATE, "slow": args.slow}, "silence": st.silence()}
    pick = lambda tid: not args.topics or tid in args.topics

    if args.only in (None, "topics"):
        items = [s for s in sentences if s["type"] in ("S", "D") and pick(s["topic"])]
        await run_all("Mẫu câu chủ đề", items, sentence_entry, st, manifest["sentences"])

    if args.only in (None, "words"):
        words = {w["id"]: w for w in vocab} | {t["id"]: t for t in terms if not t.get("same_as")}
        ids = list(dict.fromkeys(i for t in topics if pick(t["id"]) for i in t.get("words", [])))
        items = [words[i] | {"example": None} for i in ids if i in words]
        await run_all("Từ vựng chủ đề", items, word_entry, st, manifest["vocab"])
        esents = [s for s in sentences if s["type"] == "E" and pick(s["topic"])]
        await run_all("Câu theo từ", esents, sentence_entry, st, manifest["sentences"])

    if args.only in (None, "vocab"):
        for lvl in (2, 3):
            if args.level and lvl != args.level:
                continue
            items = [w for w in vocab if w["level"] == lvl][:args.limit]
            await run_all(f"Từ vựng HSK{lvl}", items, word_entry, st, manifest["vocab"])

    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ Xong: {st.made} clip mới, {st.cached} có sẵn. Manifest: {mpath}")


if __name__ == "__main__":
    asyncio.run(main())
