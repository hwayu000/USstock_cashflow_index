# -*- coding: utf-8 -*-
"""歷次錢荒回推：用與儀表板相同的口徑，把 2018 年以來每一天判成 錢荒／補水／修復，
並抓 NQ、ES、黃金日線，算出每次事件期間指數的表現。輸出 data/history.json 與 history.js。

資料源（皆免金鑰）：
  SOFR、聯邦基金目標區間 → 紐約聯儲 Markets API
  SOMA 短債持有（算 RMP 四週增持）→ 紐約聯儲 SOMA summary
  NQ=F、ES=F、GC=F 日線 → Yahoo

IORB（2021/7 前為 IOER）= 目標區間上限 + 技術調整（下表），與聯儲公告一致。

判定規則（逐日狀態機）：
  進入錢荒：近 5 個交易日中有 ≥3 天 SOFR−IORB > 5bp（排除月底一兩天的跳升）
  轉入補水：錢荒中 RMP（SOMA 短債四週增持）≥ 200 億美元
  錢荒解除：SOFR−IORB 連續 3 個交易日 ≤ 0（與儀表板「錢荒解除」推播條件相同）
  修復期　：解除後 20 個交易日
"""
import bisect, json, os, sys, time, urllib.request
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "history.json")
UA = {"User-Agent": "Mozilla/5.0 (gold-liquidity-dashboard)"}
BEGIN = "2018-04-02"  # SOFR 起始日

# IOER／IORB 相對目標區間上限的技術調整（bp），生效日起算
IOR_OFFSET = [("2000-01-01", 0), ("2018-06-14", -5), ("2018-12-20", -10), ("2019-05-02", -15),
              ("2019-09-19", -20), ("2020-01-30", -15), ("2021-06-17", -10)]

SYMS = [("NQ", "NQ=F", "那斯達克 100 期貨"), ("ES", "ES=F", "標普 500 期貨"), ("GC", "GC=F", "黃金期貨")]
RECOVER_DAYS = 20
AFTER_DAYS = 60

# 事件名稱（依起始日對應；未列出者用年月）
NAMES = {"2018-12": "2018 年底", "2019-04": "2019 上半", "2019-09": "2019/9 回購危機",
         "2020-03": "2020/3 疫情", "2024-12": "2024 年底", "2025-10": "2025/10"}


def get(url, tries=4, deadline=90):
    """總時限保護（同 update.py）：避免對方極慢吐資料時無限拖住。"""
    for i in range(tries):
        try:
            t0 = time.time()
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                buf = []
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    buf.append(chunk)
                    if time.time() - t0 > deadline:
                        raise TimeoutError(f"超過總時限 {deadline}s")
                return b"".join(buf).decode("utf-8")
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(4 * (i + 1))


def nyfed(path):
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = json.loads(get(f"https://markets.newyorkfed.org/api/rates/{path}/search.json?startDate={BEGIN}&endDate={end}"))["refRates"]
    return {r["effectiveDate"]: r for r in rows}


def soma_bills():
    rows = json.loads(get("https://markets.newyorkfed.org/api/soma/summary.json"))["soma"]["summary"]
    return [(r["asOfDate"], float(r["bills"]) / 1e9) for r in rows if r["asOfDate"] >= "2017-12-01"]


def yahoo_ohlc(sym):
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1522627200&period2=4102444800&interval=1d"))
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out, seen = [], set()
    for t, o, h, l, c in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
        if d in seen:
            continue
        seen.add(d)
        out.append([d, round(o, 2), round(h, 2), round(l, 2), round(c, 2)])
    return out


def offset(d):
    return [o for dd, o in IOR_OFFSET if dd <= d][-1]


def build():
    sofr, effr = nyfed("secured/sofr"), nyfed("unsecured/effr")
    spread = [(d, round((sofr[d]["percentRate"] - effr[d]["targetRateTo"]) * 100 - offset(d), 1))
              for d in sorted(sofr) if d in effr]

    bills = soma_bills()
    rmp = [(bills[i][0], bills[i][1] - bills[i - 4][1]) for i in range(4, len(bills))]
    rd = [d for d, _ in rmp]

    def rmp_at(d):
        i = bisect.bisect_right(rd, d) - 1
        return rmp[i][1] if i >= 0 else 0

    # 逐日狀態機
    bands, st, left = [], "normal", 0
    for i, (d, v) in enumerate(spread):
        win = [x for _, x in spread[max(0, i - 4):i + 1]]
        if st in ("normal", "recover") and sum(x > 5 for x in win) >= 3:
            st = "crunch"
        elif st in ("crunch", "refill"):
            if i >= 2 and all(x <= 0 for _, x in spread[i - 2:i + 1]):
                st, left = "recover", RECOVER_DAYS
            elif st == "crunch" and rmp_at(d) >= 20:
                st = "refill"
        elif st == "recover":
            left -= 1
            if left <= 0:
                st = "normal"
        if bands and bands[-1]["phase"] == st:
            bands[-1]["to"] = d
        else:
            bands.append({"phase": st, "from": d, "to": d})
    live_phase = bands[-1]["phase"] if bands else "normal"
    bands = [b for b in bands if b["phase"] != "normal"]

    # 本次：最近一段連續 SOFR > IORB（尚未達歷史進場門檻時，單獨標「進行中」）
    cur_from = None
    for d, v in reversed(spread):
        if v > 0:
            cur_from = d
        else:
            break

    # 把 錢荒→補水→修復 串成事件
    episodes = []
    for b in bands:
        if b["phase"] == "crunch":
            key = b["from"][:7]
            episodes.append({"key": key, "name": NAMES.get(key, key.replace("-", "/")), "crunch": [b["from"], b["to"]]})
        elif episodes:
            episodes[-1][b["phase"]] = [b["from"], b["to"]]
    for e in episodes:
        seg = [x for d, x in spread if e["crunch"][0] <= d <= e["crunch"][1]]
        e["peak"] = max(seg) if seg else None
        e["days"] = len(seg)

    live = None
    if live_phase in ("crunch", "refill") and episodes:
        live = episodes[-1]["crunch"][0]
    elif cur_from:
        live = cur_from
    if live:
        seg = [x for d, x in spread if d >= live]
        now = {"key": "now", "name": "本次（進行中）", "crunch": [live, spread[-1][0]], "peak": max(seg), "days": len(seg), "live": True}
        if live_phase in ("crunch", "refill") and episodes and episodes[-1]["crunch"][0] == live:
            episodes[-1].update(now)
        else:
            episodes.append(now)

    # 指數日線與事件表現
    px, stats = {}, {}
    for key, sym, _ in SYMS:
        try:
            px[key] = yahoo_ohlc(sym)
        except Exception as ex:
            print("[err] yahoo", sym, ex)
            px[key] = []
    for e in episodes:
        e["stats"] = {}
        for key, _, _ in SYMS:
            rows = px[key]
            if not rows:
                continue
            dates = [r[0] for r in rows]
            i0 = max(0, bisect.bisect_left(dates, e["crunch"][0]) - 1)  # 錢荒前一日收盤為基準
            end = e.get("refill", e["crunch"])[1] if "refill" in e else e["crunch"][1]
            i1 = min(len(rows) - 1, bisect.bisect_right(dates, end) - 1)
            base = rows[i0][4]
            low = min(r[3] for r in rows[i0:i1 + 1])
            s = {"during": round((rows[i1][4] / base - 1) * 100, 1), "dd": round((low / base - 1) * 100, 1)}
            if "recover" in e:
                j0 = bisect.bisect_left(dates, e["recover"][0])
                j1 = j0 + AFTER_DAYS
                if j0 < len(rows) and j1 < len(rows):
                    s["after"] = round((rows[j1][4] / rows[j0][4] - 1) * 100, 1)
            e["stats"][key] = s

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "rule": {"enter": "5 日內 ≥3 天 SOFR−IORB > 5bp", "refill": "RMP 四週增持 ≥ 200 億美元",
                 "exit": "SOFR−IORB 連續 3 日 ≤ 0", "recover": f"解除後 {RECOVER_DAYS} 個交易日", "after": AFTER_DAYS},
        "symbols": [{"key": k, "sym": s, "name": n} for k, s, n in SYMS],
        "bands": bands, "episodes": episodes, "px": px,
        "spread": [[d, v] for d, v in spread],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    txt = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(OUT[:-2], "w", encoding="utf-8") as f:
        f.write("window.HIST=" + txt + ";")
    print(f"[ok] history 區段={len(bands)} 事件={len(episodes)} " + " ".join(f"{k}={len(v)}" for k, v in px.items()))
    for e in episodes:
        print("  ", e["name"], e["crunch"], "補水" if "refill" in e else "", "修復" if "recover" in e else "", e["stats"])
    return out


if __name__ == "__main__":
    build()
