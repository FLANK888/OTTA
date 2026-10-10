#!/usr/bin/env python3
"""每週更新總體經濟數據並計算投資風險評分。

資料來源：美國聖路易聯準銀行 FRED（公開 CSV，不需 API key）。
輸出：macro/data/macro.json 與 macro/data/macro.js（供網頁直接載入）。

用法：
    python3 macro/scripts/update_macro.py          # 抓取 FRED 最新數據
    python3 macro/scripts/update_macro.py --demo   # 產生示範資料（離線測試用）

只用 Python 標準函式庫，無需安裝任何套件。
"""

from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

FRED_BASE_URL = os.environ.get("FRED_BASE_URL", "https://fred.stlouisfed.org")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

HISTORY_YEARS = 5      # 綜合風險分數回溯年數
SPARK_YEARS = 3        # 每個指標走勢圖顯示年數
FETCH_YEARS = HISTORY_YEARS + 3  # 計算年增率等需要額外的歷史

# FRED 原始序列：代碼 -> (中文名稱, 頻率)
RAW_SERIES = {
    "T10Y3M": ("10年期減3個月期美債利差", "daily"),
    "T10Y2Y": ("10年期減2年期美債利差", "daily"),
    "BAMLH0A0HYM2": ("美國高收益債利差", "daily"),
    "VIXCLS": ("VIX 波動率指數", "daily"),
    "NFCI": ("芝加哥聯準金融狀況指數", "weekly"),
    "ICSA": ("初領失業救濟金人數", "weekly"),
    "UNRATE": ("失業率", "monthly"),
    "CPIAUCSL": ("CPI", "monthly"),
    "PCEPILFE": ("核心 PCE 物價指數", "monthly"),
    "DFF": ("聯邦基金有效利率", "daily"),
    "DGS10": ("10年期美債殖利率", "daily"),
    "A191RL1Q225SBEA": ("實質 GDP 季增年率", "quarterly"),
    "INDPRO": ("工業生產指數", "monthly"),
    "UMCSENT": ("密大消費者信心", "monthly"),
    "DTWEXBGS": ("美元廣義指數", "daily"),
}

CATEGORIES = {
    "growth": {"name": "景氣成長", "weight": 0.30},
    "labor": {"name": "就業市場", "weight": 0.20},
    "inflation": {"name": "通膨與政策", "weight": 0.20},
    "market": {"name": "金融市場壓力", "weight": 0.30},
}

LEVELS = [
    # (上限, key, 名稱, 建議姿態, 參考配置)
    (20, "low", "低風險", "總經環境穩健，可維持或提高風險資產比重，留意估值過高。",
     {"股票": 70, "債券": 20, "現金": 5, "黃金/防禦": 5}),
    (40, "moderate-low", "中低風險", "整體仍偏正面，維持核心配置，逐步檢視高波動部位。",
     {"股票": 60, "債券": 25, "現金": 10, "黃金/防禦": 5}),
    (60, "moderate", "中度風險", "訊號分歧，建議股債平衡、分散產業，避免過度槓桿。",
     {"股票": 50, "債券": 30, "現金": 10, "黃金/防禦": 10}),
    (80, "elevated", "偏高風險", "多項指標轉弱，宜降低股票與信用風險，提高優質債券與現金。",
     {"股票": 35, "債券": 35, "現金": 20, "黃金/防禦": 10}),
    (101, "high", "高風險", "衰退或金融壓力訊號明顯，以保本為優先，嚴控部位與流動性。",
     {"股票": 20, "債券": 40, "現金": 25, "黃金/防禦": 15}),
]


# ---------------------------------------------------------------- 資料抓取

def parse_fred_csv(text: str) -> list[tuple[date, float]]:
    rows = csv.reader(io.StringIO(text))
    header = next(rows, None)
    if not header or len(header) < 2:
        raise ValueError("FRED CSV 格式不符")
    out = []
    for row in rows:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            out.append((date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue
    return out


def fetch_fred(series_id: str, start: date, retries: int = 3) -> list[tuple[date, float]]:
    url = f"{FRED_BASE_URL}/graph/fredgraph.csv?id={series_id}&cosd={start.isoformat()}"
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "macro-risk-dashboard/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = parse_fred_csv(resp.read().decode("utf-8"))
            if not data:
                raise ValueError("沒有資料")
            return data
        except Exception as err:  # noqa: BLE001 - 網路錯誤重試
            last_err = err
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"{series_id} 抓取失敗：{last_err}")


def demo_series(series_id: str, start: date, end: date) -> list[tuple[date, float]]:
    """產生看起來合理的隨機序列，只供離線測試與版面預覽。"""
    rng = random.Random(series_id)
    freq = RAW_SERIES[series_id][1]
    base, vol, lo, hi, trend = {
        "T10Y3M": (0.5, 0.04, -1.8, 3.5, 0), "T10Y2Y": (0.4, 0.03, -1.1, 2.8, 0),
        "BAMLH0A0HYM2": (3.8, 0.05, 2.6, 9, 0), "VIXCLS": (18, 0.9, 11, 45, 0),
        "NFCI": (-0.4, 0.03, -0.7, 0.8, 0), "ICSA": (230000, 6000, 180000, 400000, 0),
        "UNRATE": (4.0, 0.08, 3.4, 6.5, 0), "CPIAUCSL": (280, 0.3, 0, 1e9, 0.75),
        "PCEPILFE": (115, 0.12, 0, 1e9, 0.24), "DFF": (4.0, 0.03, 0.05, 5.5, 0),
        "DGS10": (4.0, 0.05, 1.5, 5.2, 0), "A191RL1Q225SBEA": (2.2, 1.2, -3, 6, 0),
        "INDPRO": (102, 0.35, 90, 110, 0.03), "UMCSENT": (68, 2.5, 50, 100, 0),
        "DTWEXBGS": (120, 0.3, 100, 135, 0),
    }[series_id]
    months = {"monthly": 1, "quarterly": 3}.get(freq)
    out, d, v = [], start.replace(day=1) if months else start, base
    while d <= end:
        if freq == "daily" and d.weekday() >= 5:
            d += timedelta(days=1)
            continue
        if freq == "quarterly":
            v = base + rng.gauss(0, vol)
        else:
            v += trend + rng.gauss(0, vol) + (base - v) * 0.01
        v = min(max(v, lo), hi)
        out.append((d, round(v, 3)))
        if months:
            m = d.month - 1 + months
            d = d.replace(year=d.year + m // 12, month=m % 12 + 1)
        else:
            d += timedelta(days=1 if freq == "daily" else 7)
    return out


# ---------------------------------------------------------------- 衍生序列

Series = list[tuple[date, float]]


def to_weekly(s: Series) -> Series:
    """日資料取每週最後一筆。"""
    out: dict[tuple[int, int], tuple[date, float]] = {}
    for d, v in s:
        out[d.isocalendar()[:2]] = (d, v)
    return sorted(out.values())


def yoy(s: Series, lag: int = 12) -> Series:
    return [(s[i][0], (s[i][1] / s[i - lag][1] - 1) * 100) for i in range(lag, len(s)) if s[i - lag][1]]


def rolling_mean(s: Series, n: int) -> Series:
    return [(s[i][0], sum(v for _, v in s[i - n + 1:i + 1]) / n) for i in range(n - 1, len(s))]


def sahm(unrate: Series) -> Series:
    avg3 = rolling_mean(unrate, 3)
    return [(avg3[i][0], avg3[i][1] - min(v for _, v in avg3[i - 12:i]))
            for i in range(12, len(avg3))]


def claims_yoy(icsa: Series) -> Series:
    return yoy(rolling_mean(icsa, 4), 52)


class AsOf:
    """查詢某日當下最新一筆觀測值。"""

    def __init__(self, s: Series):
        self.dates = [d for d, _ in s]
        self.vals = [v for _, v in s]

    def get(self, d: date):
        i = bisect.bisect_right(self.dates, d) - 1
        return (self.dates[i], self.vals[i]) if i >= 0 else (None, None)


def real_policy_rate(dff: Series, core_pce: Series) -> Series:
    pce = AsOf(yoy(core_pce))
    out = []
    for d, v in to_weekly(dff):
        _, infl = pce.get(d)
        if infl is not None:
            out.append((d, v - infl))
    return out


# ---------------------------------------------------------------- 指標定義
# score: 分段線性插值點 (指標值, 風險分數 0-100)

INDICATORS = [
    dict(key="gdp", name="實質 GDP 成長（季增年率）", category="growth", unit="%", digits=1,
         weight=1.0, source="A191RL1Q225SBEA",
         derive=lambda r: r["A191RL1Q225SBEA"],
         score=[(-2, 95), (0, 75), (1, 55), (2, 30), (3, 15), (4.5, 10)],
         note="經濟成長動能。低於 1% 代表成長失速，負值代表萎縮。"),
    dict(key="indpro", name="工業生產年增率", category="growth", unit="%", digits=1,
         weight=0.8, source="INDPRO",
         derive=lambda r: yoy(r["INDPRO"]),
         score=[(-4, 90), (-1, 65), (0, 50), (2, 25), (4, 12)],
         note="製造與能源產出，景氣循環的同時指標。"),
    dict(key="sentiment", name="密大消費者信心", category="growth", unit="", digits=1,
         weight=0.6, source="UMCSENT",
         derive=lambda r: r["UMCSENT"],
         score=[(50, 85), (60, 65), (70, 40), (85, 20), (100, 10)],
         note="消費占美國 GDP 約七成，信心低迷常領先消費放緩。"),
    dict(key="sahm", name="Sahm 衰退指標", category="labor", unit="pp", digits=2,
         weight=1.2, source="UNRATE",
         derive=lambda r: sahm(r["UNRATE"]),
         score=[(0, 10), (0.2, 30), (0.35, 60), (0.5, 90), (0.8, 100)],
         note="失業率3個月均值較過去12個月低點的升幅；≥0.5 歷來對應衰退開始。"),
    dict(key="unrate", name="失業率", category="labor", unit="%", digits=1,
         weight=0.6, source="UNRATE",
         derive=lambda r: r["UNRATE"],
         score=[(3.5, 20), (4.2, 35), (5, 60), (6, 85), (7.5, 100)],
         note="勞動市場鬆緊程度。"),
    dict(key="claims", name="初領失業金（4週均值年增）", category="labor", unit="%", digits=1,
         weight=1.0, source="ICSA",
         derive=lambda r: claims_yoy(r["ICSA"]),
         score=[(-10, 10), (0, 25), (10, 50), (20, 75), (30, 95)],
         note="每週公布，最即時的裁員訊號。"),
    dict(key="cpi", name="CPI 年增率", category="inflation", unit="%", digits=1,
         weight=0.8, source="CPIAUCSL",
         derive=lambda r: yoy(r["CPIAUCSL"]),
         score=[(-1, 70), (0.5, 40), (1.5, 15), (2.2, 10), (3, 40), (4, 65), (6, 95)],
         note="通膨過高壓縮實質購買力並迫使升息；過低則有通縮風險。"),
    dict(key="core_pce", name="核心 PCE 年增率", category="inflation", unit="%", digits=1,
         weight=1.0, source="PCEPILFE",
         derive=lambda r: yoy(r["PCEPILFE"]),
         score=[(0.5, 50), (1.5, 20), (2.1, 10), (2.8, 40), (3.5, 65), (5, 95)],
         note="聯準會最重視的通膨指標，目標 2%。"),
    dict(key="real_rate", name="實質政策利率", category="inflation", unit="%", digits=2,
         weight=1.0, source="DFF − 核心PCE",
         derive=lambda r: real_policy_rate(r["DFF"], r["PCEPILFE"]),
         score=[(-2, 20), (0, 25), (1, 40), (2, 60), (3, 80), (4, 95)],
         note="聯邦基金利率減核心通膨；越高代表貨幣政策越緊縮。"),
    dict(key="curve_3m", name="殖利率曲線 10Y−3M", category="market", unit="pp", digits=2,
         weight=1.2, source="T10Y3M",
         derive=lambda r: to_weekly(r["T10Y3M"]),
         score=[(-1, 90), (-0.3, 75), (0, 60), (0.5, 35), (1.5, 15), (2.5, 10)],
         note="倒掛（<0）是最可靠的衰退領先指標之一，常領先 6–18 個月。"),
    dict(key="curve_2y", name="殖利率曲線 10Y−2Y", category="market", unit="pp", digits=2,
         weight=0.6, source="T10Y2Y",
         derive=lambda r: to_weekly(r["T10Y2Y"]),
         score=[(-0.8, 85), (0, 55), (0.5, 35), (1.5, 15)],
         note="市場對中長期景氣與政策路徑的預期。"),
    dict(key="hy_oas", name="高收益債利差", category="market", unit="%", digits=2,
         weight=1.2, source="BAMLH0A0HYM2",
         derive=lambda r: to_weekly(r["BAMLH0A0HYM2"]),
         score=[(2.8, 15), (3.5, 25), (4.5, 45), (5.5, 65), (7, 85), (9, 100)],
         note="企業信用風險溫度計；快速擴大代表市場避險。"),
    dict(key="vix", name="VIX 波動率", category="market", unit="", digits=1,
         weight=1.0, source="VIXCLS",
         derive=lambda r: to_weekly(r["VIXCLS"]),
         score=[(12, 10), (15, 20), (20, 45), (25, 65), (30, 80), (40, 100)],
         note="股市隱含波動度，俗稱恐慌指數。"),
    dict(key="nfci", name="金融狀況指數 NFCI", category="market", unit="", digits=2,
         weight=1.0, source="NFCI",
         derive=lambda r: r["NFCI"],
         score=[(-0.6, 10), (-0.4, 25), (-0.2, 40), (0, 60), (0.5, 90)],
         note="綜合 105 項金融指標；>0 代表金融狀況比平均緊縮。"),
]

# 只顯示、不納入評分的參考指標
REFERENCE = [
    dict(key="fed_funds", name="聯邦基金利率", unit="%", digits=2, source="DFF",
         derive=lambda r: to_weekly(r["DFF"])),
    dict(key="ust10", name="10年期美債殖利率", unit="%", digits=2, source="DGS10",
         derive=lambda r: to_weekly(r["DGS10"])),
    dict(key="usd", name="美元廣義指數", unit="", digits=1, source="DTWEXBGS",
         derive=lambda r: to_weekly(r["DTWEXBGS"])),
]


def interp(x: float, pts: list[tuple[float, float]]) -> float:
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def level_of(score: float) -> dict:
    for cap, key, name, posture, alloc in LEVELS:
        if score < cap:
            return dict(key=key, name=name, posture=posture, allocation=alloc)
    raise AssertionError


def r(x, n=2):
    return None if x is None or math.isnan(x) else round(x, n)


# ---------------------------------------------------------------- 評分

def composite_at(derived: dict, d: date) -> tuple[float | None, dict, dict]:
    """回傳 (綜合分數, 類別分數, 指標分數)，只用 d 當天已有的最新觀測。"""
    ind_scores = {}
    for ind in INDICATORS:
        s = derived.get(ind["key"])
        if s is None:
            continue
        obs_date, v = s.get(d)
        # 過舊的資料（> 200 天）視為缺值，避免早期回溯時誤用
        if v is None or (d - obs_date).days > 200:
            continue
        ind_scores[ind["key"]] = interp(v, ind["score"])

    cat_scores = {}
    for ck in CATEGORIES:
        members = [i for i in INDICATORS if i["category"] == ck and i["key"] in ind_scores]
        w = sum(i["weight"] for i in members)
        if w:
            cat_scores[ck] = sum(ind_scores[i["key"]] * i["weight"] for i in members) / w

    w = sum(CATEGORIES[c]["weight"] for c in cat_scores)
    total = sum(cat_scores[c] * CATEGORIES[c]["weight"] for c in cat_scores) / w if w else None
    return total, cat_scores, ind_scores


def build(raw: dict[str, Series], errors: dict[str, str], demo: bool) -> dict:
    today = date.today()
    derived_series: dict[str, Series] = {}
    for ind in INDICATORS + REFERENCE:
        try:
            s = ind["derive"](raw)
            if s:
                derived_series[ind["key"]] = s
        except KeyError:
            pass  # 原始序列抓取失敗
    asof = {k: AsOf(s) for k, s in derived_series.items()}

    # 每週五為一個評分點
    last_friday = today - timedelta(days=(today.weekday() - 4) % 7)
    weeks = []
    d = last_friday - timedelta(weeks=52 * HISTORY_YEARS)
    while d <= last_friday:
        weeks.append(d)
        d += timedelta(weeks=1)
    if weeks[-1] != today:
        weeks.append(today)

    history = []
    for d in weeks:
        total, cats, _ = composite_at(asof, d)
        if total is not None:
            history.append({"date": d.isoformat(), "score": r(total, 1),
                            **{c: r(v, 1) for c, v in cats.items()}})

    total, cats, ind_scores = composite_at(asof, today)
    if total is None:
        raise RuntimeError("沒有足夠資料計算風險分數")
    _, _, ind_prev = composite_at(asof, today - timedelta(weeks=4))
    prev_week = composite_at(asof, today - timedelta(weeks=1))[0]
    prev_month = composite_at(asof, today - timedelta(weeks=4))[0]

    spark_start = today - timedelta(days=365 * SPARK_YEARS)

    def pack(ind, scored: bool):
        s = derived_series.get(ind["key"])
        base = dict(key=ind["key"], name=ind["name"], unit=ind["unit"], digits=ind["digits"],
                    source=ind["source"])
        if scored:
            base.update(category=ind["category"], weight=ind["weight"], note=ind["note"],
                        thresholds=ind["score"])
        if not s:
            base.update(available=False)
            return base
        obs_date, v = s[-1]
        prev = asof[ind["key"]].get(today - timedelta(weeks=4))[1]
        base.update(available=True, value=r(v, 3), date=obs_date.isoformat(),
                    change_4w=r(v - prev, 3) if prev is not None else None,
                    series=[[dd.isoformat(), r(vv, 3)] for dd, vv in s if dd >= spark_start])
        if scored:
            sc = ind_scores.get(ind["key"])
            base.update(score=r(sc, 1),
                        score_change_4w=r(sc - ind_prev[ind["key"]], 1)
                        if sc is not None and ind["key"] in ind_prev else None,
                        stale=ind["key"] not in ind_scores)
        return base

    indicators = [pack(i, True) for i in INDICATORS]
    level = level_of(total)

    # 自動摘要
    scored = [i for i in indicators if i.get("score") is not None]
    contrib = sorted(scored, key=lambda i: i["score"] * i["weight"] * CATEGORIES[i["category"]]["weight"],
                     reverse=True)
    movers = sorted([i for i in scored if i.get("score_change_4w") is not None],
                    key=lambda i: i["score_change_4w"])
    summary = [f"綜合風險分數 {total:.0f} / 100，屬於「{level['name']}」。"]
    if prev_week is not None:
        diff = total - prev_week
        summary.append("與上週持平。" if abs(diff) < 0.5 else
                       f"較上週{'上升' if diff > 0 else '下降'} {abs(diff):.1f} 分。")
    summary.append("主要風險來源：" + "、".join(f"{i['name']}（{i['score']:.0f}）" for i in contrib[:3]) + "。")
    worse = [i for i in movers[::-1] if i["score_change_4w"] >= 5][:2]
    better = [i for i in movers if i["score_change_4w"] <= -5][:2]
    if worse:
        summary.append("近 4 週轉弱：" + "、".join(i["name"] for i in worse) + "。")
    if better:
        summary.append("近 4 週改善：" + "、".join(i["name"] for i in better) + "。")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "demo": demo,
        "source": "FRED, Federal Reserve Bank of St. Louis",
        "risk": {
            "score": r(total, 1),
            "change_1w": r(total - prev_week, 1) if prev_week is not None else None,
            "change_4w": r(total - prev_month, 1) if prev_month is not None else None,
            "level": level,
            "summary": summary,
            "categories": [dict(key=c, name=CATEGORIES[c]["name"], weight=CATEGORIES[c]["weight"],
                                score=r(cats.get(c), 1)) for c in CATEGORIES],
        },
        "levels": [dict(max=cap if cap <= 100 else 100, key=k, name=n) for cap, k, n, _, _ in LEVELS],
        "history": history,
        "indicators": indicators,
        "reference": [pack(i, False) for i in REFERENCE],
        "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="產生示範資料，不連網")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()

    start = date.today() - timedelta(days=365 * FETCH_YEARS)
    raw, errors = {}, {}
    for sid in RAW_SERIES:
        try:
            raw[sid] = demo_series(sid, start, date.today()) if args.demo else fetch_fred(sid, start)
            print(f"  ✓ {sid:<18} {len(raw[sid]):>5} 筆，最新 {raw[sid][-1][0]}")
        except Exception as err:  # noqa: BLE001
            errors[sid] = str(err)
            print(f"  ✗ {sid:<18} {err}", file=sys.stderr)

    if len(errors) > len(RAW_SERIES) // 2:
        print("失敗的序列過多，保留既有資料不覆寫。", file=sys.stderr)
        return 1

    data = build(raw, errors, args.demo)
    os.makedirs(args.out, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(args.out, "macro.json"), "w", encoding="utf-8") as f:
        f.write(payload)
    with open(os.path.join(args.out, "macro.js"), "w", encoding="utf-8") as f:
        f.write("window.MACRO_DATA = " + payload + ";\n")
    rk = data["risk"]
    print(f"綜合風險分數 {rk['score']}（{rk['level']['name']}），已寫入 {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
