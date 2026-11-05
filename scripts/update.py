# -*- coding: utf-8 -*-
"""黃金錢荒儀表板：抓資料 → 套門檻 → 寫 data/data.json → 狀態變化推 Telegram。
只用標準庫，本機與 GitHub Actions 皆可直接跑：  py scripts/update.py
環境變數（選填）：TG_BOT_TOKEN 或 TG_ENV_FILE、TG_CHAT_ID、DASHBOARD_URL、DAILY=1（每天固定推日報）、FORCE_DIGEST=1
"""
import csv, html, io, json, os, re, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "data.json")
STATE = os.path.join(ROOT, "data", "state.json")
UA = {"User-Agent": "Mozilla/5.0 (gold-liquidity-dashboard)"}
START = (datetime.now(timezone.utc) - timedelta(days=420)).strftime("%Y-%m-%d")


def get(url, tries=3, deadline=60):
    """每次請求有「總時限」：urllib 的 timeout 只管單次讀取，遇到對方極慢地吐資料（tarpit）會無限拖住。"""
    for i in range(tries):
        try:
            t0 = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=min(20, deadline)) as r:
                buf = []
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    buf.append(chunk)
                    if time.time() - t0 > deadline:
                        raise TimeoutError(f"超過總時限 {deadline}s")
                return b"".join(buf).decode("utf-8")
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


FRED_DOWN = False  # 斷路器：本輪 FRED 失敗一次就不再嘗試，直接走備援


def fred(sid):
    global FRED_DOWN
    if FRED_DOWN:
        raise ConnectionError("FRED 本輪已判定不可用")
    try:
        txt = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}", tries=2, deadline=25)
    except Exception:
        FRED_DOWN = True
        raise
    out = []
    for row in csv.reader(io.StringIO(txt)):
        if len(row) < 2 or row[0][:2] != "20":
            continue
        try:
            out.append([row[0], float(row[1])])
        except ValueError:
            pass  # 假日的 "." 空值
    return out


# ── 備援來源：FRED 失敗時改抓原始發布單位，單位換成與 FRED 相同 ──
NYF = "https://markets.newyorkfed.org/api"
_NY = {}


def _nyrate(path):
    if path not in _NY:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _NY[path] = json.loads(get(f"{NYF}/rates/{path}/search.json?startDate={START}&endDate={end}"))["refRates"]
    return _NY[path]


def _nyrp(kind):  # 逆回購（Reverse Repo）／常備回購 SRF（Repo）每日承作額，十億美元
    if "rp" not in _NY:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _NY["rp"] = json.loads(get(f"{NYF}/rp/results/search.json?startDate={START}&endDate={end}"))["repo"]["operations"]
    tot = {}
    for o in _NY["rp"]:
        if o["operationType"] != kind:
            continue
        amt = sum(x.get("amtAccepted", 0) for x in o.get("details", []) if x.get("securityType") == "Treasury")  # 同 FRED：只計公債擔保
        tot[o["operationDate"]] = tot.get(o["operationDate"], 0) + amt / 1e9
    return [[d, round(v, 3)] for d, v in sorted(tot.items())]


def _tips10():
    out = []
    for y in range(int(START[:4]), datetime.now(timezone.utc).year + 1):
        txt = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                  f"{y}/all?type=daily_treasury_real_yield_curve&field_tdr_date_value={y}")
        for row in csv.DictReader(io.StringIO(txt)):
            m, d, yy = row["Date"].split("/")
            if row.get("10 YR"):
                out.append([f"{yy}-{m}-{d}", float(row["10 YR"])])
    return sorted(x for x in out if x[0] >= START)


def _soma_bills():  # 百萬美元（同 FRED WSHOBL）
    rows = json.loads(get(f"{NYF}/soma/summary.json"))["soma"]["summary"]
    return [[r["asOfDate"], float(r["bills"]) / 1e6] for r in rows if r["asOfDate"] >= START]


ALT = {
    "SOFR": lambda: [[r["effectiveDate"], r["percentRate"]] for r in _nyrate("secured/sofr")][::-1],
    "SOFR99": lambda: [[r["effectiveDate"], r["percentPercentile99"]] for r in _nyrate("secured/sofr")][::-1],
    "DFEDTARU": lambda: [[r["effectiveDate"], r["targetRateTo"]] for r in _nyrate("unsecured/effr")][::-1],
    # IORB = 目標區間上限 − 10bp（2021/6 起的技術調整）
    "IORB": lambda: [[r["effectiveDate"], round(r["targetRateTo"] - 0.10, 2)] for r in _nyrate("unsecured/effr")][::-1],
    "RRPONTSYD": lambda: _nyrp("Reverse Repo"),
    "RPONTSYD": lambda: _nyrp("Repo"),
    "WSHOBL": _soma_bills,
    "DFII10": _tips10,
}
CACHE = os.path.join(ROOT, "data", "cache.json")
WEEKLY = {"WRESBAL", "WTREGEN", "WSHOBL"}


def series(sid, errs, cache, used):
    """FRED → 原始發布單位 → 上次成功的快取。三層都失敗才回空。"""
    for name, fn in (("FRED", lambda: fred(sid)), ("備援", ALT.get(sid))):
        if not fn:
            continue
        try:
            rows = sorted(fn())
            if rows:
                cache[sid] = rows
                used[sid] = name
                return rows
        except Exception as e:
            errs.append(f"{sid} {name}: {str(e)[:80]}")
    if cache.get(sid):
        used[sid] = "快取"
        return cache[sid]
    used[sid] = "無"
    return []


YH = {}  # 盤中最高價（算歷史高點用，與影片口徑一致）


def yahoo(sym):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=2y&interval=1d"))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for t, c, h in zip(r["timestamp"], q["close"], q["high"]):
        if c is not None:
            out.append([datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), round(c, 2)])
            if h is not None:
                YH[sym] = max(YH.get(sym, 0), h)
    return out


def cot_gold():
    q = urllib.parse.urlencode({
        "cftc_contract_market_code": "088691",
        "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "60",
        "$select": "report_date_as_yyyy_mm_dd,open_interest_all,noncomm_positions_long_all,noncomm_positions_short_all"})
    rows = json.loads(get("https://publicreporting.cftc.gov/resource/6dca-aqww.json?" + q))
    out = []
    for r in reversed(rows):
        oi = float(r["open_interest_all"])
        net = float(r["noncomm_positions_long_all"]) - float(r["noncomm_positions_short_all"])
        out.append([r["report_date_as_yyyy_mm_dd"][:10], round(net / oi * 100, 1), int(oi)])
    return out


def tga_daily():
    q = "sort=-record_date&page%5Bsize%5D=400&fields=record_date,account_type,open_today_bal&filter=account_type:eq:Treasury%20General%20Account%20(TGA)%20Opening%20Balance"
    rows = json.loads(get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?" + q))["data"]
    return [[r["record_date"], round(float(r["open_today_bal"]) / 1000, 1)] for r in reversed(rows)]  # 十億美元


def asof(series, d):
    """回傳 series 中日期 <= d 的最後一筆值"""
    v = None
    for dd, x in series:
        if dd > d:
            break
        v = x
    return v


def level(v, rules):
    """rules: [(條件函式, 'green'|'yellow'|'red', 說明)] 依序判斷"""
    for fn, lv, why in rules:
        if fn(v):
            return lv, why
    return "gray", "無資料"


def main():
    errs = []
    def safe(name, fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            errs.append(f"{name}: {e}")
            return []

    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    used = {}
    s = {k: series(k, errs, cache, used) for k in ["SOFR", "SOFR99", "IORB", "DFEDTARU", "RRPONTSYD", "WRESBAL", "WTREGEN", "DFII10", "RPONTSYD", "WSHOBL"]}
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))
    # 停更偵測：日資料超過 6 天、週資料超過 13 天沒有新值
    today = datetime.now(timezone.utc).date()
    stale = [k for k, v in s.items() if not v or
             (today - datetime.strptime(v[-1][0], "%Y-%m-%d").date()).days > (13 if k in WEEKLY else 6)]
    gold = safe("GC=F", yahoo, "GC=F")
    dxy = safe("DXY", yahoo, "DX-Y.NYB")
    gld = safe("GLD", yahoo, "GLD")
    cot = safe("COT", cot_gold)
    tga = safe("TGA_DTS", tga_daily)

    ind = []  # 指標清單

    def last(x):
        return x[-1] if x else [None, None]

    # ── ① 回購壓力 ─────────────────────────────
    spread = [[d, round((v - asof(s["IORB"], d)) * 100, 1)] for d, v in s["SOFR"] if asof(s["IORB"], d) is not None]
    d, v = last(spread)
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x <= 0, "green", "SOFR 不高於 IORB：銀行有閒錢，回購水管鬆"),
                        (lambda x: x <= 5, "yellow", "SOFR 高於 IORB 0–5bp：回購開始要搶錢"),
                        (lambda x: True, "red", "SOFR 高於 IORB 超過 5bp：回購缺錢，影片所說的『錢荒』狀態")])
    ind.append(dict(id="spread", th=[0, 5], group="repo", name="資金利差 SOFR − IORB", unit="bp", date=d, value=v, level=lv, why=why,
                    rule="≤0 綠｜0~5 黃｜>5 紅", src="FRED SOFR / IORB", series=spread[-90:]))

    tail = [[d, round((v - asof(s["DFEDTARU"], d)) * 100, 1)] for d, v in s["SOFR99"] if asof(s["DFEDTARU"], d) is not None]
    d, v = last(tail)
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x < -5, "green", "尾部成交仍低於 SRF 天花板 5bp 以上"),
                        (lambda x: x <= 0, "yellow", "尾部成交逼近 SRF 天花板"),
                        (lambda x: True, "red", "第 99 百分位成交『高於』SRF 利率：有人寧可付更貴也不去聯儲窗口")])
    ind.append(dict(id="tail", th=[-5, 0], group="repo", name="尾部利率 SOFR99 − SRF", unit="bp", date=d, value=v, level=lv, why=why,
                    rule="<−5 綠｜−5~0 黃｜>0 紅", src="FRED SOFR99 / DFEDTARU（SRF＝目標區間上限）", series=tail[-90:]))

    d, v = last(s["RPONTSYD"])
    tail_red = ind[-1]["level"] == "red"
    if v is None:
        lv, why = "gray", "無資料"
    elif v >= 10:
        lv, why = "red", "常備回購（SRF）被大量使用：銀行間借不到錢"
    elif v > 0:
        lv, why = "yellow", "SRF 出現使用量"
    elif tail_red:
        lv, why = "yellow", "用量為 0 但尾部利率已破天花板：窗口污名化，壓力藏在場外（影片 10/27 情境）"
    else:
        lv, why = "green", "SRF 無使用，且尾部未破天花板"
    ind.append(dict(id="srf", th=[0, 10], group="repo", name="SRF 常備回購用量", unit="十億美元", date=d, value=v, level=lv, why=why,
                    rule="0 綠（尾部破頂時降為黃）｜>0 黃｜≥10 紅", src="FRED RPONTSYD", series=s["RPONTSYD"][-90:]))

    # ── ② 水管存量 ─────────────────────────────
    d, v = last(s["RRPONTSYD"])
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x >= 2000, "green", "逆回購 ≥ 2 兆：影片定義的『水管最鬆』"),
                        (lambda x: x >= 100, "yellow", "逆回購緩衝在消耗"),
                        (lambda x: True, "red", "逆回購 < 1000 億：緩衝墊已抽乾，衝擊會直接打到準備金")])
    ind.append(dict(id="rrp", th=[100, 2000], group="pipe", name="隔夜逆回購 ON RRP", unit="十億美元", date=d, value=v, level=lv, why=why,
                    rule="≥2000 綠｜100~2000 黃｜<100 紅", src="FRED RRPONTSYD", series=s["RRPONTSYD"][-90:]))

    res = [[d, round(v / 1e6, 3)] for d, v in s["WRESBAL"]]
    d, v = last(res)
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x >= 3.5, "green", "準備金 ≥ 3.5 兆：影片定義的『極度充裕』"),
                        (lambda x: x >= 3.0, "yellow", "準備金 3.0–3.5 兆：充足下緣"),
                        (lambda x: True, "red", "準備金 < 3 兆：進入稀缺區，回購利率易飆")])
    ind.append(dict(id="reserves", th=[3.0, 3.5], group="pipe", name="銀行準備金", unit="兆美元", date=d, value=v, level=lv, why=why,
                    rule="≥3.5 綠｜3.0~3.5 黃｜<3.0 紅", src="FRED WRESBAL（週）", series=res[-60:]))

    d, v = last(tga)
    chg = None
    if tga:
        ref = asof(tga, (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=28)).strftime("%Y-%m-%d"))
        chg = round(v - ref, 1) if ref is not None else None
    lv, why = level(chg, [(lambda x: x is None, "gray", "無資料"),
                          (lambda x: x <= 0, "green", "TGA 四週淨流出：財政部在『放水』回銀行體系"),
                          (lambda x: x <= 100, "yellow", "TGA 四週增加 ≤ 1000 億：輕微抽水"),
                          (lambda x: True, "red", "TGA 四週增加 > 1000 億：財政部在抽走準備金")])
    ind.append(dict(id="tga", sunit="十億美元（餘額）", th=[1000, 1050], group="pipe", name="財政部 TGA（四週變化）", unit="十億美元", date=d, value=chg, level=lv, why=why,
                    extra=f"餘額 {v * 10:,.0f} 億，距年底目標 8,500 億還要放 {(v - 850) * 10:,.0f} 億" if v else "",
                    rule="≤0 綠｜0~100 黃｜>100 紅", src="財政部 DTS 每日報表", series=tga[-90:]))

    bills = [[d, round(v / 1000, 1)] for d, v in s["WSHOBL"]]
    d, v = last(bills)
    rmp = None
    if bills:
        ref = asof(bills, (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=28)).strftime("%Y-%m-%d"))
        rmp = round(v - ref, 1) if ref is not None else None
    lv, why = level(rmp, [(lambda x: x is None, "gray", "無資料"),
                          (lambda x: x >= 20, "green", "聯儲四週增持短債 ≥ 200 億：RMP 已重啟（影片預期 200 億/月）"),
                          (lambda x: x > 2, "yellow", "有小幅增持，未達 RMP 節奏"),
                          (lambda x: True, "red", "短債持有不增：RMP 仍暫停")])
    ind.append(dict(id="rmp", sunit="十億美元（持有量）", group="pipe", name="RMP 準備金管理購買", unit="十億美元/4週", date=d, value=rmp, level=lv, why=why,
                    extra=f"聯儲持有短債 {v:,.0f} 十億" if v else "",
                    rule="≥20 綠｜2~20 黃｜≤2 紅", src="FRED WSHOBL（週）", series=bills[-60:]))

    # ── ③ 黃金 ─────────────────────────────────
    d, v = last(s["DFII10"])
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x <= 1.5, "green", "實際利率低：持有黃金機會成本低"),
                        (lambda x: x <= 2.5, "yellow", "實際利率中性"),
                        (lambda x: True, "red", "實際利率 > 2.5%：持金機會成本高（影片：要壓回負值才是長多燃料）")])
    ind.append(dict(id="tips", th=[1.5, 2.5], group="gold", name="10 年期實際利率 TIPS", unit="%", date=d, value=v, level=lv, why=why,
                    rule="≤1.5 綠｜1.5~2.5 黃｜>2.5 紅", src="FRED DFII10", series=s["DFII10"][-90:]))

    # 殘差模型（影片 10/30 瀑布圖）：實際利率每降 1bp → +$4；美元指數每降 1 點 → +$38
    B_TIPS, B_DXY = 4.0, 38.0
    resid = []
    for i in range(1, len(gold)):
        d0, g0 = gold[i - 1]; d1, g1 = gold[i]
        t0, t1 = asof(s["DFII10"], d0), asof(s["DFII10"], d1)
        x0, x1 = asof(dxy, d0), asof(dxy, d1)
        if None in (t0, t1, x0, x1):
            continue
        model = -B_TIPS * (t1 - t0) * 100 - B_DXY * (x1 - x0)
        resid.append([d1, round((g1 - g0) - model, 1), round(model, 1), round(g1 - g0, 1)])
    d, v = (resid[-1][0], resid[-1][1]) if resid else (None, None)
    r5 = round(sum(r[1] for r in resid[-5:]), 1) if resid else None
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x > -50, "green", "金價走勢與利率/美元因子相符"),
                        (lambda x: x > -100, "yellow", "金價比因子模型多跌 $50–100：出現非基本面賣壓"),
                        (lambda x: True, "red", "金價比因子模型多跌 > $100：流動性拋售（影片 10/30 殘差 −$166）")])
    ind.append(dict(id="resid", th=[-100, -50], group="gold", name="金價殘差（實盤 − 因子模型）", unit="美元/盎司", date=d, value=v, level=lv, why=why,
                    extra=f"近 5 日累計殘差 {r5:+,.0f}" if r5 is not None else "",
                    rule=">−50 綠｜−100~−50 黃｜<−100 紅", src="Yahoo GC=F / DX-Y.NYB、FRED DFII10",
                    series=[[r[0], r[1]] for r in resid[-90:]]))

    d, v = last(gold)
    ath = YH.get("GC=F") or (max(g for _, g in gold) if gold else None)
    dd = round((v / ath - 1) * 100, 1) if gold else None
    lv, why = level(dd, [(lambda x: x is None, "gray", "無資料"),
                         (lambda x: x > -13.6, "green", "回撤小於 2020 年錢荒（−13.6%）"),
                         (lambda x: x > -29.6, "yellow", "回撤介於 2020（−13.6%）與 2008（−29.6%）錢荒之間"),
                         (lambda x: True, "red", "回撤超過 2008 錢荒（−29.6%），逼近 1975–76（−47.2%）")])
    ind.append(dict(id="drawdown", sunit="美元（期金收盤）", group="gold", name="金價距高點回撤", unit="%", date=d, value=dd, level=lv, why=why,
                    extra=f"期金 {v:,.0f}／兩年盤中高點 {ath:,.0f}" if gold else "",
                    rule=">−13.6 綠｜−29.6~−13.6 黃｜<−29.6 紅（三次歷史錢荒刻度）", src="Yahoo GC=F（COMEX 期金連續合約）",
                    series=gold[-120:]))

    # 講者每天盯的第三件事：GLD 先收復 369（Max Pain）、再站上 373（Gamma 翻轉）——取自 10/30 期權鏈
    GLD_A, GLD_B = 369, 373
    d, v = last(gld)
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x >= GLD_B, "green", f"站上 {GLD_B}：造市商避險轉為推升，反轉成立"),
                        (lambda x: x >= GLD_A, "yellow", f"已收復 {GLD_A}，尚未站上 {GLD_B}"),
                        (lambda x: True, "red", f"仍在 {GLD_A} 之下，造市商避險仍在壓價")])
    ind.append(dict(id="gld", group="gold", name="GLD 收復關卡", unit="美元", date=d, value=v, level=lv, why=why,
                    th=[GLD_A, GLD_B], rule=f"≥{GLD_B} 綠｜{GLD_A}~{GLD_B} 黃｜<{GLD_A} 紅（影片 10/30 期權鏈）",
                    src="Yahoo GLD（收盤）", series=gld[-120:]))

    d, v = (cot[-1][0], cot[-1][1]) if cot else (None, None)
    lv, why = level(v, [(lambda x: x is None, "gray", "無資料"),
                        (lambda x: x < 40, "green", "投機淨多 < 未平倉 40%：籌碼乾淨，底部條件之一"),
                        (lambda x: x <= 55, "yellow", "投機淨多 40–55%：在出清中（影片：9 月 60% → 47%）"),
                        (lambda x: True, "red", "投機淨多 > 55%：籌碼擁擠，易再被洗")])
    ind.append(dict(id="cot", th=[40, 55], group="gold", name="COMEX 投機淨多 / 未平倉", unit="%", date=d, value=v, level=lv, why=why,
                    extra=f"未平倉 {cot[-1][2]:,} 口" if cot else "",
                    rule="<40 綠｜40~55 黃｜>55 紅", src="CFTC 期貨持倉報告（週）", series=[[c[0], c[1]] for c in cot]))

    # ── 量尺規格（頁面畫門檻量尺用；分區與上方判讀門檻一致）──
    G, Y_, R = "green", "yellow", "red"
    GAUGE = {
        "spread":   dict(q="借隔夜美元，比放在聯儲貴多少？", min=-10, max=15, zones=[[-10, 0, G], [0, 5, Y_], [5, 15, R]]),
        "tail":     dict(q="最急著借錢的人，付的價格破天花板了嗎？", min=-20, max=15, zones=[[-20, -5, G], [-5, 0, Y_], [0, 15, R]]),
        "srf":      dict(q="有人去聯儲的緊急窗口借錢嗎？", min=0, max=20, zones=[[0, 0.5, G], [0.5, 10, Y_], [10, 20, R]]),
        "rrp":      dict(q="市場上的閒錢緩衝還剩多少？", min=1, max=3000, log=True, zones=[[1, 100, R], [100, 2000, Y_], [2000, 3000, G]], ticks=[[100, "1000億"], [2000, "2兆"]]),
        "reserves": dict(q="銀行的準備金夠不夠？", min=2.5, max=4.0, zones=[[2.5, 3.0, R], [3.0, 3.5, Y_], [3.5, 4.0, G]]),
        "tga":      dict(q="財政部在抽水還是放水？", min=-200, max=250, zones=[[-200, 0, G], [0, 100, Y_], [100, 250, R]]),
        "rmp":      dict(q="聯儲開始買短債補錢了嗎？", min=-10, max=50, zones=[[-10, 2, R], [2, 20, Y_], [20, 50, G]]),
        "tips":     dict(q="持有黃金的機會成本高不高？", min=0, max=3.5, zones=[[0, 1.5, G], [1.5, 2.5, Y_], [2.5, 3.5, R]]),
        "resid":    dict(q="金價今天的跌幅，利率和美元解釋得了嗎？", min=-200, max=150, zones=[[-200, -100, R], [-100, -50, Y_], [-50, 150, G]]),
        "drawdown": dict(q="這次洗盤跌到歷史哪一級？", min=-50, max=0, zones=[[-50, -29.6, R], [-29.6, -13.6, Y_], [-13.6, 0, G]],
                         ticks=[[-47.2, "1976"], [-29.6, "2008"], [-13.6, "2020"]]),
        "gld":      dict(q="黃金收復關卡了嗎？", min=355, max=385, zones=[[355, 369, R], [369, 373, Y_], [373, 385, G]], ticks=[[369, "369"], [373, "373"]]),
        "cot":      dict(q="投機多單洗乾淨了嗎？", min=20, max=70, zones=[[20, 40, G], [40, 55, Y_], [55, 70, R]]),
    }
    for i in ind:
        i["gauge"] = GAUGE.get(i["id"])

    # ── 總結 ──────────────────────────────────
    stress = sum(1 for i in ind if i["group"] in ("repo", "pipe") and i["level"] == "red")
    by = {i["id"]: i for i in ind}
    val = lambda k: by[k]["value"]
    last3 = [x[1] for x in spread[-3:]]
    tga_chg = val("tga")
    alerts = [
        dict(id="crunch_up", kind="bad", name="錢荒加劇",
             rule="SOFR−IORB 超過 5bp，且尾部利率衝破 SRF 天花板",
             on=bool(val("spread") is not None and val("spread") > 5 and val("tail") is not None and val("tail") > 0),
             now=f"利差 {val('spread'):+.1f}bp、尾部 {val('tail'):+.1f}bp" if val("spread") is not None and val("tail") is not None else "—"),
        dict(id="crunch_end", kind="good", name="錢荒解除",
             rule="SOFR−IORB 連續 3 個交易日 ≤ 0",
             on=bool(len(last3) == 3 and all(x <= 0 for x in last3)),
             now="近 3 日 " + "、".join(f"{x:+.0f}" for x in last3) + " bp"),
        dict(id="refill", kind="good", name="補水啟動",
             rule="RMP 四週增持 ≥ 200 億美元，或 TGA 四週減少 ≥ 500 億美元",
             on=bool((val("rmp") or 0) >= 20 or (tga_chg is not None and tga_chg <= -50)),
             now=f"RMP {(val('rmp') or 0) * 10:+.0f} 億、TGA {(tga_chg or 0) * 10:+.0f} 億"),
        dict(id="gld369", kind="good", name="GLD 收復 369",
             rule="GLD 收盤 ≥ 369（10/30 期權鏈 Max Pain）",
             on=bool(val("gld") is not None and val("gld") >= 369),
             now=f"GLD 收盤 {val('gld'):.2f}" if val("gld") is not None else "—"),
        dict(id="gld373", kind="good", name="GLD 站上 373",
             rule="GLD 收盤 ≥ 373（Gamma 翻轉位）",
             on=bool(val("gld") is not None and val("gld") >= 373),
             now=f"GLD 收盤 {val('gld'):.2f}" if val("gld") is not None else "—"),
        dict(id="dump", kind="bad", name="黃金被錯殺",
             rule="單日金價比利率／美元模型多跌超過 $100",
             on=bool(val("resid") is not None and val("resid") <= -100),
             now=f"今日殘差 {val('resid'):+.0f} 美元" if val("resid") is not None else "—"),
        dict(id="clean", kind="good", name="籌碼洗乾淨",
             rule="COMEX 投機淨多低於未平倉的 40%",
             on=bool(val("cot") is not None and val("cot") < 40),
             now=f"目前 {val('cot'):.0f}%" if val("cot") is not None else "—"),
    ]
    st = {a["id"]: a["on"] for a in alerts}
    phase = 3 if st["crunch_end"] else 2 if st["refill"] else 1
    regime = ["", "錢荒期", "補水期", "修復期"][phase]
    out = dict(updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), regime=regime, phase=phase, stress=stress,
               alerts=alerts, indicators=ind, errors=errs, sources=used, stale=stale)
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(DATA[:-2], "w", encoding="utf-8") as f:  # data.js：本機 file:// 開啟用
        f.write("window.DASH=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"[ok] {out['updated']} 階段={regime} 紅燈={stress} 警報觸發={[a['name'] for a in alerts if a['on']]} 錯誤={len(errs)}")
    for i in ind:
        print(f"  {i['level']:6} {i['name']}: {i['value']} {i['unit']}  ({i['date']})")
    for e in errs:
        print("  [err]", e)
    notify(out)
    try:  # 歷次錢荒回推＋指數日線（失敗不影響主資料）
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import history
        history.build()
    except Exception as e:
        print("  [err] history:", e)


def _token():
    """TG_BOT_TOKEN 環境變數優先；否則讀 TG_ENV_FILE 指向的 .env（TELEGRAM_BOT_TOKEN=...）。token 不落地到專案內。"""
    tok = os.environ.get("TG_BOT_TOKEN")
    path = os.environ.get("TG_ENV_FILE")
    if not tok and path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "TELEGRAM_BOT_TOKEN":
                    tok = v.strip().strip('"').strip("'")
    return tok


def _send(token, chat, text, html_mode=True):
    body = {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
    if html_mode:
        body["parse_mode"] = "HTML"
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=urllib.parse.urlencode(body).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def digest(out, old):
    """組每日訊息（HTML 模式，所有動態文字都跳脫）。"""
    E = html.escape
    by = {i["id"]: i for i in out["indicators"]}
    A = {a["id"]: a for a in out["alerts"]}
    dot = {"red": "🔴", "yellow": "🟡", "green": "🟢", "gray": "⚪"}

    def f(v, d=0, sign=False):
        return "—" if v is None else (f"{v:+,.{d}f}" if sign else f"{v:,.{d}f}")

    sp, rm, gl, tga = by["spread"], by["rmp"], by["gld"], by["tga"]
    q1 = {"red": "還在", "yellow": "緩解中", "green": "解除"}.get(sp["level"], "—")
    refill_lv = "green" if A["refill"]["on"] else ("yellow" if rm["level"] == "yellow" or tga["level"] == "green" else "red")
    q2 = {"red": "還沒", "yellow": "在路上", "green": "來了"}[refill_lv]
    q3 = {"red": "還沒", "yellow": "一半", "green": "收復"}.get(gl["level"], "—")
    bal = (tga.get("series") or [[None, None]])[-1][1]
    left = f"，TGA 距目標還要放 {f((bal - 850) * 10)} 億" if bal and bal > 850 else ""

    phase_names = ["", "錢荒期", "補水期", "修復期"]
    head = f"<b>黃金錢荒｜{E(out['regime'])}</b>"
    if "phase" in old and old["phase"] != out["phase"]:
        head += f"\n🔔 階段變化：{phase_names[old['phase']]} → {E(out['regime'])}"
    lines = [head, "",
             f"{dot[sp['level']]} ① 錢荒：<b>{q1}</b>　SOFR−IORB {f(sp['value'], 1, True)} bp",
             f"{dot[refill_lv]} ② 補水：<b>{q2}</b>　RMP {f((rm['value'] or 0) * 10, 0, True)} / 200 億{left}",
             f"{dot[gl['level']]} ③ 收復：<b>{q3}</b>　GLD {f(gl['value'], 2)}（369 / 373）"]

    flips = [a for a in out["alerts"] if a["id"] in old and old[a["id"]] != a["on"]]
    if flips:
        lines += ["", "<b>變化</b>"]
        for a in flips:
            mark = ("🟢" if a["kind"] == "good" else "🔴") if a["on"] else "⚪"
            lines.append(f"{mark} {E(a['name'])}{'觸發' if a['on'] else '解除'}：{E(a['now'])}")
    on = [a for a in out["alerts"] if a["on"]]
    lines += ["", "<b>觸發中</b>" if on else "觸發中：無"]
    for a in on:
        lines.append(f"{'🟢' if a['kind'] == 'good' else '🔴'} {E(a['name'])}：{E(a['now'])}")
    if out["stale"]:
        lines += ["", f"⚠️ 資料停更：{E('、'.join(out['stale']))}，相關燈號可能失準"]
    elif old.get("stale"):
        lines += ["", "✅ 資料源已恢復"]
    url = os.environ.get("DASHBOARD_URL")
    if url:
        lines += ["", E(url)]
    return "\n".join(lines), bool(flips) or ("phase" in old and old["phase"] != out["phase"])


def notify(out):
    """DAILY=1：每天固定推日報。未設：只在警報／階段／資料停更有變化時推（GitHub Actions 用）。"""
    old = {}
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            old = json.load(f)
    new = {"phase": out["phase"], "stale": out["stale"], **{a["id"]: a["on"] for a in out["alerts"]}}
    msg, changed = digest(out, old)
    stale_changed = sorted(old.get("stale", [])) != sorted(out["stale"])
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False)
    if not (os.environ.get("DAILY") or os.environ.get("FORCE_DIGEST") or changed or stale_changed):
        print("[tg] 警報、階段、資料狀態皆無變化，不推播")
        return
    token, chat = _token(), os.environ.get("TG_CHAT_ID")
    if not (token and chat):
        print("[tg] 未設定 token / TG_CHAT_ID，預定推播內容：\n" + msg)
        return
    try:
        print("[tg] 已推播", _send(token, chat, msg))
    except Exception as e:  # HTML 解析失敗等 → 退純文字重送，確保一定送得出去
        print("[tg] HTML 推播失敗，改純文字：", str(e)[:120])
        plain = re.sub(r"</?b>", "", msg)
        print("[tg] 已推播（純文字）", _send(token, chat, html.unescape(plain), html_mode=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 整個失敗也要通知，不靜默死掉
        tok, chat = _token(), os.environ.get("TG_CHAT_ID")
        if tok and chat:
            _send(tok, chat, f"⚠️ 黃金錢荒儀表板執行失敗：{str(e)[:300]}", html_mode=False)
        raise
