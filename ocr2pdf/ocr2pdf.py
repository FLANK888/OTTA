#!/usr/bin/env python3
"""圖片文字辨識 (OCR) → 轉成可編輯/可搜尋的文字 → 輸出 PDF。

用法:
    python ocr2pdf.py 圖片1.jpg 圖片2.png -o 輸出.pdf
    python ocr2pdf.py 圖片資料夾/ -o 輸出.pdf --lang chi_tra+eng
"""
import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

import pytesseract
from fpdf import FPDF
from PIL import Image, ImageOps

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}

# 常見的中文字型位置 (Linux / Windows / macOS)，依序嘗試
FONT_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK TC"),
    ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", "Noto Sans CJK TC"),
    ("C:/Windows/Fonts/msjh.ttc", None),        # 微軟正黑體
    ("C:/Windows/Fonts/mingliu.ttc", None),     # 細明體
    ("/System/Library/Fonts/PingFang.ttc", None),
    ("/Library/Fonts/Arial Unicode.ttf", None),
]

CJK = r"\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef"


def collect_images(paths):
    images = []
    for p in map(Path, paths):
        if p.is_dir():
            images += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS)
        elif p.is_file():
            images.append(p)
        else:
            print(f"找不到檔案: {p}", file=sys.stderr)
    return images


def preprocess(img):
    """灰階、自動對比、太小就放大，提高辨識率。"""
    img = ImageOps.exif_transpose(img).convert("L")
    img = ImageOps.autocontrast(img)
    if min(img.size) < 1000:
        scale = 1000 / min(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    return img


def clean_text(text):
    """Tesseract 常在中文字之間插入空白，把它們移除。"""
    text = re.sub(rf"(?<=[{CJK}]) +(?=[{CJK}])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def ocr_image(path, lang, psm):
    with Image.open(path) as img:
        frames = []
        try:  # 支援多頁 TIFF / GIF
            for i in range(getattr(img, "n_frames", 1)):
                img.seek(i)
                frames.append(preprocess(img.copy()))
        except EOFError:
            pass
    texts = [pytesseract.image_to_string(f, lang=lang, config=f"--psm {psm}") for f in frames]
    return clean_text("\n\n".join(texts))


def resolve_font(font_arg):
    """回傳 fpdf2 可用的 .ttf/.otf 路徑；.ttc 字型集會抽出單一字型。"""
    candidates = [(font_arg, None)] if font_arg else FONT_CANDIDATES
    for path, face in candidates:
        if not os.path.exists(path):
            continue
        if not path.lower().endswith(".ttc"):
            return path
        from fontTools.ttLib import TTCollection
        coll = TTCollection(path)
        idx = 0
        if face:
            names = [f["name"].getDebugName(4) for f in coll.fonts]
            idx = names.index(face) if face in names else 0
        out = Path(tempfile.gettempdir()) / f"ocr2pdf_{Path(path).stem}_{idx}.ttf"
        if not out.exists():
            coll.fonts[idx].save(out)
        return str(out)
    sys.exit("找不到中文字型，請用 --font 指定一個 .ttf/.otf/.ttc 字型檔。")


def build_pdf(results, output, font_path, font_size, page_per_image, show_title):
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("cjk", "", font_path)
    pdf.set_margins(18, 18, 18)
    for i, (name, text) in enumerate(results):
        if i == 0 or page_per_image:
            pdf.add_page()
        elif show_title:
            pdf.ln(6)
        if show_title:
            pdf.set_font("cjk", size=font_size + 3)
            pdf.multi_cell(0, (font_size + 3) * 0.6, name, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        pdf.set_font("cjk", size=font_size)
        pdf.multi_cell(0, font_size * 0.6, text or "(未辨識到文字)", new_x="LMARGIN", new_y="NEXT")
    pdf.output(output)


def main():
    ap = argparse.ArgumentParser(description="辨識圖片上的文字並輸出成 PDF")
    ap.add_argument("inputs", nargs="+", help="圖片檔或資料夾")
    ap.add_argument("-o", "--output", default="output.pdf", help="輸出 PDF 檔名 (預設 output.pdf)")
    ap.add_argument("-l", "--lang", default="chi_tra+eng",
                    help="Tesseract 語言，例如 chi_tra+eng、chi_sim、eng (預設 chi_tra+eng)")
    ap.add_argument("--psm", type=int, default=3, help="Tesseract 版面模式 (預設 3=自動；6=單一文字區塊)")
    ap.add_argument("--font", help="PDF 使用的字型檔 (.ttf/.otf/.ttc)")
    ap.add_argument("--font-size", type=int, default=12)
    ap.add_argument("--continuous", action="store_true", help="所有圖片的文字接續排版，不分頁")
    ap.add_argument("--no-title", action="store_true", help="不在每段文字前標示圖片檔名")
    ap.add_argument("--txt", action="store_true", help="另外輸出同名 .txt 純文字檔")
    args = ap.parse_args()

    images = collect_images(args.inputs)
    if not images:
        sys.exit("沒有可處理的圖片。")

    results = []
    for path in images:
        print(f"辨識中: {path.name} ...", flush=True)
        results.append((path.name, ocr_image(path, args.lang, args.psm)))

    font = resolve_font(args.font)
    build_pdf(results, args.output, font, args.font_size, not args.continuous, not args.no_title)
    if args.txt:
        Path(args.output).with_suffix(".txt").write_text(
            "\n\n".join(f"== {n} ==\n{t}" for n, t in results), encoding="utf-8")
    print(f"完成，已輸出: {args.output}")


if __name__ == "__main__":
    main()
