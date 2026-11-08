# -*- coding: utf-8 -*-
"""模擬來源故障，確認備援與停更標示正常。輸出寫到暫存目錄，不動 data/。 py scripts/test_fallback.py"""
import json, os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import update as u

SRC = u.DATA_DIR
real = {k: getattr(u, k) for k in ("cboe", "yahoo", "options", "squeeze_gex", "naver_kospi")}
results = []


def boom(*a, **k):
    raise ConnectionError("模擬故障")


def scenario(name, patch, check):
    tmp = tempfile.mkdtemp(prefix="radar-", dir=os.environ.get("TEMP"))
    d = os.path.join(tmp, "data")
    shutil.copytree(SRC, d)
    u.DATA_DIR, u.STATE, u.SNAP = d, os.path.join(d, "state.json"), os.path.join(d, "snapshots.json")
    for k, v in real.items():
        setattr(u, k, v)
    patch()
    out = None
    try:
        u.main()
        with open(os.path.join(d, "data.json"), encoding="utf-8") as f:
            out = json.load(f)
        with open(os.path.join(d, "history.js"), encoding="utf-8") as f:
            hist = json.loads(f.read()[len("window.RADAR_HIST="):].rstrip(";"))
        ok, why = check(out, hist)
    except Exception as e:
        ok, why = check(None, None) if name.startswith("主備") else (False, f"未預期例外：{e}")
    results.append(ok)
    print(f"\n{'通過' if ok else '失敗'}｜{name}：{why}\n")
    shutil.rmtree(tmp, ignore_errors=True)


def p_cboe_vix():
    orig = real["cboe"]
    u.cboe = lambda s: boom() if s == "VIX" else orig(s)


def p_all_critical():
    u.cboe = boom
    u.yahoo = boom


def p_opt():
    u.options = boom


def p_gex():
    u.squeeze_gex = boom


def p_ks():
    orig = real["yahoo"]
    u.yahoo = lambda s, rng="10y": boom() if s == "^KS11" else orig(s, rng)


def p_ks_both():
    orig = real["yahoo"]
    u.yahoo = lambda s, rng="10y": boom() if s in ("^KS11", "^GSPC", "^NDX") else orig(s, rng)
    u.naver_kospi = boom


scenario("Cboe VIX 故障", p_cboe_vix, lambda o, h: (o["sources"][0]["note"].startswith("VIX 改用 Yahoo") and o["phase"] in (1, 2, 3), f"階段 {o['phaseName']}｜{o['sources'][0]['note']}"))
scenario("期權鏈故障", p_opt, lambda o, h: (o["optStale"] and bool(o["opt"]["exps"]), f"沿用上次 {len(o['opt']['exps'])} 組到期日｜{o['sources'][1]['note']}"))
scenario("SqueezeMetrics 故障", p_gex, lambda o, h: (o["sig"]["gex"] is None and "做市商 Gamma" in o["stale"] and o["sig"]["scoreN"] == 2 and o["sig"]["score"] is not None and o["cal"].get("stale"), f"指數以 {o['sig']['scoreN']} 項算出 {o['sig']['score']}、校準沿用上次｜停更 {o['stale']}"))
scenario("Yahoo KOSPI 故障", p_ks, lambda o, h: ("KOSPI Naver 備援" in o["sources"][3]["note"] and len(h["px"]["KOSPI"]) > 2000 and o["kospi"]["n"] == 12, f"Naver 取得 {len(h['px']['KOSPI'])} 筆，今年代理 {o['kospi']['n']} 日"))
scenario("K 線來源全斷", p_ks_both, lambda o, h: (all(k in h["px"] for k in ("SPX", "NDX", "KOSPI")) and "上次快取" in o["sources"][3]["note"], f"{o['sources'][3]['note']}"))
scenario("主備來源皆斷", p_all_critical, lambda o, h: (o is None, "中止且未覆寫資料"))
print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
