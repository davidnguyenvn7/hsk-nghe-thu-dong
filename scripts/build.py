#!/usr/bin/env python3
"""
Build toàn bộ dữ liệu từ data/source + data/vendor → data/build và web/data.js.

    python scripts/build.py

Đầu vào (chỉnh tay):
  data/source/topics.json                 12 chủ đề
  data/source/vocab_vi/hsk2.txt, hsk3.txt nghĩa tiếng Việt:  chữ Hán|nghĩa|pinyin (pinyin chỉ khi muốn ép âm)
  data/source/sentences/NN-slug.txt       mẫu câu (S|… và D|…)
  data/source/topic_terms.txt             từ chuyên ngành theo chủ đề (ngoài HSK 3)
  data/source/pinyin_phrases.txt          sửa pinyin cho cụm từ:  cụm|pin yin
  data/vendor/hsk30/{1,2,3}.json          danh sách HSK 3.0 chính thức (MIT, drkameleon/complete-hsk-vocabulary)

Đầu ra:
  data/build/vocab.json        1.703 từ HSK 3.0 cấp 2–3 (có chủ đề + câu ví dụ liên kết)
  data/build/sentences.json    mọi câu (câu đơn + lượt hội thoại), có pinyin, tách từ, cấp độ từng từ
  data/build/topic_terms.json  từ chuyên ngành theo chủ đề
  data/build/topics.json       chủ đề + thống kê
  data/build/stats.json        độ phủ từ vựng, phân bố cấp độ
  data/build/csv/*.csv         bảng cho Excel / Google Sheets
  data/build/missing_examples.tsv  từ chưa có câu ví dụ
  docs/ngu-phap.md             chỉ mục điểm ngữ pháp sinh tự động
"""
import csv, json, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import jieba
from pypinyin import lazy_pinyin, Style, load_phrases_dict

ROOT = Path(__file__).resolve().parent.parent
SRC, VENDOR, BUILD = ROOT / "data/source", ROOT / "data/vendor/hsk30", ROOT / "data/build"
jieba.setLogLevel(60)

HAN = re.compile(r"[一-鿿]")
PUNCT = {"，": ",", "。": ".", "？": "?", "！": "!", "、": ",", "：": ":", "；": ";",
         "“": '"', "”": '"', "（": "(", "）": ")", "…": "…", "—": "—"}
POS_VI = {'n': 'danh từ', 'v': 'động từ', 'a': 'tính từ', 'd': 'phó từ', 'm': 'số từ', 'q': 'lượng từ',
          'r': 'đại từ', 'p': 'giới từ', 'c': 'liên từ', 'u': 'trợ từ', 'y': 'ngữ khí từ', 'e': 'thán từ',
          'f': 'phương vị từ', 't': 'từ thời gian', 's': 'từ nơi chốn', 'nr': 'tên người', 'ns': 'địa danh',
          'nz': 'danh từ riêng', 'vn': 'danh động từ', 'an': 'danh tính từ', 'ad': 'phó tính từ',
          'l': 'quán ngữ', 'i': 'thành ngữ', 'b': 'khu biệt từ', 'z': 'từ trạng thái'}


# ---------------------------------------------------------------- pinyin helpers
def join_syllables(syls):
    """['xī','ān'] -> "xī'ān" (dấu ' trước âm tiết bắt đầu bằng a/o/e)."""
    out = ""
    for i, s in enumerate(syls):
        first = unicodedata.normalize("NFD", s)[:1].lower()
        out += ("'" if i and first in "aoe" else "") + s
    return out


def norm_py(p):
    """Chuẩn hoá pinyin nguồn ('ān jìng', 'yǒukòngr5') -> 'ānjìng'."""
    p = re.sub(r"(\w)5\b", r"\1", p.strip())
    return join_syllables(p.split())


def syllable_count(py):
    return len([s for s in re.split(r"[\s']+", py) if s]) if py else 0


# ---------------------------------------------------------------- load sources
def load_vendor():
    vendor, level_of = {}, {}
    for lvl in (1, 2, 3):
        for i, w in enumerate(json.loads((VENDOR / f"{lvl}.json").read_text(encoding="utf-8")), 1):
            h = w["simplified"]
            forms = []
            for f in w["forms"]:
                p = norm_py(f["transcriptions"]["pinyin"])
                if p.lower() not in [x["py"].lower() for x in forms]:
                    forms.append({"py": p, "en": f["meanings"][:3]})
            vendor[(lvl, h)] = {"idx": i, "forms": forms, "pos": w.get("pos", []), "freq": w.get("frequency")}
            level_of.setdefault(h, lvl)
    return vendor, level_of


def load_vi(lvl):
    out = {}
    for n, line in enumerate((SRC / f"vocab_vi/hsk{lvl}.txt").read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        out[parts[0]] = {"vi": parts[1], "py": parts[2] if len(parts) > 2 and parts[2] else None, "line": n}
    return out


ID_TERM = re.compile(r"^T\d{2}-\d{3}$")
ID_SENT = re.compile(r"^\d{2}-(S\d{2,3}|D\d+-\d+|E\d{3,4})$")
ID_WORD = re.compile(r"^(H[1-3]-\d{3}|T\d{2}-\d{3})$")


def load_terms():
    """topic_terms.txt:  '## 01' rồi các dòng  ID|chữ Hán|pinyin|nghĩa Việt|nghĩa Anh
    (định dạng cũ không có ID vẫn đọc được, ID khi đó đánh theo thứ tự dòng)."""
    terms, cur, counters = defaultdict(list), None, defaultdict(int)
    p = SRC / "topic_terms.txt"
    if not p.exists():
        return terms
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("## "):
            cur = line[3:].split()[0]
        elif line and not line.startswith("#") and cur:
            f = [x.strip() for x in line.split("|")]
            counters[cur] += 1
            tid = f.pop(0) if ID_TERM.match(f[0]) else f"T{cur}-{counters[cur]:03d}"
            h, py, vi, en = (f + ["", "", ""])[:4]
            terms[cur].append({"id": tid, "hanzi": h, "pinyin": py, "vi": vi, "en": en})
    return terms


def load_topic_words(topic):
    """topic_words/NN-*.txt:  W|ID từ|chữ Hán   và   E|ID câu|ID từ|câu|nghĩa Việt|nghĩa Anh|ngữ pháp"""
    words, sents = [], []
    for path in (SRC / "topic_words").glob(f"{topic['id']}-*.txt"):
        for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            f = [x.strip() for x in line.split("|")]
            if f[0] == "W" and len(f) >= 3 and ID_WORD.match(f[1]):
                words.append({"id": f[1], "hanzi": f[2], "src": f"{path.name}:{n}"})
            elif f[0] == "E" and len(f) >= 5 and ID_SENT.match(f[1]):
                f += [""] * (7 - len(f))
                sents.append({"id": f[1], "type": "E", "dialogue": None, "speaker": None, "word": f[2],
                              "zh": f[3], "vi": f[4], "en": f[5], "grammar": f[6], "src": f"{path.name}:{n}"})
            else:
                sys.exit(f"Dòng không hợp lệ {path.name}:{n}: {raw}")
    return words, sents


def load_phrases():
    p, d = SRC / "pinyin_phrases.txt", {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "|" in line and not line.startswith("#"):
                w, py = (x.strip() for x in line.split("|", 1))
                d[w] = py.split()
    return d


def load_sentences(topic):
    """Trả về list mục: câu đơn (S) và lượt hội thoại (D).
    ID tường minh (S|03-S12|… , D|03-D2-1|A|…); dòng chưa có ID thì đánh theo thứ tự như trước."""
    path = next((SRC / "sentences").glob(f"{topic['id']}-*.txt"), None)
    if not path:
        return []
    items, s_no, d_no, in_dialogue, turn = [], 0, 0, False, 0
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not line:
            in_dialogue = False
            continue
        f = [x.strip() for x in line.split("|")]
        explicit = len(f) > 1 and ID_SENT.match(f[1])
        if f[0] == "S":
            s_no += 1
            sid = f.pop(1) if explicit else f"{topic['id']}-S{s_no:02d}"
            items.append({"id": sid, "type": "S", "dialogue": None, "speaker": None,
                          "zh": f[1], "vi": f[2], "grammar": f[3] if len(f) > 3 else "", "src": f"{path.name}:{n}"})
        elif f[0] == "D":
            if not in_dialogue:
                d_no, turn, in_dialogue = d_no + 1, 0, True
            turn += 1
            sid = f.pop(1) if explicit else f"{topic['id']}-D{d_no}-{turn}"
            items.append({"id": sid, "type": "D", "dialogue": sid.rsplit("-", 1)[0],
                          "speaker": f[1], "zh": f[2], "vi": f[3], "grammar": f[4] if len(f) > 4 else "",
                          "src": f"{path.name}:{n}"})
        else:
            sys.exit(f"Dòng không hợp lệ {path.name}:{n}: {raw}")
    return items


# ---------------------------------------------------------------- segmentation + pinyin
NUM = set("零一二三四五六七八九十百千万亿两")
TONE = {c: t for t, cs in enumerate(["āēīōūǖ", "áéíóúǘ", "ǎěǐǒǔǚ", "àèìòùǜ"], 1) for c in cs}


def tone_of(syl):
    return next((TONE[c] for c in syl if c in TONE), 0)


def strip_tone(s):
    s = s.replace("ü", "v").replace("Ü", "V")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s.lower().replace("v", "ü")


def _syllable_set():
    from pypinyin import pinyin_dict
    out = set()
    for v in pinyin_dict.pinyin_dict.values():
        for p in v.split(","):
            out.add(strip_tone(p))
    return out


SYLLABLES = _syllable_set()


def split_syllables(py):
    """'piányi' -> ['pián','yi'];  "xī'ān" -> ['xī','ān'];  'yǒukòngr' -> ['yǒu','kòngr']"""
    out = []
    for chunk in re.split(r"[\s']+", py.strip()):
        if not chunk:
            continue
        n, best = len(chunk), {0: []}
        for i in range(n):
            if i not in best:
                continue
            for j in range(i + 1, min(n, i + 7) + 1):
                piece = strip_tone(chunk[i:j])
                ok = piece in SYLLABLES or (piece.endswith("r") and piece[:-1] in SYLLABLES and j == n)
                if ok and j not in best:
                    best[j] = best[i] + [chunk[i:j]]
        if n not in best:
            return None
        out += best[n]
    return out


class Segmenter:
    def __init__(self, level_of, curated_py, extra_words, terms=()):
        self.level_of, self.curated, self.terms = level_of, {}, set(terms)
        self.dict = set(level_of) | set(extra_words)
        for w in self.dict:
            jieba.add_word(w, freq=50000)
        self.maxlen = max(map(len, self.dict))
        self.fixes = {}                                   # ép tách: 可以来 -> [可以, 来]
        fx = SRC / "seg_fixes.txt"
        if fx.exists():
            for line in fx.read_text(encoding="utf-8").splitlines():
                if "|" in line and not line.startswith("#"):
                    parts = [x.strip() for x in line.split("|")]
                    self.fixes["".join(parts)] = parts
        phrases = {}
        for w, py in curated_py.items():
            syl = split_syllables(py)
            if not syl:
                print(f"⚠ Không tách được pinyin: {w} {py}")
                continue
            if w.endswith("儿") and len(syl) == len(w) - 1:      # nhi hoá: 一点儿 -> yìdiǎnr
                self.curated[w] = syl
            elif len(syl) == len(w):
                self.curated[w] = syl
                if len(w) > 1:
                    phrases[w] = [[x] for x in syl]
        load_phrases_dict(phrases)

    def max_match(self, s):
        out, i = [], 0
        while i < len(s):
            for L in range(min(self.maxlen, len(s) - i), 0, -1):
                if s[i:i + L] in self.dict or L == 1:
                    out.append(s[i:i + L]); i += L; break
        return out

    NUMRUN = re.compile(r"[零一二三四五六七八九两]*[十百千万亿][零一二三四五六七八九十百千万亿两]*(?!分(?!钟))")

    def tokens(self, text):
        # tách riêng cụm số trước (tránh 二十分钟 bị cắt thành 二 / 十分 / 钟)
        pat = self.NUMRUN.pattern
        if self.fixes:
            pat = "|".join(map(re.escape, sorted(self.fixes, key=len, reverse=True))) + "|" + pat
        pieces, last = [], 0
        for m in re.finditer(pat, text):
            if text[last:m.start()]:
                pieces += list(jieba.cut(text[last:m.start()], HMM=False))
            pieces += self.fixes.get(m.group(), [m.group()]); last = m.end()
        if text[last:]:
            pieces += list(jieba.cut(text[last:], HMM=False))
        toks = []
        for t in pieces:
            if HAN.search(t) and t not in self.dict and len(t) > 1:
                parts = self.max_match(t)
                # chỉ tách khi mọi phần đều là từ đã biết; không thì giữ nguyên (包括 không bị tách thành 包+括)
                toks += parts if all(p in self.dict for p in parts) else [t]
            else:
                toks.append(t)
        # gộp chuỗi số: 三百 五十 -> 三百五十
        merged = []
        for t in toks:
            if merged and t and set(t) <= NUM and set(merged[-1]) <= NUM and merged[-1]:
                merged[-1] += t
            else:
                merged.append(t)
        return merged

    def syllables(self, tok):
        if tok in self.curated and len(tok) > 1:
            return list(self.curated[tok])
        syl = lazy_pinyin(tok, style=Style.TONE, errors=lambda x: list(x))
        if len(tok) > 1 and tok.endswith("儿"):
            syl = syl[:-1]; syl[-1] += "r"
        return syl

    def pinyin(self, text):
        toks = self.tokens(text)
        # pinyin theo ngữ cảnh cho chữ đơn (还 hái/huán…): chạy pypinyin trên cả câu đã tách từ
        ctx = lazy_pinyin(toks, style=Style.TONE, errors=lambda x: list(x))
        seq, k = [], 0                     # seq: [tok, [syllables]]
        for t in toks:
            if not HAN.search(t):
                seq.append([t, None]); k += len(t); continue
            syl = self.syllables(t) if len(t) > 1 else [ctx[k]]
            k += len(t)
            seq.append([t, syl])
        # biến điệu 一 / 不 (theo cách ghi của giáo trình)
        flat = [(ti, si) for ti, (t, syl) in enumerate(seq) if syl for si in range(len(syl))]
        chars = [seq[ti][0][si] if si < len(seq[ti][0]) else "" for ti, si in flat]
        for n, (ti, si) in enumerate(flat):
            ch, syl = chars[n], seq[ti][1]
            nxt = seq[flat[n + 1][0]][1][flat[n + 1][1]] if n + 1 < len(flat) else None
            # chữ kế tiếp phải dính liền (không qua dấu câu)
            if nxt is not None and flat[n + 1][0] - ti > 1:
                nxt = None
            if ch == "不" and syl[si] == "bù" and nxt and tone_of(nxt) == 4:
                syl[si] = "bú"
            elif ch == "一" and syl[si] in ("yī", "yí", "yì"):
                prev = chars[n - 1] if n else ""
                nch = chars[n + 1] if n + 1 < len(chars) else ""
                if not nxt or prev in NUM or prev == "第" or (nch in NUM and nch not in "百千万亿") \
                        or nch in "月号日年点" or seq[ti][0] in ("一月", "一号", "一楼"):
                    syl[si] = "yī"
                else:
                    syl[si] = "yí" if tone_of(nxt) == 4 else "yì"
        # 个 làm lượng từ đọc nhẹ: yí ge, zhè ge, měi ge
        for n, (ti, si) in enumerate(flat):
            if chars[n] == "个" and seq[ti][1][si] == "gè" and n and (chars[n - 1] in NUM or chars[n - 1] in "这那哪几每上下整"):
                seq[ti][1][si] = "ge"
            # láy động từ AA không có trong từ điển: kàn kan
        for t, syl in seq:
            if syl and len(t) == 2 and t[0] == t[1] and t not in self.curated and len(syl) == 2:
                syl[1] = strip_tone(syl[1])
        words, s = [], ""
        for t, syl in seq:
            if syl is None:
                v = PUNCT.get(t, t)
                s = s.rstrip() + (v + " " if v in ",.?!:;)…" else v)
                words.append([t, "", None])
            else:
                py = join_syllables(syl)
                s += py + " "
                words.append([t, py, self.level(t)])
        s = re.sub(r"(^|[.?!] )(\w)", lambda m: m.group(1) + m.group(2).upper(), s.strip())
        return s, words

    def level(self, t):
        """1–3: cấp HSK · 4: từ chuyên ngành (topic_terms) · 0: chưa có trong danh sách nào."""
        if t in self.level_of:
            return self.level_of[t]
        if set(t) <= NUM:
            return 1
        if t in self.terms:
            return 4
        base = t[:-1] if len(t) > 1 and t.endswith("儿") else t          # 早点儿 -> 早点
        if base in self.level_of:
            return self.level_of[base]
        if len(base) == 2 and base[0] == base[1] and base[0] in self.level_of:   # 看看
            return self.level_of[base[0]]
        parts, i = [], 0                                                  # 这个 -> 这 + 个
        while i < len(base):
            for L in range(min(self.maxlen, len(base) - i), 0, -1):
                piece = base[i:i + L]
                if piece in self.level_of or piece in self.terms or set(piece) <= NUM:
                    parts.append(piece); i += L; break
            else:
                return 0
        lv = [self.level_of.get(p, 4 if p in self.terms else 1) for p in parts]
        return max(lv)


# ---------------------------------------------------------------- main
def load_vocab(vendor, problems):
    vocab = []
    for lvl in (2, 3):
        vi = load_vi(lvl)
        for (vl, h), v in vendor.items():
            if vl != lvl:
                continue
            g = vi.get(h)
            if not g:
                problems.append(f"Thiếu nghĩa Việt: HSK{lvl} {h}"); continue
            py = g["py"] or v["forms"][0]["py"]
            form = next((f for f in v["forms"] if f["py"].lower() == py.lower()), v["forms"][0])
            vocab.append({
                "id": f"H{lvl}-{v['idx']:03d}", "hanzi": h, "pinyin": py.lower(), "level": lvl,
                "pos": [POS_VI.get(p, p) for p in v["pos"]], "vi": g["vi"], "en": "; ".join(form["en"]),
                "pinyin_alt": [f["py"].lower() for f in v["forms"] if f["py"].lower() != py.lower()],
                "freq_rank": v["freq"], "topics": [], "examples": []})
        extra = set(vi) - {h for (vl, h) in vendor if vl == lvl}
        problems += [f"Từ trong hsk{lvl}.txt không có trong danh sách HSK: {h}" for h in extra]
    return vocab


def make_segmenter(vendor, level_of, vocab, terms, phrases):
    curated_py = {h: v["forms"][0]["py"] for (lvl, h), v in vendor.items() if lvl == 1 and len(h) > 1}
    curated_py.update({w["hanzi"]: w["pinyin"] for w in vocab})
    for tlist in terms.values():
        for t in tlist:
            if t["pinyin"]:
                curated_py.setdefault(t["hanzi"], t["pinyin"].replace(" ", ""))
    curated_py.update({k: " ".join(v) for k, v in phrases.items()})
    term_words = [t["hanzi"] for tl in terms.values() for t in tl]
    return Segmenter(level_of, curated_py, term_words + list(phrases), term_words)


def load_context():
    """Mọi thứ cần để tách từ / gắn pinyin / kiểm tra cấp độ (dùng chung với generate.py)."""
    problems = []
    vendor, level_of = load_vendor()
    terms, phrases = load_terms(), load_phrases()
    vocab = load_vocab(vendor, problems)
    seg = make_segmenter(vendor, level_of, vocab, terms, phrases)
    return {"vendor": vendor, "level_of": level_of, "terms": terms, "phrases": phrases,
            "vocab": vocab, "seg": seg, "problems": problems}


def annotate(seg, it, topic_id):
    py, words = seg.pinyin(it["zh"])
    lv = [w[2] for w in words if w[1]]
    it.update({"topic": topic_id, "pinyin": py, "tokens": words,
               "max_level": max(lv) if 0 not in lv else 5,
               "beyond_hsk3": sorted({w[0] for w in words if w[1] and w[2] in (0, 4)})})
    return it


def check_ids(sentences, term_rows, problems):
    """ID trùng = lỗi; ID có ở lần build trước mà nay biến mất = cảnh báo (tiến độ người học sẽ mồ côi)."""
    for kind, ids in (("câu", [s["id"] for s in sentences]), ("từ chuyên ngành", [r["id"] for r in term_rows])):
        dup = [i for i, c in Counter(ids).items() if c > 1]
        if dup:
            sys.exit(f"✗ ID {kind} bị trùng: {' '.join(dup)}")
    old_path = BUILD / "sentences.json"
    if old_path.exists():
        old = {s["id"]: s["zh"] for s in json.loads(old_path.read_text(encoding="utf-8"))}
        new = {s["id"]: s["zh"] for s in sentences}
        gone = sorted(set(old) - set(new))
        if gone:
            problems.append(f"ID câu có ở lần build trước nhưng nay không còn: {' '.join(gone)}")
        by_zh = {z: i for i, z in new.items()}
        moved = [f"{i}→{by_zh[z]}" for i, z in old.items() if i not in new and z in by_zh]
        if moved:
            problems.append(f"Câu bị đổi ID (ID cũ không còn): {' '.join(moved[:20])}")


def main():
    ctx = load_context()
    vendor, level_of, terms, vocab, seg, problems = (ctx[k] for k in ("vendor", "level_of", "terms", "vocab", "seg", "problems"))
    topics = json.loads((SRC / "topics.json").read_text(encoding="utf-8"))

    # ---- sentences (S, D theo chủ đề + E theo từ)
    sentences, topic_words = [], {}
    vocab_ids = {w["id"]: w for w in vocab}
    term_ids = {t["id"]: t for tl in terms.values() for t in tl}
    for t in topics:
        for it in load_sentences(t):
            sentences.append(annotate(seg, it, t["id"]))
        words, esents = load_topic_words(t)
        for w in words:
            ref = vocab_ids.get(w["id"]) or term_ids.get(w["id"])
            if not ref:
                problems.append(f"Từ {w['id']} ({w['hanzi']}) không có trong vocab lẫn topic_terms: {w['src']}")
            elif ref["hanzi"] != w["hanzi"]:
                problems.append(f"{w['id']} là {ref['hanzi']}, không phải {w['hanzi']}: {w['src']}")
        topic_words[t["id"]] = [w["id"] for w in words]
        wanted = {w["id"]: w["hanzi"] for w in words}
        for it in esents:
            if it["word"] not in wanted:
                problems.append(f"Câu {it['id']} gắn với từ {it['word']} không nằm trong danh sách W: {it['src']}")
            elif wanted[it["word"]] not in it["zh"]:
                problems.append(f"Câu {it['id']} không chứa từ {wanted[it['word']]}: {it['src']}")
            sentences.append(annotate(seg, it, t["id"]))

    by_hanzi = {w["hanzi"]: w for w in vocab}
    for s in sentences:
        for tok, py, lvl in s["tokens"]:
            w = by_hanzi.get(tok)
            if w and lvl in (2, 3):
                if s["topic"] not in w["topics"]:
                    w["topics"].append(s["topic"])
                if len(w["examples"]) < 3 and s["id"] not in w["examples"]:
                    w["examples"].append(s["id"])

    # ---- câu ví dụ cho từng từ (data/source/examples/hsk{2,3}*.txt:  từ|câu|nghĩa|nghĩa Anh)
    examples = {}
    for f in sorted((SRC / "examples").glob("hsk*.txt")):
        lvl = int(f.name[3])
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() and not line.startswith("#"):
                h, zh, vi, en = (x.strip() for x in (line.split("|") + ["", "", ""])[:4])
                examples[(lvl, h)] = (zh, vi, f"{f.name}:{n}", en)
    for w in vocab:
        ex = examples.get((w["level"], w["hanzi"]))
        if ex:
            py, _ = seg.pinyin(ex[0])
            w["example"] = {"zh": ex[0], "pinyin": py, "vi": ex[1], "en": ex[3]}
            if w["hanzi"] not in ex[0]:
                problems.append(f"Câu ví dụ không chứa từ {w['hanzi']}: {ex[2]}")
        else:
            w["example"] = None

    # ---- topic terms
    term_rows = []
    for tid, tl in terms.items():
        for t in tl:
            py = t["pinyin"] or seg.pinyin(t["hanzi"])[0].lower()
            term_rows.append({"id": t["id"], "topic": tid, "hanzi": t["hanzi"], "pinyin": py, "vi": t["vi"],
                              "en": t["en"], "level": level_of.get(t["hanzi"], 0),
                              "same_as": by_hanzi[t["hanzi"]]["id"] if t["hanzi"] in by_hanzi else None})
    check_ids(sentences, term_rows, problems)

    # ---- stats
    used = {w["hanzi"] for w in vocab if w["topics"]}
    stats = {"vocab_total": len(vocab), "vocab_by_level": dict(Counter(w["level"] for w in vocab)),
             "vocab_with_example": sum(1 for w in vocab if w["example"]),
             "sentences_total": len(sentences),
             "single_sentences": sum(s["type"] == "S" for s in sentences),
             "dialogue_turns": sum(s["type"] == "D" for s in sentences),
             "dialogues": len({s["dialogue"] for s in sentences if s["dialogue"]}),
             "word_sentences": sum(s["type"] == "E" for s in sentences),
             "topic_words": sum(len(v) for v in topic_words.values()),
             "hsk23_words_used_in_sentences": len(used),
             "hsk23_coverage_pct": round(100 * len(used) / len(vocab), 1),
             "sentence_max_level": dict(sorted(Counter(s["max_level"] for s in sentences).items())),
             "topic_terms_used": dict(Counter(w for s in sentences for w, p, l in s["tokens"] if l == 4).most_common()),
             "unknown_words": dict(Counter(w for s in sentences for w, p, l in s["tokens"] if p and l == 0).most_common()),
             "problems": problems}
    for t in topics:
        ss = [s for s in sentences if s["topic"] == t["id"]]
        t["stats"] = {"sentences": len(ss), "dialogues": len({s["dialogue"] for s in ss if s["dialogue"]}),
                      "hsk23_words": len({tok for s in ss for tok, _, l in s["tokens"] if l in (2, 3)}),
                      "terms": len(terms.get(t["id"], [])), "words": len(topic_words[t["id"]]),
                      "word_sentences": sum(s["type"] == "E" for s in ss)}
        t["words"] = topic_words[t["id"]]

    # ---- write
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "csv").mkdir(exist_ok=True)
    dump = lambda name, obj: (BUILD / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    dump("vocab.json", vocab); dump("sentences.json", sentences); dump("topics.json", topics)
    dump("topic_terms.json", term_rows); dump("stats.json", stats)

    def write_csv(name, header, rows):
        with open(BUILD / "csv" / name, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f); w.writerow(header); w.writerows(rows)
    names = {t["id"]: t["name_vi"] for t in topics} | {"00": "Dùng chung"}
    for lvl in (2, 3):
        write_csv(f"vocab_hsk{lvl}.csv", ["id", "chu_han", "pinyin", "nghia_viet", "tu_loai", "english", "chu_de",
                                          "vi_du", "vi_du_pinyin", "vi_du_nghia"],
                  [[w["id"], w["hanzi"], w["pinyin"], w["vi"], ", ".join(w["pos"]), w["en"], " ".join(w["topics"]),
                    *((w["example"]["zh"], w["example"]["pinyin"], w["example"]["vi"]) if w["example"] else ("", "", ""))]
                   for w in vocab if w["level"] == lvl])
    write_csv("sentences.csv", ["id", "chu_de", "loai", "nguoi_noi", "chu_han", "pinyin", "nghia_viet", "ngu_phap", "cap_cao_nhat", "tu_ngoai_hsk3"],
              [[s["id"], names[s["topic"]], {"S": "Câu đơn", "D": "Hội thoại", "E": "Câu theo từ"}[s["type"]], s["speaker"] or "",
                s["zh"], s["pinyin"], s["vi"], s["grammar"], s["max_level"], " ".join(s["beyond_hsk3"])] for s in sentences])
    write_csv("topic_terms.csv", ["id", "chu_de", "chu_han", "pinyin", "nghia_viet", "cap_hsk"],
              [[r["id"], names[r["topic"]], r["hanzi"], r["pinyin"], r["vi"], r["level"] or "ngoài HSK3"] for r in term_rows])

    missing = [f"{w['id']}\t{w['hanzi']}\t{w['pinyin']}\t{w['vi']}" for w in vocab if not w["example"]]
    (BUILD / "missing_examples.tsv").write_text("id\tchu_han\tpinyin\tnghia\n" + "\n".join(missing) + "\n", encoding="utf-8")

    # ---- grammar index
    g = defaultdict(list)
    for s in sentences:
        if s["grammar"]:
            g[s["grammar"]].append(s)
    md = ["# Chỉ mục ngữ pháp", "", "_Sinh tự động bởi `scripts/build.py` từ cột ngữ pháp của mẫu câu. Đừng sửa tay._", ""]
    for k in sorted(g, key=lambda k: (-len(g[k]), k)):
        md.append(f"## {k}  ·  {len(g[k])} câu")
        md += [f"- {s['zh']}  \n  {s['pinyin']}  \n  {s['vi']}  `{s['id']}`" for s in g[k][:5]]
        md.append("")
    (ROOT / "docs/ngu-phap.md").write_text("\n".join(md), encoding="utf-8")

    print(f"✓ {len(vocab)} từ HSK2–3 · {len(sentences)} câu ({stats['single_sentences']} câu đơn, "
          f"{stats['dialogues']} hội thoại) · {len(term_rows)} từ chuyên ngành")
    print(f"  Độ phủ: {stats['hsk23_coverage_pct']}% từ HSK2–3 xuất hiện trong mẫu câu · "
          f"{stats['vocab_with_example']}/{len(vocab)} từ có câu ví dụ")
    if stats["unknown_words"]:
        print("ℹ Từ chưa có trong HSK 1–3 lẫn topic_terms (nên thêm vào topic_terms.txt):",
              " ".join(stats["unknown_words"]))
    if problems:
        print("⚠ " + "\n⚠ ".join(problems))


if __name__ == "__main__":
    main()
