# -*- coding: utf-8 -*-
"""第二峰偵測器的已知答案測試：單峰不得報峰、雙峰要報在正確位置。 py scripts/test_bl.py"""
import math, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import bl

F = 7400.0


def mix(comps, K, cp):
    """對數常態混合的選擇權價（forward 由各成分 mean 加權）。comps=[(權重, 均值, w)]"""
    return sum(a * bl.bs_w(m, K, w, cp) for a, m, w in comps)


def chain(comps, noise=0.0, seed=1):
    rnd = random.Random(seed)
    fwd = sum(a * m for a, m, _ in comps)
    pts = []
    for K in range(int(fwd * 0.62), int(fwd * 1.14), 5):
        cp = "P" if K < fwd else "C"
        p = mix(comps, K, cp)
        if p < 0.05:
            continue
        p *= 1 + noise * rnd.uniform(-1, 1)
        w = bl.implied_w(fwd, K, p, cp)
        if w:
            pts.append((K, w))
    return fwd, pts


def run(name, comps, expect, noise=0.0):
    fwd, pts = chain(comps, noise)
    atm = min(pts, key=lambda r: abs(r[0] - fwd))[1]
    k2, h, d = bl.second_peak(pts, fwd, atm)
    if expect is None:
        ok = k2 is None
    else:
        ok = k2 is not None and abs(k2 / expect - 1) < 0.02
    print(f"{'通過' if ok else '失敗'}  {name}：期望 {expect}，偵測 {None if k2 is None else round(k2)}")
    return ok


T30 = 30 / 365
res = [
    run("單峰對數常態", [(1, F, 0.20 ** 2 * T30)], None),
    run("單峰＋0.5% 報價雜訊", [(1, F, 0.20 ** 2 * T30)], None, 0.005),
    run("左偏厚尾但單峰", [(0.75, F * 1.01, 0.13 ** 2 * T30), (0.25, F * 0.97, 0.32 ** 2 * T30)], None),
    run("雙峰：12% 權重落在 -12%", [(0.88, F * 1.016, 0.11 ** 2 * T30), (0.12, F * 0.88, 0.10 ** 2 * T30)], F * 0.88),
    run("雙峰：20% 權重落在 -15%", [(0.80, F * 1.03, 0.10 ** 2 * T30), (0.20, F * 0.85, 0.10 ** 2 * T30)], F * 0.85),
    run("雙峰＋0.5% 報價雜訊", [(0.85, F * 1.02, 0.11 ** 2 * T30), (0.15, F * 0.88, 0.10 ** 2 * T30)], F * 0.88, 0.005),
]
print(f"{sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)
