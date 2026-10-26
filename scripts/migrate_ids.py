#!/usr/bin/env python3
"""
Chuyển file nguồn sang ID tường minh (chạy MỘT lần, idempotent).

    python scripts/migrate_ids.py

- sentences/NN-*.txt:  S|câu|…        → S|03-S12|câu|…
                       D|A|câu|…      → D|03-D2-1|A|câu|…
- topic_terms.txt:     押金|yā jīn|…  → T03-001|押金|yā jīn|…
- topic_words/NN-*.txt (mới): danh sách từ của mỗi chủ đề, lấy từ topic_terms
  (từ thuộc HSK 2–3 dùng ID H…, còn lại dùng ID T…).

ID sinh ra giống hệt ID mà build.py đang đánh theo thứ tự dòng, nên tiến độ người học không bị lệch.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data/source"
ID_S = re.compile(r"^\d{2}-S\d{2,3}$")
ID_D = re.compile(r"^\d{2}-D\d+-\d+$")
ID_T = re.compile(r"^T\d{2}-\d{3}$")


def migrate_sentences(path, tid):
    out, s_no, d_no, in_dlg, turn, changed = [], 0, 0, False, 0, 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            if not line:
                in_dlg = False
            out.append(raw)
            continue
        f = line.split("|")
        if f[0] == "S":
            s_no += 1
            if not ID_S.match(f[1]):
                f.insert(1, f"{tid}-S{s_no:02d}"); changed += 1
        elif f[0] == "D":
            if not in_dlg:
                d_no, turn, in_dlg = d_no + 1, 0, True
            turn += 1
            if not ID_D.match(f[1]):
                f.insert(1, f"{tid}-D{d_no}-{turn}"); changed += 1
        out.append("|".join(f))
    text = "\n".join(out) + "\n"
    text = text.replace("# S|câu|nghĩa Việt|ngữ pháp", "# S|ID|câu|nghĩa Việt|ngữ pháp") \
               .replace("# D|người nói|câu|nghĩa Việt|ngữ pháp", "# D|ID|người nói|câu|nghĩa Việt|ngữ pháp")
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def migrate_terms():
    p = SRC / "topic_terms.txt"
    out, cur, counters, terms, changed = [], None, {}, {}, 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            cur = line[3:].split()[0]
            out.append(raw); continue
        if not line or line.startswith("#") or not cur:
            out.append(raw); continue
        f = [x.strip() for x in line.split("|")]
        if ID_T.match(f[0]):
            tid = f[0]
            counters[cur] = max(counters.get(cur, 0), int(tid[-3:]))
        else:
            counters[cur] = counters.get(cur, 0) + 1
            tid = f"T{cur}-{counters[cur]:03d}"
            f.insert(0, tid); changed += 1
        terms.setdefault(cur, []).append((tid, f[1]))
        out.append("|".join(f))
    text = "\n".join(out) + "\n"
    text = text.replace("# Định dạng:  chữ Hán|pinyin (cách âm tiết bằng dấu cách)|nghĩa Việt",
                        "# Định dạng:  ID|chữ Hán|pinyin (cách âm tiết bằng dấu cách)|nghĩa Việt|nghĩa Anh (tuỳ chọn)\n"
                        "# ID: T{chủ đề}-{nnn}, không bao giờ tái sử dụng.")
    if changed:
        p.write_text(text, encoding="utf-8")
    return changed, terms


def main():
    topics = json.loads((SRC / "topics.json").read_text(encoding="utf-8"))
    for t in topics:
        for path in (SRC / "sentences").glob(f"{t['id']}-*.txt"):
            n = migrate_sentences(path, t["id"])
            print(f"{path.name}: {n} dòng thêm ID")
    n, terms = migrate_terms()
    print(f"topic_terms.txt: {n} dòng thêm ID")

    hsk = {}
    vendor = ROOT / "data/vendor/hsk30"
    for lvl in (2, 3):
        for i, w in enumerate(json.loads((vendor / f"{lvl}.json").read_text(encoding="utf-8")), 1):
            hsk.setdefault(w["simplified"], f"H{lvl}-{i:03d}")

    wdir = SRC / "topic_words"; wdir.mkdir(exist_ok=True)
    for t in topics:
        path = wdir / f"{t['id']}-{t['slug']}.txt"
        if path.exists():
            continue
        lines = [f"# Từ vựng chủ đề {t['id']} — {t['name_vi']}",
                 "# W|ID từ|chữ Hán                         từ thuộc chủ đề (thứ tự = thứ tự nghe)",
                 "# E|ID câu|ID từ|câu|nghĩa Việt|nghĩa Anh|ngữ pháp   câu của từ (sinh bằng scripts/generate.py)",
                 ""]
        lines += [f"W|{hsk.get(h, tid)}|{h}" for tid, h in terms.get(t["id"], [])]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"topic_words/{path.name}: {len(terms.get(t['id'], []))} từ")


if __name__ == "__main__":
    main()
