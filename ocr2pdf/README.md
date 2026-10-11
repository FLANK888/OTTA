# ocr2pdf — 圖片文字辨識轉 PDF / HTML

辨識圖片上的文字 (OCR)，轉成鍵打文字，並輸出成 PDF 或 HTML 網頁（皆為真正的文字，可複製、搜尋）。

## 安裝

1. 安裝 Tesseract OCR 與中文語言包
   - Ubuntu/Debian：`sudo apt install tesseract-ocr tesseract-ocr-chi-tra tesseract-ocr-chi-sim fonts-noto-cjk`
   - macOS：`brew install tesseract tesseract-lang`
   - Windows：安裝 [UB-Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)，安裝時勾選 Chinese (Traditional)，並把安裝目錄加入 PATH
2. 安裝 Python 套件：`pip install -r requirements.txt`

## 使用

```bash
python ocr2pdf.py 照片.jpg -o 結果.pdf                # 單張圖片
python ocr2pdf.py a.png b.png c.jpg -o 結果.pdf       # 多張，每張一頁
python ocr2pdf.py 掃描資料夾/ -o 結果.pdf --continuous # 整個資料夾，文字接續排版
python ocr2pdf.py 照片.jpg -o 結果.pdf --txt          # 另外輸出 結果.txt
python ocr2pdf.py 照片.jpg -o 結果.html               # 輸出 HTML 網頁
python ocr2pdf.py 資料夾/ -o 結果.html --embed-images  # HTML 內附原圖對照
```

| 參數 | 說明 |
|---|---|
| `-f, --format` | `pdf` 或 `html`；未指定時依 `-o` 副檔名判斷 |
| `-l, --lang` | 辨識語言，預設 `chi_tra+eng`（繁中+英文）；簡中用 `chi_sim+eng` |
| `--psm` | 版面模式，預設 3（自動）；單一段落文字可試 6 |
| `--font` | 指定 PDF 字型檔（自動找不到中文字型時使用） |
| `--font-size` | 字體大小，預設 12 |
| `--continuous` | （PDF）不分頁，所有圖片文字接續 |
| `--no-title` | 不顯示圖片檔名標題 |
| `--txt` | 同時輸出純文字檔 |
| `--embed-images` | （HTML）嵌入原始圖片，與辨識文字對照 |
| `--title` | （HTML）頁面標題，預設「圖片文字辨識結果」 |

HTML 為單一檔案，可直接用瀏覽器開啟；每段文字有「複製文字」按鈕，支援深色模式，也可列印。只輸出 HTML 時不需要 fpdf2 與中文字型。

**提高辨識率：** 圖片盡量清晰、正面拍攝、光線均勻；程式已會自動轉灰階、增強對比並放大小圖。

## 網頁版（Claude Artifact）

`artifact/ocr-tool.html` 是同功能的網頁版，發布在 claude.ai 上執行：上傳、拖放或貼上圖片，由 Claude 辨識文字（中文辨識比 Tesseract 準確），可直接編輯、複製，並下載成 HTML、TXT 或 Markdown。不需安裝任何東西，辨識會使用開啟者自己的 Claude 用量。

`ocr-tool.src.html` 是原始碼，`ocr-tool.html` 是嵌入範例圖片後實際發布的檔案。
