# -*- coding: utf-8 -*-
"""Breeden-Litzenberger：由選擇權價格反推市場定價用的機率分布，並偵測下方第二峰。只用標準庫。"""
import math


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_w(F, K, w, cp):
    """不折現 Black 價；w = 總變異數 σ²T。"""
    if w <= 0:
        return max(0.0, F - K) if cp == "C" else max(0.0, K - F)
    s = math.sqrt(w)
    d1 = (math.log(F / K) + 0.5 * w) / s
    d2 = d1 - s
    return F * phi(d1) - K * phi(d2) if cp == "C" else K * phi(-d2) - F * phi(-d1)


def implied_w(F, K, price, cp):
    """由價格反解總變異數；無解回 None。"""
    intrinsic = max(0.0, F - K) if cp == "C" else max(0.0, K - F)
    if price <= intrinsic:
        return None
    lo, hi = 1e-7, 4.0
    for _ in range(60):
        m = (lo + hi) / 2
        if bs_w(F, K, m, cp) > price:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def _solve3(a, b):
    """3x3 高斯消去；奇異回 None。"""
    m = [a[i][:] + [b[i]] for i in range(3)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(m[r][i]))
        if abs(m[p][i]) < 1e-14:
            return None
        m[i], m[p] = m[p], m[i]
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]
                for c in range(i, 4):
                    m[r][c] -= f * m[i][c]
    return [m[i][3] / m[i][i] for i in range(3)]


def smooth_w(xs, ws, x0, h):
    """以局部二次迴歸平滑總變異數曲線。"""
    S = [[0.0] * 3 for _ in range(3)]
    T = [0.0] * 3
    for x, w in zip(xs, ws):
        u = (x - x0) / h
        if abs(u) > 3.5:
            continue
        g = math.exp(-0.5 * u * u)
        v = (1.0, x - x0, (x - x0) ** 2)
        for i in range(3):
            T[i] += g * v[i] * w
            for j in range(3):
                S[i][j] += g * v[i] * v[j]
    sol = _solve3(S, T)
    return None if sol is None else sol[0]


def density(pts, F, h, step=0.0025, lo=-0.40, hi=0.15):
    """pts=[(K, w)]。回傳等距履約價上的密度與累積機率。"""
    pts = sorted(pts)
    xs = [math.log(k / F) for k, _ in pts]
    ws = [w for _, w in pts]
    lo = max(lo, xs[0])
    hi = min(hi, xs[-1])
    dK = F * step
    n = int((F * math.exp(hi) - F * math.exp(lo)) / dK)
    Ks = [F * math.exp(lo) + i * dK for i in range(n + 1)]
    Cs, ok = [], []
    for K in Ks:
        w = smooth_w(xs, ws, math.log(K / F), h)
        if w is None or w <= 0:
            Cs.append(None)
        else:
            Cs.append(bs_w(F, K, w, "C"))
    out = []
    for i in range(1, n):
        if None in (Cs[i - 1], Cs[i], Cs[i + 1]):
            continue
        q = (Cs[i + 1] - 2 * Cs[i] + Cs[i - 1]) / dK ** 2
        P = 1 + (Cs[i + 1] - Cs[i - 1]) / (2 * dK)
        out.append([Ks[i], max(q, 0.0), min(max(P, 0.0), 1.0)])
    return out


def _peaks(d, F, floor=0.03, prominence=0.20):
    """找主峰與其下方的局部高點；要求高度與谷深都達門檻，避免把雜訊當成峰。"""
    if len(d) < 8:
        return None, []
    qs = [r[1] for r in d]
    im = max(range(len(qs)), key=lambda i: qs[i])
    res = []
    for i in range(2, im - 1):
        if qs[i] >= qs[i - 1] and qs[i] > qs[i + 1] and qs[i] >= floor * qs[im] and d[i][0] < d[im][0] * 0.98:
            valley = min(qs[i:im + 1])
            if qs[i] > 0 and (qs[i] - valley) / qs[i] >= prominence:
                res.append(i)
    return im, res


def second_peak(pts, F, atm_w):
    """在兩種平滑帶寬下都存在才算數，降低對單一參數的依賴。回傳 (K2, h, 主密度)。"""
    h1 = max(0.35 * math.sqrt(atm_w), 0.006)
    d1 = density(pts, F, h1)
    im1, p1 = _peaks(d1, F)
    d2 = density(pts, F, h1 * 1.5)
    _, p2 = _peaks(d2, F)
    k2 = None
    for i in reversed(p1):  # 由靠近主峰者往下找
        K = d1[i][0]
        if any(abs(d2[j][0] / K - 1) < 0.02 for j in p2):
            k2 = K
            break
    return k2, h1, d1
