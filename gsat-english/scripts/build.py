#!/usr/bin/env python3
"""檢查學測英文模擬卷的格式，並產生網頁讀取的資料檔。

來源：gsat-english/exams/<id>.json（每週一份，id 為 ISO 週次，例如 2026-W41）
輸出：gsat-english/data/<id>.js 與 gsat-english/data/manifest.js

用法：
    python3 gsat-english/scripts/build.py           # 檢查全部試卷並產生資料檔
    python3 gsat-english/scripts/build.py --check   # 只檢查，不寫檔

任何一份試卷不符合題型規格（見 SPEC.md），腳本會列出錯誤並以狀態碼 1 結束。
只用 Python 標準函式庫。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
EXAM_DIR = os.path.join(ROOT, "exams")
DATA_DIR = os.path.join(ROOT, "data")

ID_RE = re.compile(r"^\d{4}-W\d{2}$")
LETTERS4 = ["A", "B", "C", "D"]
LETTERS10 = list("ABCDEFGHIJ")
BLANK_RE = re.compile(r"__(\d+)__")


class Checker:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def need(self, cond: bool, msg: str) -> bool:
        if not cond:
            self.err(msg)
        return cond


def blanks(text: str) -> list[int]:
    return [int(m) for m in BLANK_RE.findall(text or "")]


def check_choice(c: Checker, q: dict, n: int, where: str, stem: bool) -> str | None:
    c.need(q.get("n") == n, f"{where}：題號應為 {n}，實際為 {q.get('n')}")
    if stem:
        c.need(bool(q.get("stem")), f"第 {n} 題缺少題幹 stem")
    opts = q.get("options")
    if c.need(isinstance(opts, list) and len(opts) == 4, f"第 {n} 題需要 4 個選項"):
        c.need(len(set(o.strip().lower() for o in opts)) == 4, f"第 {n} 題選項重複")
        c.need(all(isinstance(o, str) and o.strip() for o in opts), f"第 {n} 題有空白選項")
    ans = q.get("answer")
    c.need(ans in LETTERS4, f"第 {n} 題答案必須是 A–D，實際為 {ans!r}")
    c.need(bool(q.get("explanation")), f"第 {n} 題缺少解析")
    return ans if ans in LETTERS4 else None


def check_lettered(c: Checker, block: dict, label: str, first: int, count: int, letters: list[str]) -> None:
    nums = list(range(first, first + count))
    c.need(blanks(block.get("passage", "")) == nums, f"{label}文章的空格必須依序為 {nums}")
    opts = block.get("options") or {}
    c.need(sorted(opts) == letters, f"{label}選項代號必須是 {letters[0]}–{letters[-1]}")
    c.need(len(set(v.strip().lower() for v in opts.values())) == len(opts), f"{label}選項重複")
    answers = block.get("answers") or {}
    c.need(sorted(answers, key=int) == [str(n) for n in nums], f"{label}答案必須涵蓋 {nums[0]}–{nums[-1]} 題")
    used = list(answers.values())
    c.need(all(a in letters for a in used), f"{label}答案代號不在選項範圍內")
    c.need(len(set(used)) == len(used), f"{label}每個選項只能用一次")
    expl = block.get("explanations") or {}
    c.need(sorted(expl, key=int) == [str(n) for n in nums], f"{label}每題都需要解析")
    if letters is LETTERS10:
        order = [answers.get(str(n)) for n in nums]
        if order == sorted(order):
            c.err(f"{label}答案依字母順序排列，請打亂選項")


def check_exam(path: str) -> tuple[Checker, dict | None]:
    c = Checker(os.path.basename(path))
    try:
        with open(path, encoding="utf-8") as f:
            exam = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        c.err(f"無法讀取 JSON：{e}")
        return c, None

    stem_id = os.path.splitext(os.path.basename(path))[0]
    c.need(ID_RE.match(exam.get("id", "")) is not None, "id 必須是 YYYY-Www 格式")
    c.need(exam.get("id") == stem_id, f"id 必須與檔名相同（{stem_id}）")
    c.need(re.match(r"^\d{4}-\d{2}-\d{2}$", exam.get("date", "")) is not None, "date 必須是 YYYY-MM-DD")
    c.need(bool(exam.get("title")), "缺少 title")
    c.need(isinstance(exam.get("topics"), list) and len(exam["topics"]) >= 8, "topics 需列出各篇文章主題（至少 8 個）")

    single_answers: list[str] = []

    # 一、詞彙題 1–10
    vocab = exam.get("vocabulary") or []
    if c.need(len(vocab) == 10, "詞彙題需要 10 題"):
        for i, q in enumerate(vocab):
            a = check_choice(c, q, 1 + i, "詞彙題", stem=True)
            if a:
                single_answers.append(a)
            c.need("________" in q.get("stem", ""), f"第 {1 + i} 題題幹需有 ________ 空格")

    # 二、綜合測驗 11–20（兩篇各 5 題）
    cloze = exam.get("cloze") or []
    if c.need(len(cloze) == 2, "綜合測驗需要 2 篇文章"):
        n = 11
        for k, group in enumerate(cloze):
            qs = group.get("questions") or []
            nums = list(range(n, n + 5))
            c.need(len(qs) == 5, f"綜合測驗第 {k + 1} 篇需要 5 題")
            c.need(blanks(group.get("passage", "")) == nums, f"綜合測驗第 {k + 1} 篇空格必須依序為 {nums}")
            for i, q in enumerate(qs):
                a = check_choice(c, q, n + i, "綜合測驗", stem=False)
                if a:
                    single_answers.append(a)
            n += 5

    # 三、文意選填 21–30（A–J）
    check_lettered(c, exam.get("fill") or {}, "文意選填", 21, 10, LETTERS10)

    # 四、篇章結構 31–34（A–D）
    check_lettered(c, exam.get("structure") or {}, "篇章結構", 31, 4, LETTERS4)

    # 五、閱讀測驗 35–46（三篇各 4 題）
    reading = exam.get("reading") or []
    if c.need(len(reading) == 3, "閱讀測驗需要 3 篇文章"):
        n = 35
        for k, group in enumerate(reading):
            qs = group.get("questions") or []
            c.need(len(qs) == 4, f"閱讀測驗第 {k + 1} 篇需要 4 題")
            words = len((group.get("passage") or "").split())
            if not 220 <= words <= 450:
                c.warn(f"閱讀測驗第 {k + 1} 篇約 {words} 字，建議 250–400 字")
            for i, q in enumerate(qs):
                a = check_choice(c, q, n + i, "閱讀測驗", stem=True)
                if a:
                    single_answers.append(a)
            n += 4

    # 第貳部分 混合題 47–50（共 10 分）
    mixed = exam.get("mixed") or {}
    mqs = mixed.get("questions") or []
    c.need(bool(mixed.get("passage")), "混合題缺少文章")
    if c.need([q.get("n") for q in mqs] == [47, 48, 49, 50], "混合題題號必須是 47–50"):
        c.need(sum(q.get("points", 0) for q in mqs) == 10, "混合題總分必須是 10 分")
        table_text = json.dumps(mixed.get("table") or {}, ensure_ascii=False)
        for q in mqs:
            t, n = q.get("type"), q.get("n")
            c.need(t in ("choice", "multi", "fill", "short"), f"第 {n} 題 type 必須是 choice/multi/fill/short")
            c.need(bool(q.get("explanation")), f"第 {n} 題缺少解析")
            if t == "fill":
                c.need(bool(q.get("accepted")), f"第 {n} 題需列出可接受答案 accepted")
                c.need(f"__{n}__" in table_text or f"__{n}__" in mixed.get("passage", ""),
                       f"第 {n} 題的空格 __{n}__ 必須出現在 table 或文章中")
            elif t == "multi":
                opts = q.get("options") or {}
                ans = q.get("answer") or []
                c.need(len(opts) >= 5, f"第 {n} 題多選題至少 5 個選項")
                c.need(isinstance(ans, list) and 1 <= len(ans) < len(opts) and all(a in opts for a in ans),
                       f"第 {n} 題多選答案不正確")
            elif t == "choice":
                c.need(len(q.get("options") or []) == 4 and q.get("answer") in LETTERS4, f"第 {n} 題單選格式不正確")
            elif t == "short":
                c.need(bool(q.get("reference")), f"第 {n} 題缺少參考答案 reference")

    # 第參部分 非選擇題：中譯英 2 題（各 4 分）＋ 英文作文（20 分）
    tr = exam.get("translation") or []
    if c.need(len(tr) == 2, "中譯英需要 2 題"):
        for i, q in enumerate(tr):
            c.need(q.get("n") == i + 1 and q.get("points") == 4, f"中譯英第 {i + 1} 題題號或配分錯誤")
            c.need(bool(q.get("zh")) and bool(q.get("reference")), f"中譯英第 {i + 1} 題缺少題目或參考譯文")
    w = exam.get("writing") or {}
    c.need(w.get("points") == 20 and bool(w.get("prompt")) and bool(w.get("reference")), "英文作文需要 prompt、reference，配分 20")
    if w.get("reference"):
        words = len(w["reference"].split())
        if words < 120:
            c.err(f"作文範文只有 {words} 字，至少需要 120 字")

    # 單選題答案分布：避免某個字母過多或過少
    if len(single_answers) == 32:
        dist = Counter(single_answers)
        for letter in LETTERS4:
            if not 5 <= dist.get(letter, 0) <= 11:
                c.err(f"單選題答案分布不平均：{dict(sorted(dist.items()))}（每個字母應出現 5–11 次）")
                break
        run = 1
        for a, b in zip(single_answers, single_answers[1:]):
            run = run + 1 if a == b else 1
            if run >= 4:
                c.err("單選題有連續 4 題以上答案相同，請調整選項順序")
                break

    return c, exam


def summary(exam: dict) -> dict:
    return {"id": exam["id"], "date": exam["date"], "title": exam["title"], "topics": exam["topics"]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="只檢查，不寫檔")
    args = ap.parse_args()

    paths = sorted(os.path.join(EXAM_DIR, f) for f in os.listdir(EXAM_DIR) if f.endswith(".json"))
    if not paths:
        print("exams/ 裡沒有試卷", file=sys.stderr)
        return 1

    exams, failed = [], False
    for p in paths:
        c, exam = check_exam(p)
        for w in c.warnings:
            print(f"[警告] {c.name}：{w}")
        for e in c.errors:
            print(f"[錯誤] {c.name}：{e}", file=sys.stderr)
        if c.errors:
            failed = True
        elif exam:
            exams.append(exam)
            print(f"[通過] {c.name}")

    if failed:
        return 1
    if args.check:
        return 0

    os.makedirs(DATA_DIR, exist_ok=True)
    keep = {f"{e['id']}.js" for e in exams} | {"manifest.js"}
    for f in os.listdir(DATA_DIR):
        if f.endswith(".js") and f not in keep:
            os.remove(os.path.join(DATA_DIR, f))
    for e in exams:
        with open(os.path.join(DATA_DIR, f"{e['id']}.js"), "w", encoding="utf-8") as f:
            f.write("window.GSAT_EXAMS=window.GSAT_EXAMS||{};\n")
            f.write(f"window.GSAT_EXAMS[{json.dumps(e['id'])}]={json.dumps(e, ensure_ascii=False)};\n")
    manifest = [summary(e) for e in sorted(exams, key=lambda e: e["id"], reverse=True)]
    with open(os.path.join(DATA_DIR, "manifest.js"), "w", encoding="utf-8") as f:
        f.write(f"window.GSAT_MANIFEST={json.dumps(manifest, ensure_ascii=False, indent=1)};\n")
    print(f"已產生 {len(exams)} 份試卷的資料檔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
