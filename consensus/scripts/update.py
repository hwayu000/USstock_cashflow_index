# -*- coding: utf-8 -*-
"""共識崩塌雷達：抓資料 → 判階段 → 算定價分布 → 寫 data/ → 狀態變化推 Telegram。
只用標準庫：  py scripts/update.py
環境變數（選填）：TG_BOT_TOKEN 或 TG_ENV_FILE、TG_CHAT_ID、DASHBOARD_URL、DAILY=1（每天固定推日報）
"""
import bisect, csv, html, io, json, math, os, re, statistics as stats, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
STATE = os.path.join(DATA_DIR, "state.json")
SNAP = os.path.join(DATA_DIR, "snapshots.json")
UA = {"User-Agent": "Mozilla/5.0 (consensus-flip-radar)"}

# ── 判定規則（先寫定再回測，不依結果調整）──
PCT_WINDOW = 1260       # 百分位回看 5 年：節目說 SKEW 150–160 約在 90% 高位，5 年窗 155 = 89.8
PCT_MIN = 252
FLIP_RATIO = 1.0        # VIX ≥ VIX3M：翻轉定價落在前端
FLIP_MULT = 1.25        # VIX ≥ 前 20 日中位數 ×1.25
RECOVER_DROP = 0.85     # VIX ≤ 高點 ×0.85：翻轉結束，進入回落
DONE_EXCESS = 0.25      # 超額回到 25% 以內（兩個半衰期）：回落結束
SKEW_HOT = 90           # 節目口徑
SYNC_HOT = 75
GEX_LOW = 25
QUIET = 35
BT_FROM = "2015-06-20"  # DSPX 自 2014-06 起，再加 1 年百分位暖機
HORIZON = 21
STALE_DAYS = 5          # 來源最新日期落後超過此天數視為停更（涵蓋週末加假日）
PHASES = ["", "翻轉前", "翻轉過程", "恐慌回落"]
CBOE = "https://cdn.cboe.com/api/global/us_indices/daily_prices/"
YH_MAP = {"VIX": "^VIX", "VIX9D": "^VIX9D", "VIX3M": "^VIX3M", "SKEW": "^SKEW", "DSPX": "^DSPX", "SPX": "^GSPC"}  # COR3M 在 Yahoo 沒有歷史


def get(url, tries=3, deadline=60):
    """總時限下載：urllib 的 timeout 只管單次讀取，遇到極慢吐資料會被拖住。"""
    for i in range(tries):
        try:
            t0 = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                buf = []
                while True:
                    c = r.read(65536)
                    if not c:
                        break
                    buf.append(c)
                    if time.time() - t0 > deadline:
                        raise TimeoutError(f"超過總時限 {deadline}s")
            return b"".join(buf).decode("utf-8")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def cboe(sym):
    rows = list(csv.reader(io.StringIO(get(f"{CBOE}{sym}_History.csv"))))
    col = rows[0].index("CLOSE") if "CLOSE" in rows[0] else 1
    out = {}
    for r in rows[1:]:
        try:
            m, d, y = r[0].split("/")
            out[f"{y}-{m}-{d}"] = float(r[col])
        except (ValueError, IndexError):
            pass
    return out


def yahoo(sym, rng="10y"):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval=1d"))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    off = r["meta"].get("gmtoffset", 0)  # 韓股 00:00 KST 用 UTC 會落到前一天
    out = []
    for t, o, h, l, c in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        out.append([datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d"), round(o, 2), round(h, 2), round(l, 2), round(c, 2)])
    return out


def naver_kospi():
    end = datetime.now(timezone.utc).strftime("%Y%m%d")
    rows = json.loads(get(f"https://api.stock.naver.com/chart/domestic/index/KOSPI/day?startDateTime=20160101000000&endDateTime={end}235959"))
    out = []
    for x in rows:
        d = str(x["localDate"])
        out.append([f"{d[:4]}-{d[4:6]}-{d[6:8]}", x["openPrice"], x["highPrice"], x["lowPrice"], x["closePrice"]])
    return out


def squeeze_gex():
    txt = get("https://squeezemetrics.com/monitor/static/DIX.csv", tries=2, deadline=40)
    return {r["date"]: float(r["gex"]) for r in csv.DictReader(io.StringIO(txt)) if r.get("gex")}


class Rolling:
    """滾動百分位（與 pandas rank(pct) 同口徑，取平均名次）。"""

    def __init__(self, n, minp):
        self.n, self.minp, self.q, self.s = n, minp, [], []

    def push(self, x):
        if x is None:
            return None
        self.q.append(x)
        bisect.insort(self.s, x)
        if len(self.q) > self.n:
            self.s.pop(bisect.bisect_left(self.s, self.q.pop(0)))
        if len(self.q) < self.minp:
            return None
        lo, hi = bisect.bisect_left(self.s, x), bisect.bisect_right(self.s, x)
        return (lo + hi + 1) / 2 / len(self.s) * 100


def build_rows(S):
    days = sorted(set(S["VIX"]) & set(S["SPX"]))
    last, age = {}, defaultdict(int)
    rows, rv_win, vix_hist = [], [], []
    prev_spx = None
    roll = {k: Rolling(PCT_WINDOW, PCT_MIN) for k in ("SKEW", "DSPX", "COR3M", "VIX", "RV", "GEX", "ratio")}
    for d in days:
        r = {"d": d, "VIX": S["VIX"][d], "SPX": S["SPX"][d]}
        for k in ("VIX3M", "VIX9D", "SKEW", "COR3M", "DSPX", "GEX"):
            if d in S.get(k, {}):
                last[k], age[k] = S[k][d], 0
            else:
                age[k] += 1
            r[k] = last.get(k) if age[k] <= 3 else None
        if prev_spx:
            rv_win.append(math.log(r["SPX"] / prev_spx))
            rv_win = rv_win[-20:]
        r["RV"] = stats.stdev(rv_win) * math.sqrt(252) * 100 if len(rv_win) == 20 else None
        prev_spx = r["SPX"]
        r["ratio"] = r["VIX"] / r["VIX3M"] if r["VIX3M"] else None
        for k in roll:
            r[k + "p"] = roll[k].push(r.get(k))
        # 共識崩塌指數：翻轉強度、市場同步、Gamma 偏低，三項 5 年百分位等權平均；缺一項時以其餘兩項計算並標示
        comp = {"A": r["ratiop"], "B": r["COR3Mp"], "C": None if r["GEXp"] is None else 100 - r["GEXp"]}
        r.update(comp)
        have = [v for v in comp.values() if v is not None]
        r["score"] = sum(have) / len(have) if len(have) >= 2 else None
        r["scoreN"] = len(have)
        r["base"] = stats.median(vix_hist[-20:]) if len(vix_hist) >= 20 else None
        vix_hist.append(r["VIX"])
        r["a"] = r["SKEWp"] is not None and r["SKEWp"] >= SKEW_HOT
        r["b"] = r["DSPXp"] is not None and r["DSPXp"] <= 25
        r["c"] = r["VIXp"] is not None and r["RVp"] is not None and r["VIXp"] <= QUIET and r["RVp"] <= QUIET
        r["n"] = int(r["a"]) + int(r["b"]) + int(r["c"])
        rows.append(r)
    return rows


def run_states(rows):
    """狀態機：0 非事件 / 1 翻轉 / 2 回落。回傳事件起點。"""
    cur, peak, base = 0, None, None
    onsets = []
    for i, r in enumerate(rows):
        v = r["VIX"]
        if cur == 0:
            if r["ratio"] and r["base"] and r["ratio"] >= FLIP_RATIO and v >= FLIP_MULT * r["base"]:
                cur, peak, base = 1, v, r["base"]
                onsets.append(i)
        elif cur == 1:
            peak = max(peak, v)
            if v <= peak * RECOVER_DROP:
                cur = 2
        else:
            if v > peak:
                cur, peak = 1, v
            elif v - base <= DONE_EXCESS * (peak - base):
                cur = 0
        r["st"], r["peak"], r["ev_base"] = cur, peak if cur else None, base if cur else None
        r["phase"] = cur + 1
    return onsets


def events(rows, onsets, since="2010"):
    out = []
    for o in onsets:
        if rows[o]["d"] < since:
            continue
        base = rows[o]["base"]
        j = o
        while j + 1 < len(rows) and rows[j + 1]["st"] == 1:
            j += 1
        pi = max(range(o, j + 1), key=lambda k: rows[k]["VIX"])
        pk = rows[pi]["VIX"]
        half = quarter = None
        for k in range(pi + 1, min(pi + 400, len(rows))):
            ex = rows[k]["VIX"] - base
            if half is None and ex <= 0.5 * (pk - base):
                half = k - pi
            if ex <= DONE_EXCESS * (pk - base):
                quarter = k - pi
                break
        ref = rows[max(0, o - 1)]["SPX"]
        low = min(rows[k]["SPX"] for k in range(o, min(pi + (quarter or 5) + 1, len(rows))))
        decay = [round((rows[k]["VIX"] - base) / (pk - base), 3) for k in range(pi, min(pi + 16, len(rows)))] if pk > base else []
        out.append({"on": rows[o]["d"], "peakd": rows[pi]["d"], "peak": round(pk, 2), "base": round(base, 2),
                    "half": half, "quarter": quarter, "dd": round((low / ref - 1) * 100, 1), "decay": decay,
                    "live": quarter is None and pi + 400 > len(rows)})
    return out


def backtest(rows, onsets):
    """只看非事件日：條件成立後 21 日內，翻轉機率與 SPX 最大回撤。post=True 表示看過初次結果後才加入。"""
    onset = set(onsets)
    N = len(rows)
    samples = []
    for i, r in enumerate(rows):
        if r["d"] < BT_FROM or r["st"] != 0 or i + HORIZON >= N:
            continue
        w = [rows[k]["SPX"] for k in range(i + 1, i + HORIZON + 1)]
        samples.append((r, min(w) / r["SPX"] - 1, any(k in onset for k in range(i + 1, i + HORIZON + 1))))

    def row(name, fn, post=False):
        s = [(dd, fon) for r, dd, fon in samples if fn(r)]
        if not s:
            return {"name": name, "n": 0, "post": post}
        return {"name": name, "post": post, "n": len(s),
                "flip": round(sum(f for _, f in s) / len(s) * 100, 1),
                "d5": round(sum(d < -0.05 for d, _ in s) / len(s) * 100, 1),
                "d10": round(sum(d < -0.10 for d, _ in s) / len(s) * 100, 1)}

    P = lambda k, lo=None, hi=None: (lambda r: r[k + "p"] is not None and (lo is None or r[k + "p"] >= lo) and (hi is None or r[k + "p"] <= hi))
    return {"from": BT_FROM, "to": samples[-1][0]["d"], "horizon": HORIZON, "rows": [
        row("基準：所有非事件日", lambda r: True),
        row("SKEW 第 90 百分位以上", lambda r: r["a"]),
        row("VIX 與已實現波動皆在第 35 百分位以下", lambda r: r["c"]),
        row("SKEW、低離散、波動安靜三項達兩項", lambda r: r["n"] >= 2),
        row("DSPX 第 25 百分位以下（低離散）", P("DSPX", hi=25)),
        row("DSPX 第 75 百分位以上（高離散）", P("DSPX", lo=75)),
        row("COR3M 第 75 百分位以上（高同步）", P("COR3M", lo=75), True),
        row("COR3M 第 25 百分位以下（低同步）", P("COR3M", hi=25), True),
        row("GEX 第 25 百分位以下（低 Gamma）", P("GEX", hi=25), True),
        row("GEX 第 75 百分位以上（高 Gamma）", P("GEX", lo=75), True),
    ]}


BINS = [(0, 40, "低"), (40, 60, "中"), (60, 75, "偏高"), (75, 101, "高")]


def band_of(v):
    return next((i for i, (lo, hi, _) in enumerate(BINS) if lo <= v < hi), None) if v is not None else None


def score_eval(rows):
    """分數校準：每個分數區間之後 21 日 SPX 最大回撤的歷史分布；並與只看 VIX 比較區分力（AUC）。"""
    N = len(rows)
    S = []
    for i, r in enumerate(rows):
        if r["d"] < BT_FROM or i + HORIZON >= N or r["score"] is None or r["scoreN"] < 3:
            continue
        dd = min(rows[k]["SPX"] for k in range(i + 1, i + HORIZON + 1)) / r["SPX"] - 1
        S.append((r, dd))
    if not S:  # 某成分整段缺漏（如 GEX 來源故障）時無法校準，由呼叫端沿用上次結果
        return None

    def auc(xs, key, thr):
        pts = [(x[0][key], x[1] < thr) for x in xs if x[0][key] is not None]
        pts.sort(key=lambda p: p[0])
        ranks, i = {}, 0
        while i < len(pts):  # 同分取平均名次
            j = i
            while j + 1 < len(pts) and pts[j + 1][0] == pts[i][0]:
                j += 1
            for k in range(i, j + 1):
                ranks[k] = (i + j) / 2 + 1
            i = j + 1
        n1 = sum(1 for p in pts if p[1])
        n0 = len(pts) - n1
        if not n1 or not n0:
            return None
        return round((sum(ranks[k] for k, p in enumerate(pts) if p[1]) - n1 * (n1 + 1) / 2) / (n1 * n0), 3)

    def bins(xs):
        out = []
        for lo, hi, name in BINS:
            s = [dd for r, dd in xs if lo <= r["score"] < hi]
            out.append({"name": name, "lo": lo, "hi": hi, "n": len(s), "share": round(len(s) / len(xs) * 100, 1),
                        "d5": round(sum(d < -0.05 for d in s) / len(s) * 100, 1) if s else None,
                        "d10": round(sum(d < -0.10 for d in s) / len(s) * 100, 1) if s else None})
        return out

    periods = []
    for name, f in (("全期", lambda r: True), ("2015–2020", lambda r: r["d"] < "2021"), ("2021 起", lambda r: r["d"] >= "2021")):
        xs = [x for x in S if f(x[0])]
        periods.append({"name": name, "n": len(xs), "auc": {k: [auc(xs, k, -0.05), auc(xs, k, -0.10)] for k in ("score", "VIXp", "A", "B", "C", "SKEWp")}})
    allbase = {"d5": round(sum(d < -0.05 for _, d in S) / len(S) * 100, 1), "d10": round(sum(d < -0.10 for _, d in S) / len(S) * 100, 1)}
    return {"from": BT_FROM, "to": S[-1][0]["d"], "horizon": HORIZON, "bins": bins(S), "base": allbase, "periods": periods}


def options():
    """SPX 延遲報價 → 7／14／30 日分布與第二峰。"""
    J = json.loads(get("https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json", deadline=180))
    D = J["data"]
    asof = (J.get("timestamp") or "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.strptime(asof, "%Y-%m-%d")
    exp = defaultdict(lambda: {"C": {}, "P": {}})
    for o in D["options"]:
        m = re.match(r"^(SPXW?)(\d{6})([CP])(\d{8})$", o["option"])
        if m:
            root, e, cp, k = m.groups()
            exp[(root, e)][cp][int(k) / 1000] = o
    S = D["current_price"]

    def fit(key):
        C, P = exp[key]["C"], exp[key]["P"]
        near = [k for k in sorted(set(C) & set(P), key=lambda k: abs(k - S))[:6] if C[k]["bid"] > 0 and P[k]["bid"] > 0]
        if len(near) < 3:
            return None
        F = stats.mean(k + (C[k]["bid"] + C[k]["ask"]) / 2 - (P[k]["bid"] + P[k]["ask"]) / 2 for k in near)
        pts = []
        for k in sorted(set(C) | set(P)):
            cp = "P" if k < F else "C"
            o = (P if cp == "P" else C).get(k)
            if not o or o["bid"] <= 0 or o["ask"] <= 0 or not (0.6 * F < k < 1.2 * F):
                continue
            mid = (o["bid"] + o["ask"]) / 2
            if (o["ask"] - o["bid"]) / mid > 0.5:
                continue
            w = bl.implied_w(F, k, mid, cp)
            if w:
                pts.append((k, w))
        return ((datetime.strptime(key[1], "%y%m%d") - now).days, F, pts) if len(pts) >= 40 else None

    fits = {}
    for key in sorted(exp, key=lambda x: x[1]):
        if 3 <= (datetime.strptime(key[1], "%y%m%d") - now).days <= 40:
            f = fit(key)
            if f:
                fits[key] = f
    picks, used = [], set()
    for tgt in (7, 14, 30):
        cand = [k for k, f in fits.items() if abs(f[0] - tgt) <= max(3, tgt * 0.2) and k[1] not in used]
        if not cand:
            continue
        key = max(cand, key=lambda k: len(fits[k][2]) - 8 * abs(fits[k][0] - tgt))
        used.add(key[1])
        dte, F, pts = fits[key]
        atm = min(pts, key=lambda r: abs(r[0] - F))[1]
        k2, _, den = bl.second_peak(pts, F, atm)
        Pat = lambda K: next((r[2] for r in den if r[0] >= K), None)
        picks.append({"tgt": tgt, "exp": "20" + key[1], "dte": dte, "F": round(F, 1), "atm": round(math.sqrt(atm / (dte / 365)) * 100, 1),
                      "k2": None if k2 is None else round(k2), "p5": Pat(F * 0.95), "p10": Pat(F * 0.90), "p15": Pat(F * 0.85),
                      "den": [[round(K), round(q * 1e5, 3), round(P, 4)] for K, q, P in den[::2]]})
    return {"spot": S, "asof": J.get("timestamp"), "exps": picks}


def load_prior(path, prefix=""):
    try:
        with open(path, encoding="utf-8") as f:
            t = f.read()
        return json.loads(t[len(prefix):].rstrip(";"))
    except Exception:
        return None


def main():
    errs, stale = [], []
    os.makedirs(DATA_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    prior = load_prior(os.path.join(DATA_DIR, "data.json")) or {}
    prior_h = load_prior(os.path.join(DATA_DIR, "history.js"), "window.RADAR_HIST=") or {}

    S, used = {}, {}
    for s in ("VIX", "VIX3M", "VIX9D", "SKEW", "COR3M", "DSPX", "SPX"):
        try:
            S[s] = cboe(s)
            used[s] = "Cboe"
        except Exception as e:
            errs.append(f"Cboe {s}: {str(e)[:80]}")
            S[s] = {}
            if s in YH_MAP:
                try:
                    S[s] = {r[0]: r[4] for r in yahoo(YH_MAP[s])}
                    used[s] = "Yahoo 備援"
                except Exception as e2:
                    errs.append(f"Yahoo {s}: {str(e2)[:80]}")
    if not S["VIX"] or not S["SPX"] or not S["VIX3M"]:
        raise RuntimeError("VIX／VIX3M／SPX 主備來源皆失敗：" + "; ".join(errs))
    try:
        S["GEX"] = squeeze_gex()
    except Exception as e:
        errs.append(f"SqueezeMetrics: {str(e)[:80]}")
        S["GEX"] = {}

    rows = build_rows(S)
    onsets = run_states(rows)
    evs = events(rows, onsets)
    bt = backtest(rows, onsets)
    cal = score_eval(rows)
    if cal is None:
        cal = dict(prior["cal"], stale=True) if prior.get("cal") else None
    L, prev = rows[-1], rows[-2]

    # K 線：抓不到就沿用上次，只影響圖表，不影響判定
    px, px_src = {}, {}
    for key, sym in (("SPX", "^GSPC"), ("NDX", "^NDX"), ("KOSPI", "^KS11")):
        try:
            px[key] = yahoo(sym)
            px_src[key] = "Yahoo"
        except Exception as e:
            errs.append(f"Yahoo {sym}: {str(e)[:80]}")
    if "KOSPI" not in px:
        try:
            px["KOSPI"] = naver_kospi()
            px_src["KOSPI"] = "Naver 備援"
        except Exception as e:
            errs.append(f"Naver: {str(e)[:80]}")
    for key in ("SPX", "NDX", "KOSPI"):
        if key not in px and (prior_h.get("px") or {}).get(key):
            px[key] = prior_h["px"][key]
            px_src[key] = "上次快取"

    # 每日交叉比對：只比最近 5 日，差距過大就在來源表示警
    check = []
    if "SPX" in px:
        yc = {r[0]: r[4] for r in px["SPX"]}
        for d in sorted(S["SPX"])[-5:]:
            if d in yc and abs(yc[d] / S["SPX"][d] - 1) > 0.005:
                check.append(f"SPX {d}")
    for s in ("VIX", "VIX3M"):
        if used.get(s) == "Cboe":
            try:
                yc = {r[0]: r[4] for r in yahoo(YH_MAP[s], "1mo")}
                for d in sorted(S[s])[-5:]:
                    if d in yc and abs(yc[d] / S[s][d] - 1) > 0.02:
                        check.append(f"{s} {d}")
            except Exception:
                pass

    cb = []
    if "KOSPI" in px:
        for a, b in zip(px["KOSPI"][1:], px["KOSPI"][:-1]):
            if a[3] / b[4] - 1 <= -0.08:
                cb.append({"d": a[0], "low": round((a[3] / b[4] - 1) * 100, 1)})
    ks_last = px["KOSPI"][-1] if "KOSPI" in px else None

    opt, opt_stale = None, False
    try:
        opt = options()
    except Exception as e:
        errs.append(f"期權鏈: {str(e)[:100]}")
        if prior.get("opt"):
            opt, opt_stale = prior["opt"], True

    snaps = load_prior(SNAP) or {}
    e30 = next((e for e in (opt or {}).get("exps", []) if e["tgt"] == 30), None)
    if opt and not opt_stale:
        snaps[L["d"]] = {"k2": e30 and e30["k2"], "p10": e30 and e30["p10"]}
        with open(SNAP, "w", encoding="utf-8") as f:
            json.dump(snaps, f, ensure_ascii=False, separators=(",", ":"))

    # 來源狀態表
    def asof_of(sers):
        return min(max(S[k]) for k in sers if S.get(k))

    def src(name, use, provider, url, asof, note=""):
        late = False
        if asof:
            late = (today - datetime.strptime(asof[:10], "%Y-%m-%d").date()).days > STALE_DAYS
        return {"name": name, "use": use, "provider": provider, "url": url, "asof": asof, "ok": bool(asof) and not late, "note": note}

    fallback = [k for k, v in used.items() if v != "Cboe"]
    missing = [k for k in ("VIX9D", "SKEW", "COR3M", "DSPX") if not S.get(k)]
    note = "；".join(x for x in (f"{'、'.join(fallback)} 改用 Yahoo 備援" if fallback else "", f"{'、'.join(missing)} 無資料" if missing else "",
                                 f"與 Yahoo 差異：{'、'.join(check)}" if check else "") if x)
    sources = [
        src("波動率與尾部指數", "VIX、VIX9D、VIX3M、SKEW、COR3M、DSPX、SPX 收盤（階段判定）", "Cboe 官方", "https://www.cboe.com/tradable_products/vix/vix_historical_data/", asof_of(["VIX", "VIX3M", "SKEW", "SPX"]), note),
        src("SPX 選擇權鏈", "定價分布、第二峰", "Cboe 官方（延遲報價）", "https://www.cboe.com/delayed_quotes/spx/quote_table", (opt or {}).get("asof"), "沿用上次資料" if opt_stale else ""),
        src("做市商 Gamma", "GEX", "SqueezeMetrics", "https://squeezemetrics.com/monitor/dix", max(S["GEX"]) if S.get("GEX") else None),
        src("指數 K 線", "SPX、NDX、KOSPI 圖表與韓股跌幅代理", "Yahoo Finance（KOSPI 備援 Naver）", "https://finance.yahoo.com/", ks_last[0] if ks_last else None, "；".join(f"{k} {v}" for k, v in px_src.items() if v != "Yahoo")),
    ]
    stale = [s["name"] for s in sources if not s["ok"]]

    bands, cur = [], None
    for r in rows:
        if r["d"] < "2016-01-01":
            continue
        ph = r["phase"] if r["phase"] >= 2 else None
        if ph is None:
            cur = None
        elif cur and cur["ph"] == ph:
            cur["to"] = r["d"]
        else:
            cur = {"ph": ph, "from": r["d"], "to": r["d"]}
            bands.append(cur)

    tail = lambda k, n=130: [[r["d"], round(r[k], 3)] for r in rows[-n:] if r.get(k) is not None]
    phase = L["phase"]
    live = next((e for e in reversed(evs) if L["st"] and e["on"] >= rows[onsets[-1]]["d"]), None)
    pctile_at = lambda k, q: round(sorted(w)[int(len(w) * q)], 1) if (w := [r[k] for r in rows[-PCT_WINDOW:] if r.get(k) is not None]) else None
    sig = {
        "skew": L["SKEW"], "skewp": L["SKEWp"], "skew90": pctile_at("SKEW", 0.9), "skewS": tail("SKEW"),
        "vix": L["VIX"], "vixp": L["VIXp"], "vix3m": L["VIX3M"], "vix9d": L["VIX9D"], "rv": L["RV"], "rvp": L["RVp"],
        "ratio": L["ratio"], "ratioS": tail("ratio"), "vixChg": (L["VIX"] / prev["VIX"] - 1) * 100,
        "base": L["base"], "dspx": L["DSPX"], "dspxp": L["DSPXp"], "cor3m": L["COR3M"], "cor3mp": L["COR3Mp"], "cor75": pctile_at("COR3M", 0.75), "corS": tail("COR3M"),
        "gex": None if L["GEX"] is None else round(L["GEX"] / 1e9, 2), "gexp": L["GEXp"],
        "spx": L["SPX"], "spxChg": (L["SPX"] / prev["SPX"] - 1) * 100,
        "quiet": L["c"], "peak": L["peak"], "evBase": L["ev_base"],
        "score": None if L["score"] is None else round(L["score"], 1), "scoreN": L["scoreN"], "band": band_of(L["score"]),
        "scorePrev": None if prev["score"] is None else round(prev["score"], 1),
        "A": L["A"], "B": L["B"], "C": L["C"], "aS": tail("A"), "bS": tail("B"), "cS": tail("C"), "scoreS": tail("score"),
    }
    since_peak = sum(1 for r in rows if r["d"] > live["peakd"]) if L["st"] and live else None

    hs = [e["half"] for e in evs if e["half"]]
    qs = [e["quarter"] for e in evs if e["quarter"]]
    decay_med = []
    for t in range(16):
        v = [e["decay"][t] for e in evs if not e["live"] and len(e["decay"]) > t]
        if len(v) >= 5:
            decay_med.append(round(stats.median(v), 3))

    def alert(id_, name, rule, on, now, kind="bad"):
        return {"id": id_, "name": name, "rule": rule, "on": bool(on), "now": now, "kind": kind}

    k2s = [f"{e['dte']} 日 {e['k2']:,}" for e in (opt or {}).get("exps", []) if e["k2"]]
    pf = lambda v: "—" if v is None else f"{v:.0f}"
    sc = "無資料" if L["score"] is None else f"{L['score']:.0f}（{BINS[band_of(L['score'])][2]}）"
    alerts = [
        alert("hi", "指數進入高區", "共識崩塌指數 ≥ 75", L["score"] is not None and L["score"] >= 75, sc),
        alert("mid", "指數偏高", "共識崩塌指數 ≥ 60", L["score"] is not None and L["score"] >= 60, sc),
        alert("flip", "翻轉觸發", "VIX ≥ VIX3M 且 VIX ≥ 前 20 日中位數 ×1.25", L["st"] == 1, f"VIX/VIX3M {L['ratio']:.2f}"),
        alert("recover", "進入恐慌回落", "VIX ≤ 事件高點 ×0.85", L["st"] == 2, "未在事件中" if not L["peak"] else f"VIX {L['VIX']:.2f}／門檻 {L['peak'] * RECOVER_DROP:.2f}", "good"),
        alert("peak2", "定價分布出現第二峰", "下方局部高點 ≥ 主峰 3%、谷深 ≥ 20%，兩種帶寬都成立", bool(k2s), "、".join(k2s) or "未出現"),
    ]

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "asof": L["d"],
        "phase": phase, "phaseName": PHASES[phase], "st": L["st"], "sig": sig, "sincePeak": since_peak,
        "alerts": alerts, "opt": opt, "optStale": opt_stale, "events": evs[::-1], "backtest": bt, "cal": cal, "bins": BINS, "decayMed": decay_med,
        "halfMed": stats.median(hs), "quarterMed": stats.median(qs), "evCount": len(evs),
        "kospi": {"y": L["d"][:4], "n": sum(1 for c in cb if c["d"].startswith(L["d"][:4])), "last": cb[-1] if cb else None},
        "sources": sources, "stale": stale, "errs": errs,
    }
    with open(os.path.join(DATA_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DATA_DIR, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.RADAR=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";")
    hist = {"px": px, "bands": bands, "score": [[r["d"], round(r["score"], 1)] for r in rows if r["d"] >= "2016-01-01" and r["score"] is not None]}
    with open(os.path.join(DATA_DIR, "history.js"), "w", encoding="utf-8") as f:
        f.write("window.RADAR_HIST=" + json.dumps(hist, ensure_ascii=False, separators=(",", ":")) + ";")
    print(f"[ok] {L['d']} 指數 {sig['score']}（{L['scoreN']} 成分）｜階段 {PHASES[phase]}｜VIX {L['VIX']} SKEW {L['SKEW']} COR3M {L['COR3M']} GEX {sig['gex']}｜事件 {len(evs)}｜半衰期中位 {stats.median(hs)} 日")
    for s in sources:
        print(f"  [{'ok' if s['ok'] else '停更'}] {s['name']} {s['asof']} {s['note']}")
    for e in errs:
        print("  [err]", e)
    notify(out)


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
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=urllib.parse.urlencode(body).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def notify(out):
    """DAILY=1：每天推日報。未設：只在階段、警示或資料停更變化時推。沒設 token 時只印出，不送出。"""
    old = load_prior(STATE) or {}
    new = {"phase": out["phase"], "band": out["sig"]["band"], "stale": out["stale"], **{a["id"]: a["on"] for a in out["alerts"]}}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False)
    E = html.escape
    lines = [f"<b>共識崩塌雷達｜{E(out['phaseName'])}</b>"]
    changed = "phase" in old and old["phase"] != out["phase"]
    if changed:
        lines.append(f"🔔 階段變化：{PHASES[old['phase']]} → {out['phaseName']}")
    s = out["sig"]
    lines[0] = f"<b>共識崩塌指數 {s['score']:.0f}／100（{out['bins'][s['band']][2]}）｜{E(out['phaseName'])}</b>" if s["score"] is not None else lines[0]
    if old.get("band") is not None and s["band"] is not None and old["band"] != s["band"]:
        changed = True
        lines.append(f"🔔 區間變化：{out['bins'][old['band']][2]} → {out['bins'][s['band']][2]}")
    lines += ["", f"翻轉 {s['A']:.0f}　同步 {s['B']:.0f}　Gamma 偏低 {s['C']:.0f}（5 年百分位）" if None not in (s["A"], s["B"], s["C"]) else "成分有缺，見頁面",
              f"VIX {s['vix']:.2f}　VIX/VIX3M {s['ratio']:.2f}"]
    flips = [a for a in out["alerts"] if a["id"] in old and old[a["id"]] != a["on"]]
    if flips:
        changed = True
        lines += ["", "<b>變化</b>"] + [f"{'🔴' if a['on'] else '⚪'} {E(a['name'])}{'觸發' if a['on'] else '解除'}：{E(a['now'])}" for a in flips]
    on = [a for a in out["alerts"] if a["on"]]
    lines += ["", "<b>觸發中</b>" if on else "觸發中：無"] + [f"• {E(a['name'])}：{E(a['now'])}" for a in on]
    if sorted(old.get("stale", [])) != sorted(out["stale"]):
        changed = True
    if out["stale"]:
        lines += ["", f"⚠️ 資料停更：{E('、'.join(out['stale']))}"]
    url = os.environ.get("DASHBOARD_URL")
    if url:
        lines += ["", E(url)]
    msg = "\n".join(lines)
    if not (os.environ.get("DAILY") or changed):
        print("[tg] 無變化，不推播")
        return
    tok, chat = _token(), os.environ.get("TG_CHAT_ID")
    if not (tok and chat):
        print("[tg] 未設定 token／TG_CHAT_ID，預定推播內容：\n" + msg)
        return
    print("[tg] 已推播", _send(tok, chat, msg))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        tok, chat = _token(), os.environ.get("TG_CHAT_ID")
        if tok and chat:
            body = urllib.parse.urlencode({"chat_id": chat, "text": f"⚠️ 共識崩塌雷達執行失敗：{str(e)[:300]}"}).encode()
            urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body), timeout=30)
        raise
