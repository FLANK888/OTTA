# 總經風險儀表板

這是一個每週自動更新的網頁，會抓取美國最新的總體經濟數據，並換算成 0–100 的投資風險分數。

流程：`GitHub Actions（每週六）→ update_macro.py 抓取 FRED → data/macro.json → index.html（GitHub Pages）`

## 檔案

| 路徑 | 用途 |
|---|---|
| `index.html` | 儀表板網頁，為純 HTML/JS，不需要建置步驟 |
| `data/macro.json`、`data/macro.js` | 由腳本產生的數據，內容相同；網頁讀取的是 `.js` 版本，所以直接雙擊開檔也能看 |
| `scripts/update_macro.py` | 抓取數據並計算評分，只用 Python 標準函式庫 |
| `../.github/workflows/update-macro.yml` | 每週排程更新數據，並部署到 GitHub Pages |

## 部署

1. 把分支合併到 `main`。
2. 到 GitHub repo 的 **Settings → Pages → Build and deployment**，把 Source 設為 **GitHub Actions**。
3. 到 **Actions → 每週更新總經風險儀表板 → Run workflow** 手動執行一次。第一次執行時，FRED 真實數據會取代目前 repo 裡的示範資料。
4. 之後每週六 01:17 UTC 會自動更新。

## 本機執行

```bash
python3 macro/scripts/update_macro.py          # 抓取真實數據（需能連到 fred.stlouisfed.org）
python3 macro/scripts/update_macro.py --demo   # 離線產生示範資料
```

執行後直接用瀏覽器打開 `macro/index.html` 即可。

## 指標與評分

| 類別（權重） | 指標（FRED 代碼） |
|---|---|
| 景氣成長 30% | 實質 GDP 季增年率（A191RL1Q225SBEA）、工業生產年增率（INDPRO）、密大消費者信心（UMCSENT） |
| 就業市場 20% | Sahm 衰退指標、失業率（UNRATE）、初領失業金 4 週均值年增率（ICSA） |
| 通膨與政策 20% | CPI 年增率（CPIAUCSL）、核心 PCE 年增率（PCEPILFE）、實質政策利率（DFF − 核心 PCE） |
| 金融市場壓力 30% | 10Y−3M 利差（T10Y3M）、10Y−2Y 利差（T10Y2Y）、高收益債利差（BAMLH0A0HYM2）、VIX（VIXCLS）、NFCI |

每個指標都用分段線性門檻換算成 0–100 分（定義在 `update_macro.py` 的 `INDICATORS`），先在類別內加權平均，再把各類別加權成綜合分數。

| 分數 | 等級 | 參考配置（股／債／現金／黃金防禦） |
|---|---|---|
| 0–20 | 低風險 | 70 / 20 / 5 / 5 |
| 20–40 | 中低風險 | 60 / 25 / 10 / 5 |
| 40–60 | 中度風險 | 50 / 30 / 10 / 10 |
| 60–80 | 偏高風險 | 35 / 35 / 20 / 10 |
| 80–100 | 高風險 | 20 / 40 / 25 / 15 |

要調整門檻、權重或配置，修改 `update_macro.py` 的 `INDICATORS`、`CATEGORIES`、`LEVELS` 後重新執行即可。

## 注意事項

- 歷史走勢是用目前（已修正）的數據回算的，並以觀測期間日期對齊，沒有扣除公布時間的落後，所以會比當時即時看到的數字略為樂觀。
- 如果有超過一半的序列抓不到，腳本會失敗退出，並保留舊數據。少數序列失敗時，評分會排除這些序列，網頁上也會顯示提示。
- 本專案僅供研究與教學參考，不構成投資建議。
