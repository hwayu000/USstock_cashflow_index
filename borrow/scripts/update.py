# -*- coding: utf-8 -*-
"""借錢成本雷達：抓資料 → 算指數與回測 → 寫 data/data.js、data.json、history.js。
方法來源：兩支節目（AI 借錢成本／輝達的債），收斂為「債市先於股市」三成分指數。
環境變數（選填）：FRED_API_KEY（ICE 利差觀察卡；沒有就略過）、TG_BOT_TOKEN 或 TG_ENV_FILE、TG_CHAT_ID、DASHBOARD_URL、DAILY=1
"""
import csv, html, io, re, json, math, os, statistics as stats, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA_DIR, "cache")
STATE = os.path.join(DATA_DIR, "state.json")
UA = {"User-Agent": "Mozilla/5.0 (borrow-cost-radar)"}
API_UA = {"User-Agent": "dashboard-bot/1.0"}
BTN_TEXT = "開借錢成本雷達"

# ── 事先宣告的參數（看回測結果前定下，之後不為好看改）──
LB = 21                  # 變化回看 21 個交易日（約一個月）
PCT_WINDOW = 1260        # 5 年百分位
PCT_MIN = 252
HORIZON = 21             # 回測：之後 21 日 SPX 最大回撤
BINS = [(0, 40, "低"), (40, 60, "中"), (60, 75, "偏高"), (75, 101, "高")]
DIVERGE_UP = 2.0         # 股漲債不跟：QQQ 單日 ≥ +2%
REPRICE_BP = 25          # 短端重估：2 年期 21 日上升 ≥ 25bp 且多於 10 年期
SETTLE_BIG = 1000        # 集中結算：單日附息債結算 ≥ 1000 億美元
CCC_STABLE = 12.15       # 節目觀測線：CCC 及以下 OAS 回到 10/1 的 12.15% 以下
STALE_DAYS = 5


def get(url, tries=3, timeout=40):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=API_UA if "stlouisfed.org" in url else UA), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def yahoo_adj(sym):
    """還原權息收盤（含配息，信用 ETF 必須用總報酬）。"""
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?period1=1104537600&period2={int(time.time())}&interval=1d"))  # range=max 會被降成月線
    r = j["chart"]["result"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for t, c in zip(r["timestamp"], adj):
        if c is not None:
            out[datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")] = c
    return out


def treasury(kind, year):
    """財政部每日殖利率（名目 par yield 或實際殖利率），過去年度快取。"""
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, f"{kind}_{year}.csv")
    this_year = datetime.now(timezone.utc).year
    if year < this_year and os.path.exists(fp):
        txt = open(fp, encoding="utf-8").read()
    else:
        txt = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                  f"{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
        if year < this_year:
            open(fp, "w", encoding="utf-8").write(txt)
    out = {}
    for row in csv.DictReader(io.StringIO(txt)):
        m, d, y = row["Date"].split("/")
        out[f"{y}-{m}-{d}"] = row
    return out


def tsy_series(kind, col, y0):
    s = {}
    for y in range(y0, datetime.now(timezone.utc).year + 1):
        for d, row in treasury(kind, y).items():
            v = row.get(col)
            if v not in (None, "", "N/A"):
                s[d] = float(v)
    return s


def settlements():
    """已標售未結算＋已公告：依結算日加總（億美元），附息債與短券分開。"""
    seen, rows = set(), []
    for ep in ("auctioned?days=21", "upcoming"):
        for x in json.loads(get(f"https://www.treasurydirect.gov/TA_WS/securities/{ep}&format=json" if "?" in ep else
                                f"https://www.treasurydirect.gov/TA_WS/securities/{ep}?format=json")):
            key = (x["cusip"], x["issueDate"][:10])
            if key in seen or not x.get("offeringAmount"):
                continue
            seen.add(key)
            rows.append(x)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by = {}
    for x in rows:
        d = x["issueDate"][:10]
        if d < today:
            continue
        b = by.setdefault(d, {"d": d, "coupon": 0.0, "bill": 0.0, "items": []})
        amt = float(x["offeringAmount"]) / 1e8
        kind = "bill" if x["securityType"] == "Bill" else "coupon"
        b[kind] += amt
        term = x["securityTerm"].replace("-Year", " 年").replace("-Month", " 個月").replace("-Week", " 週").replace("-Day", " 天")
        if kind == "bill":
            name = "短券"
        elif x.get("inflationProtected") == "Yes":
            name = "抗通膨債"
        elif x.get("floatingRate") == "Yes":
            name = "浮動利率債"
        else:
            name = {"Note": "中期公債", "Bond": "長期公債"}.get(x["securityType"], x["securityType"])
        b["items"].append(f"{term}{name} {amt:,.0f}")
    return sorted(by.values(), key=lambda b: b["d"])


def fred_api(sid, key, start="2023-01-01"):
    url = ("https://api.stlouisfed.org/fred/series/observations?" +
           urllib.parse.urlencode({"series_id": sid, "api_key": key, "file_type": "json", "observation_start": start}))
    j = json.loads(get(url, tries=2, timeout=30))
    return [[o["date"], float(o["value"])] for o in j["observations"] if o["value"] not in (".", "")]


# ── 計算 ──────────────────────────────────────
def pct_rank(hist, v):
    return 100.0 * sum(1 for x in hist if x < v) / len(hist)


def rolling_pct(vals):
    """vals: [(d, v or None)] → 同長度百分位（只用當日以前 5 年）。"""
    out, buf = [], []
    for d, v in vals:
        if v is None:
            out.append(None)
            continue
        buf.append(v)
        h = buf[-PCT_WINDOW:]
        out.append(pct_rank(h[:-1], v) if len(h) > PCT_MIN else None)
    return out


def auc(scores, labels):
    pairs = [(s, l) for s, l in zip(scores, labels) if s is not None and l is not None]
    pos = [s for s, l in pairs if l]
    neg = [s for s, l in pairs if not l]
    if not pos or not neg:
        return None
    allv = sorted(pairs, key=lambda p: p[0])
    rank, i = {}, 0
    ranks = [0.0] * len(allv)
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    rp = sum(r for r, (s, l) in zip(ranks, allv) if l)
    return round((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)), 3)


def band_of(v):
    return next(k for k, b in enumerate(BINS) if b[0] <= v < b[1]) if v is not None else None


def main():
    errs, sources = [], []
    P = {}
    for sym in ("HYG", "IEF", "LQD", "QQQ", "^GSPC"):
        P[sym] = yahoo_adj(sym)
    sources.append({"name": "信用債與公債 ETF（HYG、LQD、IEF）", "src": "Yahoo Finance 還原收盤", "asof": max(P["HYG"])})
    y0 = 2006
    n2 = tsy_series("daily_treasury_yield_curve", "2 Yr", y0)
    n10 = tsy_series("daily_treasury_yield_curve", "10 Yr", y0)
    r10 = tsy_series("daily_treasury_real_yield_curve", "10 YR", y0)
    sources.append({"name": "美債殖利率（2 年、10 年、10 年實際）", "src": "美國財政部每日殖利率", "asof": max(n2)})

    dates = sorted(set(P["HYG"]) & set(P["IEF"]) & set(P["LQD"]) & set(P["^GSPC"]))
    rows = []
    for d in dates:
        rows.append({"d": d, "hi": math.log(P["HYG"][d] / P["IEF"][d]), "hl": math.log(P["HYG"][d] / P["LQD"][d]),
                     "spx": P["^GSPC"][d], "qqq": P["QQQ"].get(d), "y2": n2.get(d), "y10": n10.get(d), "r10": r10.get(d)})
    # 殖利率缺值往前補（假日錯開）
    last = {}
    for r in rows:
        for k in ("y2", "y10", "r10"):
            if r[k] is None:
                r[k] = last.get(k)
            else:
                last[k] = r[k]
    for i, r in enumerate(rows):
        p = rows[i - LB] if i >= LB else None
        r["A"] = -(r["hi"] - p["hi"]) * 100 if p else None          # 高收益相對公債 21 日落後幅度（%）
        r["C"] = -(r["hl"] - p["hl"]) * 100 if p else None          # 高收益相對投資級
        r["B"] = (r["y2"] - p["y2"]) * 100 if p and r["y2"] is not None and p["y2"] is not None else None  # 2 年期 21 日變化 bp
        r["b10"] = (r["y10"] - p["y10"]) * 100 if p and r["y10"] is not None and p["y10"] is not None else None
        r["bei"] = (r["y10"] - r["r10"]) if r["y10"] is not None and r["r10"] is not None else None
        r["dbei"] = (r["bei"] - p["bei"]) * 100 if p and r["bei"] is not None and p.get("bei") is not None else None
    for k in ("A", "B", "C"):
        for r, v in zip(rows, rolling_pct([(r["d"], r[k]) for r in rows])):
            r[k + "p"] = v
    for r in rows:
        # 事先宣告為三成分；回測 2 年期上升為反向（AUC<0.5），看過結果後移出指數，只留觀察卡（頁面標＊）
        r["score3"] = (r["Ap"] + r["Bp"] + r["Cp"]) / 3 if None not in (r["Ap"], r["Bp"], r["Cp"]) else None
        r["score"] = (r["Ap"] + r["Cp"]) / 2 if None not in (r["Ap"], r["Cp"]) else None
    # 未來 21 日 SPX 最大回撤
    for i, r in enumerate(rows):
        fut = [x["spx"] for x in rows[i + 1:i + 1 + HORIZON]]
        r["fdd"] = (min(fut) / r["spx"] - 1) * 100 if len(fut) == HORIZON else None

    # 回測
    bt_rows = [r for r in rows if r["score"] is not None and r["fdd"] is not None]
    periods = [("全期", bt_rows), ("2008–2015", [r for r in bt_rows if r["d"] < "2016"]), ("2016 起", [r for r in bt_rows if r["d"] >= "2016"])]
    per = []
    for name, rs in periods:
        a = {}
        for k in ("score", "score3", "Ap", "Bp", "Cp"):
            a[k] = [auc([r[k] for r in rs], [r["fdd"] <= -5 for r in rs]), auc([r[k] for r in rs], [r["fdd"] <= -10 for r in rs])]
        per.append({"name": name, "n": len(rs), "from": rs[0]["d"] if rs else None, "auc": a})
    cal_bins = []
    for lo, hi, nm in BINS:
        rs = [r for r in bt_rows if lo <= r["score"] < hi]
        cal_bins.append({"name": nm, "lo": lo, "hi": hi, "n": len(rs), "share": round(100 * len(rs) / len(bt_rows), 1),
                         "d5": round(100 * sum(r["fdd"] <= -5 for r in rs) / len(rs), 1) if rs else None,
                         "d10": round(100 * sum(r["fdd"] <= -10 for r in rs) / len(rs), 1) if rs else None})
    base = {"d5": round(100 * sum(r["fdd"] <= -5 for r in bt_rows) / len(bt_rows), 1),
            "d10": round(100 * sum(r["fdd"] <= -10 for r in bt_rows) / len(bt_rows), 1)}

    # 股漲債不跟（節目 A 的判讀）：只當觀察，附回測
    div_ev, div_recent = [], []
    for i in range(1, len(rows)):
        r, p = rows[i], rows[i - 1]
        if r["qqq"] and p["qqq"] and (r["qqq"] / p["qqq"] - 1) * 100 >= DIVERGE_UP:
            lag = r["hi"] - p["hi"] <= 0
            if r["fdd"] is not None:
                div_ev.append((lag, r["fdd"]))
            if i >= len(rows) - 5:
                div_recent.append({"d": r["d"], "qqq": round((r["qqq"] / p["qqq"] - 1) * 100, 2),
                                   "credit": round((r["hi"] - p["hi"]) * 100, 2), "lag": lag})
    def ev_stat(flag):
        x = [f for c, f in div_ev if c == flag]
        return {"n": len(x), "d5": round(100 * sum(f <= -5 for f in x) / len(x), 1) if x else None}
    diverge = {"recent": div_recent, "lag": ev_stat(True), "join": ev_stat(False)}

    # 結算日曆
    try:
        settle = settlements()
        sources.append({"name": "國債結算日曆", "src": "TreasuryDirect 標售結果與公告", "asof": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
    except Exception as e:
        settle = []
        errs.append(f"TreasuryDirect: {str(e)[:80]}")

    # ICE 利差（選填，需 FRED API 金鑰；FRED 授權只給近 3 年，不進指數）
    ice = None
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        try:
            ice = {"hy": fred_api("BAMLH0A0HYM2", key), "ccc": fred_api("BAMLH0A3HYC", key), "ig": fred_api("BAMLC0A0CM", key)}
            sources.append({"name": "ICE BofA 信用利差（HY、CCC、IG）", "src": "FRED（需金鑰，近 3 年）", "asof": ice["hy"][-1][0]})
        except Exception as e:
            errs.append(f"FRED API: {str(e).replace(key, '***')[:80]}")

    L = rows[-1]
    stale = [s["name"] for s in sources if (datetime.now(timezone.utc) - datetime.strptime(s["asof"], "%Y-%m-%d").replace(tzinfo=timezone.utc)).days > STALE_DAYS]
    prev = next((r for r in reversed(rows[:-1]) if r["score"] is not None), None)
    tail = rows[-130:]
    sig = {
        "score": round(L["score"], 1), "scorePrev": round(prev["score"], 1) if prev else None, "band": band_of(L["score"]),
        "A": round(L["Ap"], 1), "C": round(L["Cp"], 1), "B": round(L["Bp"], 1) if L["Bp"] is not None else None,
        "Araw": round(L["A"], 2), "Craw": round(L["C"], 2),
        "y2": L["y2"], "y10": L["y10"], "d2": L["B"], "d10": L["b10"], "bei": round(L["bei"], 2) if L["bei"] is not None else None,
        "dbei": L["dbei"], "r10": L["r10"],
        "aS": [[r["d"], round(r["Ap"], 1)] for r in tail if r["Ap"] is not None],
        "cS": [[r["d"], round(r["Cp"], 1)] for r in tail if r["Cp"] is not None],
        "scoreS": [[r["d"], round(r["score"], 1)] for r in tail if r["score"] is not None],
        "y2S": [[r["d"], r["y2"]] for r in tail if r["y2"] is not None], "y10S": [[r["d"], r["y10"]] for r in tail if r["y10"] is not None],
    }
    # 利率重估判讀（節目 B：短端升得比長端多、隱含通脹下降 → 加息預期重估，不是供給）
    if sig["d2"] is not None and sig["d10"] is not None:
        if sig["d2"] >= REPRICE_BP and sig["d2"] > sig["d10"]:
            sig["rate"] = "短端領漲：加息預期重估"
        elif sig["d10"] >= REPRICE_BP and sig["d10"] > sig["d2"]:
            sig["rate"] = "長端領漲：期限溢價或供給"
        elif max(sig["d2"], sig["d10"]) <= -REPRICE_BP:
            sig["rate"] = "利率回落"
        else:
            sig["rate"] = "利率持平"
    nxt_big = next((s for s in settle if s["coupon"] >= SETTLE_BIG), None)
    days_to = (datetime.strptime(nxt_big["d"], "%Y-%m-%d") - datetime.now(timezone.utc).replace(tzinfo=None)).days + 1 if nxt_big else None
    sc = f"{L['score']:.0f}（{BINS[band_of(L['score'])][2]}）"

    def alert(id_, name, rule, on, now, kind="bad"):
        return {"id": id_, "name": name, "rule": rule, "on": bool(on), "now": now, "kind": kind}
    alerts = [
        alert("hi", "指數進入高區", "借錢成本指數 ≥ 75", L["score"] >= 75, sc),
        alert("mid", "指數偏高", "借錢成本指數 ≥ 60", L["score"] >= 60, sc),
        alert("reprice", "短端加息重估", f"2 年期 21 日上升 ≥ {REPRICE_BP}bp 且多於 10 年期",
              sig["d2"] is not None and sig["d2"] >= REPRICE_BP and sig["d2"] > (sig["d10"] or 0),
              f"2 年 {sig['d2']:+.0f}bp、10 年 {sig['d10']:+.0f}bp" if sig["d2"] is not None else "無資料"),
        alert("settle", "集中結算日將到", f"7 日內有單日附息債結算 ≥ {SETTLE_BIG:,} 億美元",
              days_to is not None and days_to <= 7, f"{nxt_big['d']} 附息債 {nxt_big['coupon']:,.0f} 億" if nxt_big else "已公告範圍內沒有"),
    ]
    if ice:
        ccc = ice["ccc"][-1][1]
        alerts.append(alert("ccc", "CCC 利差回到企穩線", f"ICE CCC 及以下 OAS < {CCC_STABLE}%", ccc < CCC_STABLE, f"{ccc:.2f}%", "good"))

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "asof": L["d"], "sig": sig, "alerts": alerts,
        "settle": settle[:12], "diverge": diverge, "ice": {k: v[-130:] for k, v in ice.items()} if ice else None,
        "cal": {"bins": cal_bins, "base": base, "periods": per, "horizon": HORIZON}, "bins": BINS,
        "params": {"LB": LB, "REPRICE_BP": REPRICE_BP, "SETTLE_BIG": SETTLE_BIG, "CCC_STABLE": CCC_STABLE, "DIVERGE_UP": DIVERGE_UP},
        "sources": sources, "stale": stale, "errs": errs,
    }
    with open(os.path.join(DATA_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DATA_DIR, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.BORROW=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";")
    hist = {"score": [[r["d"], round(r["score"], 1)] for r in rows if r["score"] is not None and r["d"] >= "2010-01-01"],
            "spx": [[r["d"], round(r["spx"], 2)] for r in rows if r["d"] >= "2010-01-01"]}
    with open(os.path.join(DATA_DIR, "history.js"), "w", encoding="utf-8") as f:
        f.write("window.BORROW_HIST=" + json.dumps(hist, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"[ok] {L['d']} 借錢成本指數 {L['score']:.1f}｜高收益/公債 {L['Ap']:.0f}　高收益/投資級 {L['Cp']:.0f}｜2 年 {sig['d2']:+.0f}bp 10 年 {sig['d10']:+.0f}bp｜{sig.get('rate')}")
    for p in per:
        print("   AUC", p["name"], p["n"], p["auc"])
    for s in settle[:6]:
        print(f"   結算 {s['d']} 附息 {s['coupon']:,.0f} 短券 {s['bill']:,.0f}")
    for e in errs:
        print("  [err]", e)
    return out


# ── Telegram 推播（格式與錢荒、共識崩塌兩則一致）──
LV = {"red": "🔴", "yellow": "🟡", "green": "🟢", "gray": "⚪"}


def _token():
    tok = os.environ.get("TG_BOT_TOKEN")
    path = os.environ.get("TG_ENV_FILE")
    if not tok and path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "TELEGRAM_BOT_TOKEN":
                    tok = v.strip().strip('"').strip("'")
    return tok


def _send(token, chat, text):
    body = {"chat_id": chat, "text": text, "disable_web_page_preview": "true", "parse_mode": "HTML"}
    if _kb():
        body["reply_markup"] = json.dumps(_kb())
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=urllib.parse.urlencode(body).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status



def _kb():
    """訊息底部的標準內嵌按鈕（所有 Telegram 版本都會顯示；Rich 內建的 tg-button 部分裝置不顯示）。"""
    url = os.environ.get("DASHBOARD_URL")
    return {"inline_keyboard": [[{"text": BTN_TEXT, "url": url}]]} if url else None


def _send_rich(token, chat, rich_html):
    rich_html = re.sub(r"<tg-button-row>.*?</tg-button-row>", "", rich_html)
    payload = {"chat_id": chat, "rich_message": {"html": rich_html}}
    if _kb():
        payload["reply_markup"] = _kb()
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendRichMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", "replace")[:200])


def emoji_gauge(score, n=12):
    def c(k):
        x = (k + .5) * 100 / n
        return "🟩" if x < 40 else "🟨" if x < 60 else "🟧" if x < 75 else "🟥"
    cells = [c(k) for k in range(n)]
    cells[min(n - 1, max(0, int(score / 100 * n)))] = "📍"
    return "".join(cells)


def pbar(p, n=20):
    on = round(max(0, min(100, p)) / 100 * n)
    cells = ["█" if k < on else "░" for k in range(n)]
    cut = round(.75 * n)
    return "".join(cells[:cut]) + "┃" + "".join(cells[cut:])


def layers(out):
    """三層判讀，與頁面 #layers 同一套規則。管道層讀錢荒分頁的 SOFR − IORB。"""
    s = out["sig"]
    try:
        with open(os.path.join(os.path.dirname(ROOT), "data", "data.json"), encoding="utf-8") as f:
            G = json.load(f)
        sp = next(i for i in G["indicators"] if i["id"] == "spread")
        pipe = (sp["level"], f"SOFR − IORB {sp['value']:+.1f} bp",
                {"red": "錢不夠", "yellow": "偏緊", "green": "錢夠"}.get(sp["level"], "—"))
    except Exception:
        pipe = ("gray", "錢荒資料未載入", "—")
    rr = s.get("rate") or "—"
    price = ("red" if rr.startswith("短端") else "yellow" if rr.startswith("長端") else "green",
             f"2 年 {s['d2']:+.0f}bp、10 年 {s['d10']:+.0f}bp（21 日）" if s.get("d2") is not None else "無資料",
             rr.split("：")[0])
    b = s["band"]
    clv = "red" if b >= 3 else "yellow" if b >= 2 else "green"
    credit = (clv, f"指數 {s['score']:.0f}", {"red": "貴在低評等", "yellow": "低評等轉貴", "green": "信用平穩"}[clv])
    return [("管道層", pipe), ("價格層", price), ("信用層", credit)]


def notify(out):
    """DAILY=1：每天推日報。未設：只在區間、警示或資料停更變化時推。沒設 token 時只印出，不送出。"""
    try:
        with open(STATE, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = {}
    s, E = out["sig"], html.escape
    new = {"band": s["band"], "stale": out["stale"], **{a["id"]: a["on"] for a in out["alerts"]}}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False)

    # 從較低區間第一次升進「高」區：另推一則醒目警報（不受 DAILY 影響）
    if old.get("band") is not None and s["band"] is not None and old["band"] < 3 and s["band"] == 3:
        _tok, _chat = _token(), os.environ.get("TG_CHAT_ID")
        _cb = (out["cal"].get("bins") or [None] * 4)[3] if out.get("cal") else None
        _al = [f"🚨 <b>借錢成本指數首次進入「高」區</b>",
               f"{out['bins'][old['band']][2]} → <b>高</b>：{s['score']:.0f}／100（門檻 75）"]
        if _cb and _cb.get("d10") is not None:
            _al.append(f"歷史上進入高區後 21 日內 SPX 跌超過 10% 的比例 {_cb['d10']:.1f}%（全期平均 {out['cal']['base']['d10']:.1f}%）")
        if _tok and _chat:
            try:
                print("[tg] 已推高區警報", _send(_tok, _chat, "\n".join(_al)))
            except Exception as e:
                print("[tg] 高區警報失敗：", str(e)[:160])
        else:
            print("[tg] 預定高區警報：\n" + "\n".join(_al))
    bn = BINS[s["band"]][2]
    changed, bells = False, []
    if old.get("band") is not None and old["band"] != s["band"]:
        changed = True
        bells.append(f"🔔 區間變化：{BINS[old['band']][2]} → <b>{bn}</b>")
    flips = [a for a in out["alerts"] if a["id"] in old and old[a["id"]] != a["on"]]
    if flips or sorted(old.get("stale", [])) != sorted(out["stale"]):
        changed = True
    cb, base = out["cal"]["bins"][s["band"]], out["cal"]["base"]
    dlt = f"（前一日 {s['scorePrev']:.0f}）" if s.get("scorePrev") is not None else ""
    L3 = layers(out)
    on = [a for a in out["alerts"] if a["on"]]
    url = os.environ.get("DASHBOARD_URL")
    comps = [("高收益落後公債", s["A"], f"HYG÷IEF 21 日 {-s['Araw']:+.2f}%"),
             ("高收益落後投資級", s["C"], f"HYG÷LQD 21 日 {-s['Craw']:+.2f}%")]
    dot = lambda p: "🔴" if p >= 75 else "🟡" if p >= 60 else "🟢"

    # 文字版（Rich 失敗時的備援）
    t = [f"<b>借錢成本指數 {s['score']:.0f}／100（{bn}）</b>{dlt}"] + bells
    t += ["", emoji_gauge(s["score"]), E("0 低 ─ 40 中 ─ 60 偏高（警示）─ 75 高（危險）─ 100")]
    if cb.get("d10") is not None:
        t.append(f"歷史上在「{bn}」區，21 日內 SPX 跌超過 10% 的比例 {cb['d10']:.1f}%（全期平均 {base['d10']:.1f}%）")
    t += ["", "<b>三層判讀</b>"] + [f"{LV[lv]} {n}｜{E(w)}　{E(v)}" for n, (lv, v, w) in L3]
    t += ["", "<b>成分</b>（5 年百分位，┃ 為 75 警戒線）"]
    for n, p, ex in comps:
        t += [f"{dot(p)} {n} <b>{p:.0f}</b>", f"<code>{pbar(p)}</code>", E(ex), ""]
    if flips:
        t += ["<b>變化</b>"] + [f"{'🔴' if a['on'] else '⚪'} {E(a['name'])}{'觸發' if a['on'] else '解除'}：{E(a['now'])}" for a in flips] + [""]
    t += ["<b>觸發中</b>" if on else "觸發中：無"] + [f"• {E(a['name'])}：{E(a['now'])}" for a in on]
    if out["stale"]:
        t += ["", f"⚠️ 資料停更：{E('、'.join(out['stale']))}"]
    if url:
        t += ["", E(url)]
    msg = "\n".join(t)

    # Rich Message 版
    sc = s["score"]
    nxt = next(((b, n) for b, n in ((40, "中"), (60, "偏高（警示）"), (75, "高（危險）")) if sc < b), None)
    gap = f"距「{nxt[1]}」線 {nxt[0]} 還差 <b>{nxt[0] - sc:.0f}</b>" if nxt else "已在最高區間"
    h = [f"<h3>借錢成本指數 {sc:.0f}／100</h3><p><mark>{bn}</mark>　{E(s.get('rate') or '')}{dlt}</p>"]
    if bells:
        h.append("<blockquote>" + "<br>".join(bells) + "</blockquote>")
    h.append("<table bordered compact><tr><th>低</th><th>中</th><th>偏高</th><th>高</th></tr><tr>"
             + "".join(f"<td align=\"center\">{'📍 ' + format(sc, '.0f') if lo <= sc < hi or (hi == 100 and sc >= lo) else f'{lo}–{hi}'}</td>"
                       for lo, hi in ((0, 40), (40, 60), (60, 75), (75, 100)))
             + f"</tr></table><p>{gap}</p>")
    h.append("<table bordered compact><caption>三層判讀（先排除管道，再看價格，最後定位信用）</caption>"
             + "".join(f"<tr><td>{LV[lv]} {n}</td><td><b>{E(w)}</b></td><td>{E(v)}</td></tr>" for n, (lv, v, w) in L3) + "</table>")
    h.append("<table bordered compact><caption>成分（5 年百分位，┃ 為 75 警戒線）</caption>"
             "<tr><th>成分</th><th align=\"right\">百分位</th><th>依據</th></tr>"
             + "".join(f"<tr><td>{dot(p)} {n}</td><td align=\"right\"><b>{p:.0f}</b></td><td>{E(ex)}</td></tr>"
                       f"<tr><td colspan=\"3\"><code>{pbar(p)}</code></td></tr>" for n, p, ex in comps) + "</table>")
    if cb.get("d10") is not None:
        h.append(f"<details><summary>歷史對照：「{bn}」區</summary><p>21 日內 SPX 跌超過 10% 的比例 <b>{cb['d10']:.1f}%</b>、"
                 f"超過 5% 為 <b>{cb['d5']:.1f}%</b><br>全期平均 {base['d10']:.1f}%／{base['d5']:.1f}%</p>"
                 "<p><sub>區分力集中在「高」區；「偏高」區與全期平均相近</sub></p></details>")
    if flips:
        h.append("<h4>變化</h4><ul>" + "".join(
            f"<li>{'🔴' if a['on'] else '⚪'} {E(a['name'])}{'觸發' if a['on'] else '解除'}：{E(a['now'])}</li>" for a in flips) + "</ul>")
    h.append("<h4>觸發中</h4><ul>" + "".join(f"<li>{E(a['name'])}：{E(a['now'])}</li>" for a in on) + "</ul>"
             if on else "<p>觸發中：無</p>")
    if out["stale"]:
        h.append(f"<blockquote>⚠️ 資料停更：{E('、'.join(out['stale']))}</blockquote>")
    if url:
        h.append(f'<tg-button-row><tg-button type="url" style="primary" url="{E(url)}">開借錢成本雷達</tg-button></tg-button-row>')
    rich = "".join(h)

    if not (os.environ.get("DAILY") or changed):
        print("[tg] 無變化，不推播")
        return
    tok, chat = _token(), os.environ.get("TG_CHAT_ID")
    if not (tok and chat):
        print("[tg] 未設定 token／TG_CHAT_ID，預定推播內容：\n" + msg + "\n\n[rich]\n" + rich)
        return
    try:
        print("[tg] 已推播（Rich）", _send_rich(tok, chat, rich))
        return
    except Exception as e:
        print("[tg] Rich 推播失敗，改舊版：", str(e)[:160])
    print("[tg] 已推播", _send(tok, chat, msg))


if __name__ == "__main__":
    try:
        notify(main())
    except Exception as e:
        tok, chat = _token(), os.environ.get("TG_CHAT_ID")
        if tok and chat:
            body = urllib.parse.urlencode({"chat_id": chat, "text": f"⚠️ 借錢成本雷達執行失敗：{str(e)[:300]}"}).encode()
            urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body), timeout=30)
        raise
