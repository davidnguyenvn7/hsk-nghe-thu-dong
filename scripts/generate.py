#!/usr/bin/env python3
"""
Sinh nội dung mới bằng DeepSeek API rồi ghi vào data/source/ (sau đó chạy build.py như thường).

Key:  biến môi trường DEEPSEEK_API_KEY, hoặc file .env ở gốc repo:  DEEPSEEK_API_KEY=sk-...
      DEEPSEEK_MODEL (mặc định deepseek-flash), DEEPSEEK_BASE_URL (mặc định https://api.deepseek.com)

    python scripts/generate.py topic --name "Nhà hàng" --desc "Gọi món, thanh toán" --words 20 --per-word 2
    python scripts/generate.py words --topic 03 --count 10 --per-word 2
    python scripts/generate.py words --topic 03 --list 押金,合同
    python scripts/generate.py sentences --topic 13 --per-word 2
    python scripts/generate.py examples --level 3 --limit 100

Thêm --dry-run để xem kết quả mà không ghi file.

Mọi câu đều được kiểm tra: chứa từ đích, không quá --max-len chữ Hán, chỉ dùng từ HSK 1–3 / từ chuyên ngành.
Câu không đạt được gửi lại DeepSeek kèm lý do (tối đa --rounds vòng).
"""
import argparse, json, os, re, sys, time, unicodedata, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as B  # noqa: E402

try:                                  # dùng kho chứng chỉ của hệ điều hành (antivirus / proxy chèn chứng chỉ)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT, SRC = B.ROOT, B.SRC
HAN = B.HAN


# ---------------------------------------------------------------- DeepSeek
def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class DeepSeek:
    def __init__(self):
        load_env()
        self.key = os.environ.get("DEEPSEEK_API_KEY")
        if not self.key:
            sys.exit("Thiếu DEEPSEEK_API_KEY (đặt biến môi trường hoặc thêm vào file .env ở gốc repo).")
        self.model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
        self.url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
        self.tokens = 0

    def json(self, system, user, temperature=0.8):
        body = {"model": self.model, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}
        for attempt in range(5):
            req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(3 * (attempt + 1)); continue
                sys.exit(f"DeepSeek lỗi HTTP {e.code}: {msg}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 4:
                    time.sleep(3 * (attempt + 1)); continue
                sys.exit(f"Không gọi được DeepSeek: {e}")
            self.tokens += data.get("usage", {}).get("total_tokens", 0)
            text = data["choices"][0]["message"]["content"] or ""
            m = re.search(r"\{.*\}", text, re.S)
            try:
                return json.loads(m.group(0) if m else text)
            except json.JSONDecodeError:
                if attempt < 4:
                    continue
                sys.exit(f"DeepSeek trả về JSON hỏng:\n{text[:500]}")


SYSTEM = ("You are an experienced Mandarin teacher writing listening material for Vietnamese adults at HSK 2–3 level "
          "who work in real estate, offices and city life. You write natural, everyday spoken Mandarin "
          "(simplified characters, mainland usage). Always answer with one JSON object only.")


# ---------------------------------------------------------------- source files
def read_topics():
    return json.loads((SRC / "topics.json").read_text(encoding="utf-8"))


def write_topics(topics):
    body = ",\n".join("  " + json.dumps(t, ensure_ascii=False) for t in topics)
    (SRC / "topics.json").write_text("[\n" + body + "\n]\n", encoding="utf-8")


def slugify(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "chu-de"


def topic_words_path(topic):
    d = SRC / "topic_words"; d.mkdir(exist_ok=True)
    return next(d.glob(f"{topic['id']}-*.txt"), d / f"{topic['id']}-{topic['slug']}.txt")


def read_topic_words(topic):
    """→ (lines, words [(id, hanzi)], sentences_by_word {id: [zh]}, max E number)"""
    p = topic_words_path(topic)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else [
        f"# Từ vựng chủ đề {topic['id']} — {topic['name_vi']}",
        "# W|ID từ|chữ Hán                         từ thuộc chủ đề (thứ tự = thứ tự nghe)",
        "# E|ID câu|ID từ|câu|nghĩa Việt|nghĩa Anh|ngữ pháp   câu của từ (sinh bằng scripts/generate.py)", ""]
    words, sents, max_e = [], {}, 0
    for line in lines:
        f = line.split("|")
        if f[0] == "W" and len(f) >= 3:
            words.append((f[1], f[2])); sents.setdefault(f[1], [])
        elif f[0] == "E" and len(f) >= 4:
            sents.setdefault(f[2], []).append(f[3])
            max_e = max(max_e, int(f[1].split("-E")[1]))
    return lines, words, sents, max_e


def write_lines(path, lines):
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def insert_terms(topic, new_terms):
    """Thêm dòng ID|chữ Hán|pinyin|nghĩa|en vào cuối nhóm '## NN' (tạo nhóm nếu chưa có)."""
    p = SRC / "topic_terms.txt"
    lines = p.read_text(encoding="utf-8").splitlines()
    rows = [f"{t['id']}|{t['hanzi']}|{t['pinyin']}|{t['vi']}|{t['en']}" for t in new_terms]
    start = next((i for i, l in enumerate(lines) if l.startswith(f"## {topic['id']}")), None)
    if start is None:
        lines += ["", f"## {topic['id']} {topic['name_vi']}"] + rows
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = rows
    write_lines(p, lines)


# ---------------------------------------------------------------- validation
class Checker:
    def __init__(self, max_len, allow_unknown=0):
        self.reload()
        self.max_len, self.allow_unknown = max_len, allow_unknown

    def reload(self):
        self.ctx = B.load_context()
        self.seg = self.ctx["seg"]
        self.vocab_by_hanzi = {w["hanzi"]: w for w in self.ctx["vocab"]}
        self.term_ids = {t["id"]: t for tl in self.ctx["terms"].values() for t in tl}

    def problems(self, zh, word):
        zh = zh.strip()
        out = []
        if word not in zh:
            out.append(f"không chứa từ đích {word}")
        n = len(HAN.findall(zh))
        if n > self.max_len:
            out.append(f"dài {n} chữ (tối đa {self.max_len})")
        if not re.search(r"[。？！]$", zh):
            out.append("thiếu dấu câu cuối (。？！)")
        if re.search(r"[A-Za-z0-9]", zh):
            out.append("có chữ Latin/số Ả Rập (hãy viết số bằng chữ Hán)")
        _, toks = self.seg.pinyin(zh)
        unknown = [t for t, py, lv in toks if py and lv == 0 and t != word]
        if len(unknown) > self.allow_unknown:
            out.append("dùng từ ngoài HSK 1–3: " + "、".join(unknown))
        return out

    def term_pinyin(self, hanzi, py):
        """Pinyin từ DeepSeek: chấp nhận nếu số âm tiết khớp số chữ, không thì để pypinyin gán."""
        syl = B.split_syllables(py.replace(" ", "")) if py else None
        if syl and len(syl) == len(hanzi):
            return " ".join(s.lower() for s in syl)
        return " ".join(self.seg.syllables(hanzi))


# ---------------------------------------------------------------- generation steps
def ask_words(ds, topic, n, exclude, hint=None):
    ask = (f"Topic (Vietnamese): {topic['name_vi']}. Description: {topic.get('desc', '')}.\n" +
           (f"Give pinyin/meaning for exactly these words: {'、'.join(hint)}.\n" if hint else
            f"List the {n} Chinese words or short phrases most useful for this topic in daily work conversations.\n"
            "- Prefer words from HSK 1–3. Specialized terms (outside HSK) are fine when the topic needs them.\n"
            "- Each item is a single lexical word or fixed phrase, 1–4 characters, no sentences.\n") +
           (f"- Do NOT include any of: {'、'.join(exclude)}\n" if exclude and not hint else "") +
           "For each item give: hanzi (simplified), pinyin (tone marks, syllables separated by spaces), "
           "vi (short natural Vietnamese meaning in the context of this topic, max 6 words), "
           "en (short English gloss, max 4 words).\n" +
           ("" if topic.get("name_zh") else
            "Also give name_zh (2–6 character Chinese title of the topic) and desc (one Vietnamese line listing sub-situations).\n") +
           'JSON: {"name_zh": "...", "desc": "...", "words": [{"hanzi": "...", "pinyin": "...", "vi": "...", "en": "..."}]}')
    return ds.json(SYSTEM, ask, temperature=0.7)


def add_words(ds, chk, topic, items, args):
    """items: [{hanzi, pinyin, vi, en}] → ghi topic_terms (từ ngoài HSK2–3) + dòng W. Trả về số từ thêm."""
    lines, words, _, _ = read_topic_words(topic)
    have = {h for _, h in words}
    terms = chk.ctx["terms"].get(topic["id"], [])
    next_t = max([int(t["id"][-3:]) for t in terms] + [0])
    term_by_hanzi = {t["hanzi"]: t for tl in chk.ctx["terms"].values() for t in tl}
    new_terms, new_w = [], []
    for it in items:
        h = (it.get("hanzi") or "").strip()
        if not h or not HAN.search(h) or h in have or len(h) > 6:
            continue
        have.add(h)
        if h in chk.vocab_by_hanzi:
            wid = chk.vocab_by_hanzi[h]["id"]
        elif h in term_by_hanzi:
            wid = term_by_hanzi[h]["id"]
        else:
            next_t += 1
            wid = f"T{topic['id']}-{next_t:03d}"
            new_terms.append({"id": wid, "hanzi": h, "pinyin": chk.term_pinyin(h, it.get("pinyin", "")),
                              "vi": (it.get("vi") or "").replace("|", "/").strip(),
                              "en": (it.get("en") or "").replace("|", "/").strip()})
        new_w.append(f"W|{wid}|{h}")
        print(f"  + {wid:8} {h}  {it.get('vi', '')}")
    if args.dry_run or not new_w:
        return len(new_w)
    if new_terms:
        insert_terms(topic, new_terms)
    last_w = max([i for i, l in enumerate(lines) if l.startswith(("W|", "E|"))] + [len(lines) - 1])
    lines[last_w + 1:last_w + 1] = new_w
    write_lines(topic_words_path(topic), lines)
    return len(new_w)


def gen_sentences(ds, chk, topic, per_word, args, only=None):
    """Sinh câu E cho các từ của chủ đề còn thiếu (< per_word câu)."""
    lines, words, sents, max_e = read_topic_words(topic)
    todo = [(wid, h) for wid, h in words if len(sents.get(wid, [])) < per_word and (not only or h in only)]
    if not todo:
        print("  Không có từ nào thiếu câu."); return 0
    terms = sorted({t["hanzi"] for t in chk.ctx["terms"].get(topic["id"], [])} | {h for _, h in words})
    meaning = {}
    for wid, h in words:
        w = chk.vocab_by_hanzi.get(h) or chk.term_ids.get(wid) or {}
        meaning[wid] = w.get("vi", "")
    accepted = {}
    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        need = {wid: per_word - len(sents.get(wid, [])) for wid, _ in batch}
        feedback = ""
        for rnd in range(args.rounds + 1):
            pending = [(wid, h) for wid, h in batch if need[wid] > 0]
            if not pending:
                break
            ask = (f"Topic: {topic['name_vi']} ({topic.get('name_zh', '')}). {topic.get('desc', '')}\n"
                   "For EACH target word below write the requested number of different, natural spoken Mandarin "
                   "sentences set in this topic's real work/daily situations.\n"
                   "Rules:\n"
                   "- The sentence MUST contain the target word written exactly as given.\n"
                   f"- At most {chk.max_len} Chinese characters. End with 。？ or ！. Write numbers in Chinese characters.\n"
                   "- Use only HSK 1–3 vocabulary, plus the target word and these topic words: " + "、".join(terms) + "\n"
                   "- Vary the patterns (question, statement, request, negative). No personal names.\n"
                   "- vi: natural Vietnamese translation. en: natural English translation. "
                   "grammar: the key pattern, short, e.g. \"如果…就…\" or \"động từ + 一下\" (may be empty).\n"
                   + "Target words:\n" + "\n".join(f"- {h} ({meaning[wid]}): {need[wid]} sentence(s)" for wid, h in pending)
                   + (f"\n\nPrevious attempt had problems, avoid them:\n{feedback}" if feedback else "")
                   + '\nJSON: {"items": [{"word": "...", "sentences": [{"zh": "...", "vi": "...", "en": "...", "grammar": "..."}]}]}')
            data = ds.json(SYSTEM, ask)
            feedback = ""
            by_word = {h: wid for wid, h in pending}
            for item in data.get("items", []):
                wid = by_word.get((item.get("word") or "").strip())
                if not wid:
                    continue
                h = item["word"].strip()
                for s in item.get("sentences", []):
                    zh = (s.get("zh") or "").strip().replace("|", "，")
                    if need[wid] <= 0 or not zh:
                        break
                    seen = sents.get(wid, []) + [x["zh"] for x in accepted.get(wid, [])]
                    errs = chk.problems(zh, h) + (["trùng câu đã có"] if zh in seen else [])
                    if errs:
                        feedback += f"- {h}: 「{zh}」 → {'; '.join(errs)}\n"
                        continue
                    accepted.setdefault(wid, []).append({k: (s.get(k) or "").replace("|", "/").strip()
                                                         for k in ("vi", "en", "grammar")} | {"zh": zh})
                    need[wid] -= 1
            if feedback:
                print("  ↻ bị loại:\n    " + feedback.strip().replace("\n", "\n    "))
        missing = [h for wid, h in batch if need[wid] > 0]
        if missing:
            print(f"  ⚠ chưa đủ câu cho: {'、'.join(missing)} (chạy lại lệnh sentences để sinh bù)")

    total = 0
    for wid, h in words:
        for s in accepted.get(wid, []):
            max_e += 1; total += 1
            s["id"] = f"{topic['id']}-E{max_e:03d}"
            print(f"  {s['id']} {h}: {s['zh']}  — {s['vi']}")
    if args.dry_run or not total:
        return total
    # chèn câu E ngay sau khối của từ đó (dòng W + các dòng E đi kèm)
    for wid, h in reversed(words):
        new = [f"E|{s['id']}|{wid}|{s['zh']}|{s['vi']}|{s['en']}|{s['grammar']}" for s in accepted.get(wid, [])]
        if not new:
            continue
        i = next(k for k, l in enumerate(lines) if l.startswith(f"W|{wid}|"))
        while i + 1 < len(lines) and lines[i + 1].startswith("E|"):
            i += 1
        lines[i + 1:i + 1] = new
    write_lines(topic_words_path(topic), lines)
    return total


def gen_examples(ds, chk, level, limit, args):
    vocab = [w for w in chk.ctx["vocab"] if w["level"] == level]
    have = set()
    for f in (SRC / "examples").glob(f"hsk{level}*.txt"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                have.add(line.split("|")[0].strip())
    todo = [w for w in vocab if w["hanzi"] not in have][:limit]
    print(f"HSK{level}: {len(todo)} từ cần câu ví dụ")
    out = []
    for i in range(0, len(todo), args.batch):
        batch, feedback = todo[i:i + args.batch], ""
        for rnd in range(args.rounds + 1):
            pending = [w for w in batch if w["hanzi"] not in {o[0] for o in out}]
            if not pending:
                break
            ask = ("Write ONE short example sentence for each HSK word below, set in office / housing / city life.\n"
                   f"- MUST contain the word exactly. At most {chk.max_len} Chinese characters. End with 。？ or ！\n"
                   "- Use only HSK 1–3 vocabulary. Natural spoken Mandarin. Numbers in Chinese characters.\n"
                   "- vi: natural Vietnamese translation. en: natural English translation.\n"
                   + "\n".join(f"- {w['hanzi']} ({w['pinyin']}): {w['vi']}" for w in pending)
                   + (f"\n\nPrevious attempt had problems, avoid them:\n{feedback}" if feedback else "")
                   + '\nJSON: {"items": [{"word": "...", "zh": "...", "vi": "...", "en": "..."}]}')
            data = ds.json(SYSTEM, ask)
            feedback = ""
            want = {w["hanzi"] for w in pending}
            for it in data.get("items", []):
                h, zh = (it.get("word") or "").strip(), (it.get("zh") or "").strip().replace("|", "，")
                if h not in want or h in {o[0] for o in out}:
                    continue
                errs = chk.problems(zh, h)
                if errs:
                    feedback += f"- {h}: 「{zh}」 → {'; '.join(errs)}\n"; continue
                out.append((h, zh, (it.get("vi") or "").replace("|", "/").strip(), (it.get("en") or "").replace("|", "/").strip()))
                print(f"  {h}: {zh}  — {out[-1][2]}")
            if feedback:
                print("  ↻ bị loại:\n    " + feedback.strip().replace("\n", "\n    "))
    if out and not args.dry_run:
        p = SRC / "examples" / f"hsk{level}b.txt"
        old = p.read_text(encoding="utf-8").rstrip("\n") + "\n" if p.exists() else \
            f"# Câu ví dụ HSK{level} (sinh bằng scripts/generate.py):  từ|câu|nghĩa Việt|nghĩa Anh\n"
        p.write_text(old + "\n".join("|".join(o) for o in out) + "\n", encoding="utf-8")
    return len(out)


# ---------------------------------------------------------------- commands
def find_topic(tid):
    t = next((t for t in read_topics() if t["id"] == tid), None)
    if not t:
        sys.exit(f"Không có chủ đề {tid}")
    return t


def cmd_topic(ds, chk, args):
    topics = read_topics()
    tid = f"{max(int(t['id']) for t in topics) + 1:02d}"
    topic = {"id": tid, "slug": slugify(args.name), "name_vi": args.name, "name_zh": "", "desc": args.desc or ""}
    print(f"▶ Chủ đề mới {tid}: {args.name}")
    data = ask_words(ds, topic, args.words, [])
    topic["name_zh"] = (data.get("name_zh") or "").strip()
    topic["desc"] = args.desc or (data.get("desc") or "").strip()
    print(f"  {topic['name_zh']} · {topic['desc']}")
    if not args.dry_run:
        write_topics(topics + [topic])
    n = add_words(ds, chk, topic, data.get("words", [])[:args.words], args)
    if args.dry_run:
        print("(dry-run: không sinh câu vì từ chưa được ghi)"); return
    chk.reload()
    gen_sentences(ds, chk, topic, args.per_word, args)
    print(f"✓ Chủ đề {tid}: {n} từ. Tiếp theo: tạo file data/source/sentences/{tid}-{topic['slug']}.txt nếu muốn có mẫu câu/hội thoại riêng.")


def cmd_words(ds, chk, args):
    topic = find_topic(args.topic)
    _, words, _, _ = read_topic_words(topic)
    hint = [h.strip() for h in re.split(r"[,，、\s]+", args.list or "") if h.strip()]
    print(f"▶ Thêm từ vào chủ đề {topic['id']} {topic['name_vi']}")
    data = ask_words(ds, topic, len(hint) or args.count, [h for _, h in words], hint or None)
    n = add_words(ds, chk, topic, data.get("words", [])[:len(hint) or args.count], args)
    if args.dry_run or not n:
        return
    chk.reload()
    gen_sentences(ds, chk, topic, args.per_word, args)


def cmd_sentences(ds, chk, args):
    topic = find_topic(args.topic)
    print(f"▶ Sinh câu cho từ của chủ đề {topic['id']} {topic['name_vi']}")
    gen_sentences(ds, chk, topic, args.per_word, args)


def cmd_examples(ds, chk, args):
    gen_examples(ds, chk, args.level, args.limit, args)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true", help="chỉ in kết quả, không ghi file")
    common.add_argument("--max-len", type=int, default=18, help="số chữ Hán tối đa mỗi câu")
    common.add_argument("--batch", type=int, default=8, help="số từ mỗi lần gọi API")
    common.add_argument("--rounds", type=int, default=2, help="số vòng sinh lại câu bị loại")
    common.add_argument("--allow-unknown", type=int, default=0, help="số từ ngoài HSK1–3/chuyên ngành được phép mỗi câu")

    p = sub.add_parser("topic", parents=[common], help="tạo chủ đề mới + từ + câu")
    p.add_argument("--name", required=True, help="tên chủ đề (tiếng Việt)")
    p.add_argument("--desc", help="mô tả ngắn các tình huống")
    p.add_argument("--words", type=int, default=20)
    p.add_argument("--per-word", type=int, default=2)
    p.set_defaults(fn=cmd_topic)

    p = sub.add_parser("words", parents=[common], help="thêm từ vào chủ đề có sẵn + sinh câu")
    p.add_argument("--topic", required=True)
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--list", help="danh sách từ cụ thể, cách nhau bằng dấu phẩy")
    p.add_argument("--per-word", type=int, default=2)
    p.set_defaults(fn=cmd_words)

    p = sub.add_parser("sentences", parents=[common], help="sinh bù câu cho từ còn thiếu")
    p.add_argument("--topic", required=True)
    p.add_argument("--per-word", type=int, default=2)
    p.set_defaults(fn=cmd_sentences)

    p = sub.add_parser("examples", parents=[common], help="câu ví dụ cho từ HSK còn thiếu")
    p.add_argument("--level", type=int, choices=[2, 3], required=True)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_examples)

    args = ap.parse_args()
    if args.cmd == "examples" and args.max_len == 18:
        args.max_len = 15
    ds = DeepSeek()
    chk = Checker(args.max_len, args.allow_unknown)
    args.fn(ds, chk, args)
    print(f"  (DeepSeek: {ds.tokens} token)")
    if not args.dry_run:
        print("Tiếp theo: python scripts/build.py  →  python scripts/make_audio.py  →  python scripts/pack.py")


if __name__ == "__main__":
    main()
