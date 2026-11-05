"""纯 Python 技术指标库（无第三方依赖）。

所有函数返回与输入等长的列表，预热期为 None。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

Num = Optional[float]


# ---------------------------------------------------------------- 基础工具
def sma(values: Sequence[Num], n: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    s = 0.0
    cnt = 0
    for i, v in enumerate(values):
        if v is None:
            continue
        s += v
        cnt += 1
        if cnt > n:
            s -= values[i - n]  # type: ignore[operator]
            cnt = n
        if cnt == n:
            out[i] = s / n
    return out


def ema(values: Sequence[Num], n: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    k = 2.0 / (n + 1)
    prev: Num = None
    seed: List[float] = []
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == n:
                prev = sum(seed) / n
                out[i] = prev
        else:
            prev = v * k + prev * (1 - k)
            out[i] = prev
    return out


def rma(values: Sequence[Num], n: int) -> List[Num]:
    """Wilder 平滑（RMA）。"""
    out: List[Num] = [None] * len(values)
    prev: Num = None
    seed: List[float] = []
    for i, v in enumerate(values):
        if v is None:
            continue
        if prev is None:
            seed.append(v)
            if len(seed) == n:
                prev = sum(seed) / n
                out[i] = prev
        else:
            prev = (prev * (n - 1) + v) / n
            out[i] = prev
    return out


def stdev(values: Sequence[Num], n: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    for i in range(n - 1, len(values)):
        win = values[i - n + 1 : i + 1]
        if any(v is None for v in win):
            continue
        m = sum(win) / n  # type: ignore[arg-type]
        var = sum((v - m) ** 2 for v in win) / n  # type: ignore[operator]
        out[i] = math.sqrt(var)
    return out


def rsi(closes: Sequence[float], n: int = 14) -> List[Num]:
    gains: List[Num] = [None]
    losses: List[Num] = [None]
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = rma(gains, n)
    al = rma(losses, n)
    out: List[Num] = [None] * len(closes)
    for i in range(len(closes)):
        if ag[i] is None or al[i] is None:
            continue
        if al[i] == 0:
            out[i] = 50.0 if ag[i] == 0 else 100.0
        else:
            rs = ag[i] / al[i]  # type: ignore[operator]
            out[i] = 100 - 100 / (1 + rs)
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, sig: int = 9):
    ef = ema(closes, fast)
    es = ema(closes, slow)
    dif: List[Num] = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    dea = ema(dif, sig)
    hist: List[Num] = [None if (a is None or b is None) else (a - b) * 2 for a, b in zip(dif, dea)]
    return dif, dea, hist


def true_range(highs, lows, closes) -> List[Num]:
    out: List[Num] = [None] * len(closes)
    for i in range(1, len(closes)):
        out[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return out


def atr(highs, lows, closes, n: int = 14) -> List[Num]:
    return rma(true_range(highs, lows, closes), n)


def adx(highs, lows, closes, n: int = 14):
    tr = true_range(highs, lows, closes)
    pdm: List[Num] = [None] * len(closes)
    mdm: List[Num] = [None] * len(closes)
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
    str_ = rma(tr, n)
    spdm = rma(pdm, n)
    smdm = rma(mdm, n)
    pdi: List[Num] = [None] * len(closes)
    mdi: List[Num] = [None] * len(closes)
    dx: List[Num] = [None] * len(closes)
    for i in range(len(closes)):
        if str_[i] in (None, 0) or spdm[i] is None or smdm[i] is None:
            continue
        pdi[i] = 100 * spdm[i] / str_[i]  # type: ignore[operator]
        mdi[i] = 100 * smdm[i] / str_[i]  # type: ignore[operator]
        denom = pdi[i] + mdi[i]
        dx[i] = 0.0 if not denom else 100 * abs(pdi[i] - mdi[i]) / denom
    return rma(dx, n), pdi, mdi


def bollinger(closes, n: int = 20, mult: float = 2.0):
    mid = sma(closes, n)
    sd = stdev(closes, n)
    up: List[Num] = []
    lo: List[Num] = []
    for m, s in zip(mid, sd):
        if m is None or s is None:
            up.append(None)
            lo.append(None)
        else:
            up.append(m + mult * s)
            lo.append(m - mult * s)
    return up, mid, lo


def kdj(highs, lows, closes, n: int = 9, k_period: int = 3, d_period: int = 3):
    k_out: List[Num] = [None] * len(closes)
    d_out: List[Num] = [None] * len(closes)
    j_out: List[Num] = [None] * len(closes)
    k_prev = 50.0
    d_prev = 50.0
    for i in range(len(closes)):
        if i < n - 1:
            continue
        hh = max(highs[i - n + 1 : i + 1])
        ll = min(lows[i - n + 1 : i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k_prev = (k_period - 1) / k_period * k_prev + rsv / k_period
        d_prev = (d_period - 1) / d_period * d_prev + k_prev / d_period
        k_out[i] = k_prev
        d_out[i] = d_prev
        j_out[i] = 3 * k_prev - 2 * d_prev
    return k_out, d_out, j_out


def obv(closes, volumes):
    out: List[Num] = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out.append(out[-1] + volumes[i])  # type: ignore[operator]
        elif closes[i] < closes[i - 1]:
            out.append(out[-1] - volumes[i])
        else:
            out.append(out[-1])
    return out


def cci(highs, lows, closes, n: int = 20) -> List[Num]:
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    ma = sma(tp, n)
    out: List[Num] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        win = tp[i - n + 1 : i + 1]
        dev = sum(abs(x - ma[i]) for x in win) / n  # type: ignore[operator]
        if dev == 0:
            continue
        out[i] = (tp[i] - ma[i]) / (0.015 * dev)  # type: ignore[operator]
    return out


# ---------------------------------------------------------------- 统计工具
def linreg(y: Sequence[float]):
    """返回 (斜率, 截距, R²)。"""
    n = len(y)
    if n < 3:
        return 0.0, 0.0, 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(y) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (v - my) for x, v in zip(xs, y))
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((v - my) ** 2 for v in y)
    ss_res = sum((v - (slope * x + intercept)) ** 2 for x, v in zip(xs, y))
    r2 = 0.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return slope, intercept, max(0.0, min(1.0, r2))


def percentile_rank(values: Sequence[Num], v: float) -> float:
    vals = [x for x in values if x is not None]
    if not vals:
        return 50.0
    cnt = sum(1 for x in vals if x <= v)
    return cnt / len(vals) * 100


def slope_pct(values: Sequence[Num], lookback: int = 10) -> Num:
    vals = [x for x in values if x is not None]
    if len(vals) < lookback + 1:
        return None
    a, b = vals[-lookback - 1], vals[-1]
    if not a:
        return None
    return (b - a) / a * 100


def clip(v: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def compute_all(candles) -> dict:
    """candles: list of dict(t,o,h,l,c,v) -> 指标字典"""
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    vols = [c.get("v") or 0.0 for c in candles]

    dif, dea, hist = macd(closes)
    a, pdi, mdi = adx(highs, lows, closes, 14)
    bu, bm, bl = bollinger(closes, 20, 2.0)
    k, d, j = kdj(highs, lows, closes)
    _atr = atr(highs, lows, closes, 14)

    ind = {
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema100": ema(closes, 100),
        "ema200": ema(closes, 200),
        "sma20": sma(closes, 20),
        "macd_dif": dif,
        "macd_dea": dea,
        "macd_hist": hist,
        "rsi14": rsi(closes, 14),
        "rsi6": rsi(closes, 6),
        "atr": _atr,
        "adx": a,
        "pdi": pdi,
        "mdi": mdi,
        "bb_up": bu,
        "bb_mid": bm,
        "bb_low": bl,
        "k": k,
        "d": d,
        "j": j,
        "obv": obv(closes, vols),
        "vol_ma5": sma(vols, 5),
        "vol_ma20": sma(vols, 20),
        "cci": cci(highs, lows, closes, 20),
    }
    return ind
