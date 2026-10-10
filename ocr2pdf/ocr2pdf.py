#!/usr/bin/env python3
"""圖片文字辨識 (OCR) → 轉成可編輯/可搜尋的文字 → 輸出 PDF 或 HTML。

用法:
    python ocr2pdf.py 圖片1.jpg 圖片2.png -o 輸出.pdf
    python ocr2pdf.py 圖片資料夾/ -o 輸出.pdf --lang chi_tra+eng
    python ocr2pdf.py 圖片1.jpg -o 輸出.html          (副檔名 .html 即輸出網頁)
"""
import argparse
import base64
import html
import mimetypes
import os
import re
import sys
import tempfile
from pathlib import Path

import pytesseract
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
    from fpdf import FPDF

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


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#f7f7f5; --card:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#e3e3e0; --accent:#2f6fde; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#161617; --card:#1f1f21; --fg:#ececee; --muted:#9a9aa0; --line:#333336; --accent:#6ea0ff; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif; line-height:1.75; }}
  main {{ max-width:860px; margin:0 auto; padding:32px 16px 64px; }}
  h1 {{ font-size:1.5rem; margin:0 0 4px; }}
  .meta {{ color:var(--muted); font-size:.9rem; margin-bottom:24px; }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px; margin-bottom:20px; }}
  header {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:12px; }}
  h2 {{ font-size:1.05rem; margin:0; word-break:break-all; }}
  button {{ font:inherit; font-size:.85rem; color:var(--accent); background:none; border:1px solid var(--line);
    border-radius:8px; padding:4px 12px; cursor:pointer; white-space:nowrap; }}
  button:hover {{ border-color:var(--accent); }}
  img {{ max-width:100%; border:1px solid var(--line); border-radius:8px; margin-bottom:12px; }}
  .text {{ white-space:pre-wrap; word-break:break-word; font-size:{font_size}px; margin:0; }}
  .empty {{ color:var(--muted); font-style:italic; }}
  @media print {{ button {{ display:none; }} section {{ break-inside:avoid; border:none; }} }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<div class="meta">共 {count} 張圖片 · 由 ocr2pdf 辨識產生</div>
{sections}
</main>
<script>
document.querySelectorAll("button[data-copy]").forEach(function (b) {{
  b.addEventListener("click", function () {{
    var t = document.getElementById(b.dataset.copy).innerText;
    navigator.clipboard.writeText(t).then(function () {{
      b.textContent = "已複製"; setTimeout(function () {{ b.textContent = "複製文字"; }}, 1500);
    }});
  }});
}});
</script>
</body>
</html>
"""


def image_data_uri(path):
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def build_html(results, output, font_size, show_title, embed_images, title):
    sections = []
    for i, (path, text) in enumerate(results):
        parts = ["<section>"]
        if show_title:
            parts.append(f'<header><h2>{html.escape(path.name)}</h2>'
                         f'<button data-copy="t{i}">複製文字</button></header>')
        if embed_images:
            parts.append(f'<img src="{image_data_uri(path)}" alt="{html.escape(path.name)}">')
        if text:
            parts.append(f'<p class="text" id="t{i}">{html.escape(text)}</p>')
        else:
            parts.append(f'<p class="text empty" id="t{i}">(未辨識到文字)</p>')
        parts.append("</section>")
        sections.append("\n".join(parts))
    Path(output).write_text(HTML_TEMPLATE.format(
        title=html.escape(title), count=len(results), font_size=round(font_size * 4 / 3),
        sections="\n".join(sections)), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="辨識圖片上的文字並輸出成 PDF 或 HTML")
    ap.add_argument("inputs", nargs="+", help="圖片檔或資料夾")
    ap.add_argument("-o", "--output", default="output.pdf", help="輸出檔名，副檔名 .pdf 或 .html 決定格式 (預設 output.pdf)")
    ap.add_argument("-f", "--format", choices=["pdf", "html"],
                    help="輸出格式；未指定時依 --output 副檔名判斷")
    ap.add_argument("-l", "--lang", default="chi_tra+eng",
                    help="Tesseract 語言，例如 chi_tra+eng、chi_sim、eng (預設 chi_tra+eng)")
    ap.add_argument("--psm", type=int, default=3, help="Tesseract 版面模式 (預設 3=自動；6=單一文字區塊)")
    ap.add_argument("--font", help="PDF 使用的字型檔 (.ttf/.otf/.ttc)")
    ap.add_argument("--font-size", type=int, default=12)
    ap.add_argument("--continuous", action="store_true", help="所有圖片的文字接續排版，不分頁")
    ap.add_argument("--no-title", action="store_true", help="不在每段文字前標示圖片檔名")
    ap.add_argument("--txt", action="store_true", help="另外輸出同名 .txt 純文字檔")
    ap.add_argument("--embed-images", action="store_true", help="HTML 輸出時一併嵌入原始圖片，方便對照")
    ap.add_argument("--title", default="圖片文字辨識結果", help="HTML 頁面標題")
    args = ap.parse_args()

    images = collect_images(args.inputs)
    if not images:
        sys.exit("沒有可處理的圖片。")

    fmt = args.format or ("html" if Path(args.output).suffix.lower() in (".html", ".htm") else "pdf")
    output = args.output
    if args.format and Path(output).suffix.lower() not in ({".html", ".htm"} if fmt == "html" else {".pdf"}):
        output = str(Path(output).with_suffix("." + fmt))

    results = []
    for path in images:
        print(f"辨識中: {path.name} ...", flush=True)
        results.append((path, ocr_image(path, args.lang, args.psm)))

    if fmt == "html":
        build_html(results, output, args.font_size, not args.no_title, args.embed_images, args.title)
    else:
        font = resolve_font(args.font)
        build_pdf([(p.name, t) for p, t in results], output, font, args.font_size,
                  not args.continuous, not args.no_title)
    if args.txt:
        Path(output).with_suffix(".txt").write_text(
            "\n\n".join(f"== {p.name} ==\n{t}" for p, t in results), encoding="utf-8")
    print(f"完成，已輸出: {output}")


if __name__ == "__main__":
    main()
