# ocr2pdf — 圖片文字辨識轉 PDF

辨識圖片上的文字 (OCR)，轉成鍵打文字，並輸出成 PDF（PDF 內為真正的文字，可複製、搜尋）。

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
```

| 參數 | 說明 |
|---|---|
| `-l, --lang` | 辨識語言，預設 `chi_tra+eng`（繁中+英文）；簡中用 `chi_sim+eng` |
| `--psm` | 版面模式，預設 3（自動）；單一段落文字可試 6 |
| `--font` | 指定 PDF 字型檔（自動找不到中文字型時使用） |
| `--font-size` | 字體大小，預設 12 |
| `--continuous` | 不分頁，所有圖片文字接續 |
| `--no-title` | 不顯示圖片檔名標題 |
| `--txt` | 同時輸出純文字檔 |

**提高辨識率：** 圖片盡量清晰、正面拍攝、光線均勻；程式已會自動轉灰階、增強對比並放大小圖。
