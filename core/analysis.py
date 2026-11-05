"""技术分析引擎：指标结构解读 + 趋势评分 + 关键价位 + 交易计划。"""
from __future__ import annotations

import math
from typing import Optional

from . import indicators as ta

Num = Optional[float]


# ---------------------------------------------------------------- 小工具
def _last(arr, off: int = 0) -> Num:
    if not arr:
        return None
    idx = len(arr) - 1 - off
    if idx < 0:
        return None
    v = arr[idx]
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def _round(v: float, digits: int = 2) -> float:
    if v is None or not math.isfinite(v):
        return 0.0
    if abs(v) >= 1000:
        return round(v, 2)
    if abs(v) >= 10:
        return round(v, 2)
    if abs(v) >= 1:
        return round(v, 3)
    return round(v, 5)


def fmt_price(v: float) -> float:
    return _round(v, 6)


def money(v: float) -> str:
    """带千分位的价格字符串。"""
    if v is None or not math.isfinite(v):
        return "—"
    a = abs(v)
    if a >= 100:
        return f"{v:,.2f}"
    if a >= 1:
        return f"{v:,.3f}"
    return f"{v:,.5f}"


# ---------------------------------------------------------------- 摆动结构
def find_swings(candles, k: int = 3):
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    n = len(candles)
    out = []
    for i in range(k, n - k):
        wh = highs[i - k : i + k + 1]
        if highs[i] == max(wh) and wh.count(highs[i]) == 1:
            out.append({"i": i, "type": "high", "price": highs[i]})
        wl = lows[i - k : i + k + 1]
        if lows[i] == min(wl) and wl.count(lows[i]) == 1:
            out.append({"i": i, "type": "low", "price": lows[i]})
    out.sort(key=lambda x: x["i"])
    alt = []
    for p in out:
        if alt and alt[-1]["type"] == p["type"]:
            better = (p["type"] == "high" and p["price"] > alt[-1]["price"]) or (
                p["type"] == "low" and p["price"] < alt[-1]["price"]
            )
            if better:
                alt[-1] = p
        else:
            alt.append(p)
    return alt


def structure_report(candles, swings, close: float):
    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]
    n = len(candles)
    pattern = "mixed"
    label = "结构混合"
    detail = "摆动高低点未形成清晰序列"
    score = 0.0

    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2]["price"], highs[-1]["price"]
        l1, l2 = lows[-2]["price"], lows[-1]["price"]
        hh, hl, lh, ll = h2 > h1, l2 > l1, h2 < h1, l2 < l1
        if hh and hl:
            pattern, label = "up", "上升结构 · HH/HL"
            detail = "高点抬高、低点抬高，多头结构完整"
            score = 80
        elif lh and ll:
            pattern, label = "down", "下降结构 · LH/LL"
            detail = "高点降低、低点降低，空头结构完整"
            score = -80
        elif hh and ll:
            pattern, label = "expanding", "扩张结构"
            detail = "高低点同时外扩，波动放大，方向待选择"
            score = 5
        elif lh and hl:
            pattern, label = "contracting", "收敛结构"
            detail = "高低点同时内收，正在压缩，等待突破"
            score = 0
        else:
            detail = "高低点序列交错，趋势性不足"

    breakout = None
    if highs and close > highs[-1]["price"] and (n - 1 - highs[-1]["i"]) <= 60:
        breakout = "up"
        score += 18
    elif lows and close < lows[-1]["price"] and (n - 1 - lows[-1]["i"]) <= 60:
        breakout = "down"
        score -= 18

    recent = [s for s in swings if n - 1 - s["i"] <= 160][-8:]
    for s in recent:
        s["t"] = candles[s["i"]]["t"]
    return {
        "pattern": pattern,
        "label": label,
        "detail": detail,
        "score": ta.clip(score),
        "breakout": breakout,
        "swings": [{"t": s["t"], "price": fmt_price(s["price"]), "type": s["type"]} for s in recent],
        "last_high": fmt_price(highs[-1]["price"]) if highs else None,
        "last_low": fmt_price(lows[-1]["price"]) if lows else None,
    }


# ---------------------------------------------------------------- 关键价位
def build_levels(candles, swings, ind, close: float, atr_v: float, market: str):
    n = len(candles)
    pts = []
    for s in swings[-14:]:
        age = n - 1 - s["i"]
        if age > 300:
            continue
        w = 1.0 + 0.9 * max(0.0, 1 - age / 300)
        pts.append((s["price"], w, s["type"]))
    for lb, w in ((20, 1.1), (60, 1.0), (250, 0.8)):
        if n > lb + 2:
            pts.append((max(c["h"] for c in candles[-lb:]), w, "range"))
            pts.append((min(c["l"] for c in candles[-lb:]), w, "range"))
    e200 = _last(ind["ema200"])
    if e200:
        pts.append((e200, 1.3, "ema"))

    tol = max(atr_v * 0.6, close * 0.0015)
    clusters = []
    for price, w, kind in sorted(pts, key=lambda x: x[0]):
        # 与簇均值比较，避免逐点漂移把整段价位合并成一大簇
        if clusters and price - clusters[-1]["mean"] <= tol:
            c = clusters[-1]
            c["values"].append(price)
            c["weight"] += w
            c["kinds"].add(kind)
            c["mean"] = sum(c["values"]) / len(c["values"])
        else:
            clusters.append({"values": [price], "weight": w, "kinds": {kind}, "mean": price})

    levels = []
    for c in clusters:
        price = sum(c["values"]) / len(c["values"])
        touches = len(c["values"])
        strength = min(100.0, 24 + touches * 11 + c["weight"] * 8)
        kinds = c["kinds"]
        kind = "摆动结构" if kinds & {"high", "low"} else ("均线" if "ema" in kinds else "区间极值")
        levels.append({"price": fmt_price(price), "strength": round(strength, 0), "touches": touches, "kind": kind})

    supports = sorted([l for l in levels if l["price"] < close * 0.999], key=lambda x: -x["price"])[:3]
    resistances = sorted([l for l in levels if l["price"] > close * 1.001], key=lambda x: x["price"])[:3]
    hi20 = max(c["h"] for c in candles[-20:])
    lo20 = min(c["l"] for c in candles[-20:])
    hi60 = max(c["h"] for c in candles[-60:])
    lo60 = min(c["l"] for c in candles[-60:])
    return {
        "supports": supports,
        "resistances": resistances,
        "pivot": fmt_price((hi20 + lo20 + close) / 3),
        "range20": [fmt_price(lo20), fmt_price(hi20)],
        "range60": [fmt_price(lo60), fmt_price(hi60)],
    }


# ---------------------------------------------------------------- 背离 / 形态
def detect_divergence(candles, swings, rsi_arr):
    highs = [s for s in swings if s["type"] == "high"][-3:]
    lows = [s for s in swings if s["type"] == "low"][-3:]
    out = []
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        ra, rb = rsi_arr[a["i"]], rsi_arr[b["i"]]
        if ra is not None and rb is not None and b["price"] > a["price"] and rb < ra - 2.5:
            out.append({"type": "bear", "name": "顶背离", "detail": f"价格创新高而 RSI 走弱（{ra:.0f}→{rb:.0f}）"})
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        ra, rb = rsi_arr[a["i"]], rsi_arr[b["i"]]
        if ra is not None and rb is not None and b["price"] < a["price"] and rb > ra + 2.5:
            out.append({"type": "bull", "name": "底背离", "detail": f"价格创新低而 RSI 走强（{ra:.0f}→{rb:.0f}）"})
    return out


def candle_patterns(candles):
    if len(candles) < 3:
        return []
    c, p = candles[-1], candles[-2]
    rng = max(c["h"] - c["l"], 1e-9)
    body = abs(c["c"] - c["o"])
    upper = c["h"] - max(c["c"], c["o"])
    lower = min(c["c"], c["o"]) - c["l"]
    out = []
    if body / rng < 0.12:
        out.append({"name": "十字星", "bias": "neutral", "detail": "多空均衡，等待方向选择"})
    if lower > body * 2 and upper < rng * 0.3 and c["c"] >= c["o"]:
        out.append({"name": "锤子线", "bias": "bull", "detail": "下影线长，低位承接明显"})
    if upper > body * 2 and lower < rng * 0.3 and c["c"] <= c["o"]:
        out.append({"name": "射击之星", "bias": "bear", "detail": "上影线长，上方抛压沉重"})
    if c["c"] > c["o"] and p["c"] < p["o"] and c["c"] >= p["o"] and c["o"] <= p["c"]:
        out.append({"name": "看涨吞没", "bias": "bull", "detail": "阳线完全吞没前一根阴线"})
    if c["c"] < c["o"] and p["c"] > p["o"] and c["c"] <= p["o"] and c["o"] >= p["c"]:
        out.append({"name": "看跌吞没", "bias": "bear", "detail": "阴线完全吞没前一根阳线"})
    return out[:2]


# ---------------------------------------------------------------- 评分
def evaluate(candles, ind, market: str = "crypto"):
    close = candles[-1]["c"]
    e20, e50, e200 = _last(ind["ema20"]), _last(ind["ema50"]), _last(ind["ema200"])
    dif, dea, hist = _last(ind["macd_dif"]), _last(ind["macd_dea"]), _last(ind["macd_hist"])
    rsi_v = _last(ind["rsi14"])
    adx_v, pdi, mdi = _last(ind["adx"]), _last(ind["pdi"]), _last(ind["mdi"])
    atr_v = _last(ind["atr"]) or close * 0.02
    bb_up, bb_mid, bb_lo = _last(ind["bb_up"]), _last(ind["bb_mid"]), _last(ind["bb_low"])
    vol, vma20 = candles[-1]["v"], _last(ind["vol_ma20"]) or 0
    cci_v = _last(ind["cci"])

    swings = find_swings(candles, 3)
    st = structure_report(candles, swings, close)

    # ---- 1. 均线结构
    pts = []
    if e20:
        pts.append((close > e20, 1.15))
    if e50:
        pts.append((close > e50, 1.25))
    if e200:
        pts.append((close > e200, 1.0))
    if e20 and e50:
        pts.append((e20 > e50, 1.25))
    if e50 and e200:
        pts.append((e50 > e200, 1.05))
    slope20 = ta.slope_pct(ind["ema20"], 8)
    if slope20 is not None:
        pts.append((slope20 > 0, 0.85))
    ma_score = sum((1 if ok else -1) * w for ok, w in pts) / sum(w for _, w in pts) * 100 if pts else 0
    if close > (e20 or close) > (e50 or close) > (e200 or close):
        ma_state = "多头排列"
    elif close < (e20 or close) < (e50 or close) < (e200 or close):
        ma_state = "空头排列"
    elif e20 and e50 and e20 > e50:
        ma_state = "均线偏多"
    elif e20 and e50 and e20 < e50:
        ma_state = "均线偏空"
    else:
        ma_state = "均线纠缠"
    ma_detail = f"EMA20 {fmt_price(e20) if e20 else '—'} / EMA50 {fmt_price(e50) if e50 else '—'} / EMA200 {fmt_price(e200) if e200 else '—'}"
    if slope20 is not None:
        ma_detail += f"；EMA20 斜率 {slope20:+.2f}%"

    # ---- 2. MACD
    mpts = []
    if dif is not None:
        mpts.append((dif > 0, 1.0))
    if dif is not None and dea is not None:
        mpts.append((dif > dea, 1.25))
    hist_prev = _last(ind["macd_hist"], 1)
    if hist is not None and hist_prev is not None:
        mpts.append((hist > hist_prev, 0.65))
    dif_prev3 = _last(ind["macd_dif"], 3)
    if dif is not None and dif_prev3 is not None:
        mpts.append((dif > dif_prev3, 0.6))
    macd_score = sum((1 if ok else -1) * w for ok, w in mpts) / sum(w for _, w in mpts) * 100 if mpts else 0

    cross = None
    if dif is not None and dea is not None:
        for back in range(0, 4):
            d0, s0 = _last(ind["macd_dif"], back + 1), _last(ind["macd_dea"], back + 1)
            d1, s1 = _last(ind["macd_dif"], back), _last(ind["macd_dea"], back)
            if None in (d0, s0, d1, s1):
                continue
            if d0 <= s0 and d1 > s1:
                cross = "金叉"
                break
            if d0 >= s0 and d1 < s1:
                cross = "死叉"
                break
    if cross == "金叉":
        macd_score = ta.clip(macd_score + 12)
        macd_state = "MACD 金叉"
    elif cross == "死叉":
        macd_score = ta.clip(macd_score - 12)
        macd_state = "MACD 死叉"
    elif dif is not None and dea is not None and dif > dea:
        macd_state = "多头动能" if dif > 0 else "低位反弹"
    elif dif is not None and dea is not None:
        macd_state = "高位回调" if dif > 0 else "空头动能"
    else:
        macd_state = "数据不足"
    macd_detail = f"DIF {_round(dif or 0, 4)} / DEA {_round(dea or 0, 4)} / 柱 {_round(hist or 0, 4)}"
    if dif is not None and dea is not None:
        macd_detail += "；零轴上方" if dif > 0 else "；零轴下方"

    # ---- 3. RSI
    rsi_hist = [x for x in ind["rsi14"][-200:] if x is not None]
    rsi_pct = ta.percentile_rank(rsi_hist, rsi_v) if rsi_v is not None else 50
    if rsi_v is None:
        rsi_score, rsi_state = 0, "数据不足"
    else:
        rsi_score = ta.clip((rsi_v - 50) * 3.2)
        if rsi_v > 80:
            rsi_score -= (rsi_v - 80) * 2.2
        if rsi_v < 20:
            rsi_score += (20 - rsi_v) * 2.2
        rsi_score = ta.clip(rsi_score)
        if rsi_v >= 70:
            rsi_state = "超买区"
        elif rsi_v >= 60:
            rsi_state = "强势区"
        elif rsi_v >= 50:
            rsi_state = "偏强区"
        elif rsi_v >= 40:
            rsi_state = "偏弱区"
        elif rsi_v >= 30:
            rsi_state = "弱势区"
        else:
            rsi_state = "超卖区"

    # ---- 4. ADX / DMI
    if adx_v is None or pdi is None or mdi is None or (pdi + mdi) == 0:
        adx_score, adx_state, adx_detail = 0, "数据不足", "—"
    else:
        direction = (pdi - mdi) / (pdi + mdi) * 100
        strength = min(adx_v / 35.0, 1.0)
        adx_score = ta.clip(direction * strength)
        if adx_v < 18:
            adx_state = "无明显趋势"
        elif adx_v < 25:
            adx_state = "趋势初现"
        elif adx_v < 40:
            adx_state = "趋势强"
        else:
            adx_state = "趋势极强"
        adx_state += " · 多头主导" if pdi > mdi else " · 空头主导"
        adx_detail = f"ADX {adx_v:.1f} / +DI {pdi:.1f} / -DI {mdi:.1f}"

    # ---- 5. BOLL
    bb_pctb = None
    if bb_up and bb_lo and bb_up > bb_lo:
        bb_pctb = (close - bb_lo) / (bb_up - bb_lo)
        boll_score = ta.clip((bb_pctb - 0.5) * 210)
    else:
        boll_score = 0
    widths = []
    for u, l, m in zip(ind["bb_up"][-200:], ind["bb_low"][-200:], ind["bb_mid"][-200:]):
        if u and l and m:
            widths.append((u - l) / m * 100)
    width_now = None
    if bb_up and bb_lo and bb_mid:
        width_now = (bb_up - bb_lo) / bb_mid * 100
    width_pct = ta.percentile_rank(widths, width_now) if (widths and width_now is not None) else 50
    if bb_pctb is None:
        boll_state = "数据不足"
    elif bb_pctb > 1:
        boll_state = "突破上轨"
    elif bb_pctb > 0.8:
        boll_state = "上轨附近"
    elif bb_pctb > 0.5:
        boll_state = "中轨上方"
    elif bb_pctb > 0.2:
        boll_state = "中轨下方"
    elif bb_pctb > 0:
        boll_state = "下轨附近"
    else:
        boll_state = "跌破下轨"
    if width_pct < 20:
        boll_state += " · 收口"
    elif width_pct > 80:
        boll_state += " · 开口"

    # ---- 6. 量能
    ratio = vol / vma20 if vma20 else 1.0
    obv_series = [x for x in ind["obv"][-21:] if x is not None]
    obv_score = 0.0
    if len(obv_series) >= 10:
        vol_sum = sum(c["v"] for c in candles[-20:]) or 1
        obv_score = ta.clip((obv_series[-1] - obv_series[0]) / vol_sum * 160)
    direction = 1 if candles[-1]["c"] >= candles[-2]["c"] else -1
    vol_score = ta.clip((ratio - 1) * 110, -70, 70) * direction * 0.55 + obv_score * 0.45
    vol_score = ta.clip(vol_score)
    if ratio >= 1.6:
        vol_word = "显著放量"
    elif ratio >= 1.15:
        vol_word = "温和放量"
    elif ratio <= 0.6:
        vol_word = "明显缩量"
    elif ratio <= 0.85:
        vol_word = "缩量"
    else:
        vol_word = "量能平稳"
    vol_state = f"{vol_word} · " + ("量价齐升" if direction > 0 and ratio > 1.1 else "量价齐跌" if direction < 0 and ratio > 1.1 else "量价背离" if ratio > 1.1 else "观望量能")
    vol_detail = f"量比 {ratio:.2f} / 20日均量 {vma20:,.0f}"

    # ---- 7. 结构
    st_score = st["score"]

    # ---- 8. 线性回归趋势
    look = min(90, len(candles))
    logs = [math.log(c["c"]) for c in candles[-look:]]
    slope, intercept, r2 = ta.linreg(logs)
    slope_pct = (math.exp(slope) - 1) * 100
    reg_score = ta.clip(math.tanh(slope_pct * 260) * 100 * max(r2, 0.25))
    if slope_pct > 0.03:
        reg_state = "上行通道"
    elif slope_pct < -0.03:
        reg_state = "下行通道"
    else:
        reg_state = "横向走平"
    reg_detail = f"{look} 根斜率 {slope_pct:+.3f}%/根，R² {r2:.2f}"

    comps = [
        {"key": "ma", "label": "均线结构", "weight": 22, "score": ta.clip(ma_score), "state": ma_state, "detail": ma_detail},
        {"key": "macd", "label": "MACD 动量", "weight": 14, "score": ta.clip(macd_score), "state": macd_state, "detail": macd_detail},
        {"key": "rsi", "label": "RSI 强弱", "weight": 10, "score": rsi_score, "state": rsi_state,
         "detail": (f"RSI14 {rsi_v:.1f}，近 200 根分位 {rsi_pct:.0f}%" if rsi_v is not None else "—")},
        {"key": "adx", "label": "趋势强度", "weight": 14, "score": adx_score, "state": adx_state, "detail": adx_detail},
        {"key": "boll", "label": "布林通道", "weight": 8, "score": boll_score, "state": boll_state,
         "detail": f"%B {bb_pctb:.2f}，带宽 {width_now:.2f}%（分位 {width_pct:.0f}%）" if bb_pctb is not None and width_now else "—"},
        {"key": "volume", "label": "量能确认", "weight": 8, "score": vol_score, "state": vol_state, "detail": vol_detail},
        {"key": "structure", "label": "摆动结构", "weight": 16, "score": st_score, "state": st["label"], "detail": st["detail"]},
        {"key": "regression", "label": "回归趋势", "weight": 8, "score": reg_score, "state": reg_state, "detail": reg_detail},
    ]

    score = sum(c["score"] * c["weight"] for c in comps) / 100
    score = ta.clip(score)

    verdict, short = _verdict(score, adx_v)
    confidence = 46 + min(abs(score) * 0.32, 24) + max(-8, min(12, ((adx_v or 15) - 15) * 0.45)) + r2 * 8
    if adx_v is None or adx_v < 15:
        confidence -= 4
    confidence = max(28, min(94, confidence))

    atr_pct = atr_v / close * 100
    div = detect_divergence(candles, swings, ind["rsi14"])
    pats = candle_patterns(candles)
    levels = build_levels(candles, swings, ind, close, atr_v, market)
    perf = {}
    for lb, key in ((5, "d5"), (20, "d20"), (60, "d60"), (120, "d120")):
        if len(candles) > lb:
            perf[key] = round((close / candles[-lb - 1]["c"] - 1) * 100, 2)
    lo60, hi60 = levels["range60"]
    range_pos = round((close - lo60) / (hi60 - lo60) * 100, 0) if hi60 > lo60 else 50

    res = {
        "price": fmt_price(close),
        "score": round(score, 1),
        "verdict": verdict,
        "verdict_short": short,
        "bias": "long" if score >= 18 else ("short" if score <= -18 else "neutral"),
        "confidence": round(confidence, 0),
        "components": comps,
        "structure": st,
        "levels": levels,
        "volatility": {
            "atr": _round(atr_v, 6),
            "atr_pct": round(atr_pct, 2),
            "bb_width": round(width_now, 2) if width_now else None,
            "bb_width_pct": round(width_pct, 0),
            "bb_pctb": round(bb_pctb, 3) if bb_pctb is not None else None,
            "regime": "高波动" if atr_pct > (6 if market == "crypto" else 3.5) else ("低波动" if atr_pct < (1.4 if market == "crypto" else 0.9) else "中等波动"),
        },
        "momentum": {
            "rsi": round(rsi_v, 1) if rsi_v is not None else None,
            "rsi_state": rsi_state,
            "rsi_pct": round(rsi_pct, 0),
            "macd_state": macd_state,
            "cci": round(cci_v, 1) if cci_v is not None else None,
            "divergence": div,
            "patterns": pats,
        },
        "trend": {
            "adx": round(adx_v, 1) if adx_v is not None else None,
            "adx_state": adx_state,
            "slope_pct": round(slope_pct, 3),
            "r2": round(r2, 2),
            "ma_state": ma_state,
        },
        "volume": {"ratio": round(ratio, 2), "state": vol_state, "obv_score": round(obv_score, 0)},
        "perf": perf,
        "range_pos": range_pos,
        "swings": st["swings"],
        "signals": _signals(comps, st, div, pats, market),
        "risks": _risks(comps, st, div, atr_pct, ratio, close, e20, atr_v, market, rsi_v, adx_v, levels, r2),
        "summary": "",
    }
    res["summary"] = _summary(res, swing_high=st.get("last_high"), swing_low=st.get("last_low"))
    return res


def _verdict(score: float, adx_v: Num):
    if score >= 55 and (adx_v or 0) >= 18:
        return "强势多头", "强多"
    if score >= 55:
        return "多头占优（趋势强度不足）", "偏多"
    if score >= 25:
        return "多头趋势", "多头"
    if score >= 10:
        return "震荡偏多", "偏多"
    if score > -10:
        return "震荡整理", "震荡"
    if score > -25:
        return "震荡偏空", "偏空"
    if score > -55:
        return "空头趋势", "空头"
    if (adx_v or 0) >= 18:
        return "强势空头", "强空"
    return "空头占优（趋势强度不足）", "偏空"


def _signals(comps, st, div, pats, market):
    out = []
    by = {c["key"]: c for c in comps}

    if by["ma"]["score"] >= 40:
        out.append({"type": "bull", "title": "均线多头排列", "detail": by["ma"]["detail"]})
    elif by["ma"]["score"] <= -40:
        out.append({"type": "bear", "title": "均线空头排列", "detail": by["ma"]["detail"]})
    elif by["ma"]["score"] >= 15:
        out.append({"type": "bull", "title": "价格站上主要均线", "detail": by["ma"]["detail"]})
    elif by["ma"]["score"] <= -15:
        out.append({"type": "bear", "title": "价格位于主要均线下方", "detail": by["ma"]["detail"]})

    if "金叉" in by["macd"]["state"]:
        out.append({"type": "bull", "title": "MACD 金叉", "detail": "短期动能转强，关注能否站稳零轴"})
    elif "死叉" in by["macd"]["state"]:
        out.append({"type": "bear", "title": "MACD 死叉", "detail": "短期动能转弱，谨防回落延续"})
    elif abs(by["macd"]["score"]) >= 20:
        out.append({"type": "bull" if by["macd"]["score"] > 0 else "bear",
                    "title": by["macd"]["state"], "detail": by["macd"]["detail"]})

    if abs(by["adx"]["score"]) >= 25:
        out.append({"type": "bull" if by["adx"]["score"] > 0 else "bear",
                    "title": "趋势强度" + ("偏多" if by["adx"]["score"] > 0 else "偏空"),
                    "detail": by["adx"]["detail"]})
    elif "无明显趋势" in by["adx"]["state"]:
        out.append({"type": "neutral", "title": "趋势强度不足", "detail": by["adx"]["detail"] + "，区间震荡概率大"})

    if "超买" in by["rsi"]["state"]:
        out.append({"type": "bear", "title": "RSI 超买", "detail": by["rsi"]["detail"] + "，短线追多风险高"})
    elif "超卖" in by["rsi"]["state"]:
        out.append({"type": "bull", "title": "RSI 超卖", "detail": by["rsi"]["detail"] + "，关注技术性反弹"})

    if "突破上轨" in by["boll"]["state"]:
        out.append({"type": "bull", "title": "价格突破布林上轨", "detail": by["boll"]["detail"]})
    elif "跌破下轨" in by["boll"]["state"]:
        out.append({"type": "bear", "title": "价格跌破布林下轨", "detail": by["boll"]["detail"]})
    elif "收口" in by["boll"]["state"]:
        out.append({"type": "neutral", "title": "布林带收口", "detail": by["boll"]["detail"] + "，变盘临近"})

    if st["pattern"] == "up":
        out.append({"type": "bull", "title": st["label"], "detail": st["detail"]})
    elif st["pattern"] == "down":
        out.append({"type": "bear", "title": st["label"], "detail": st["detail"]})
    elif st["pattern"] in ("contracting", "expanding"):
        out.append({"type": "neutral", "title": st["label"], "detail": st["detail"]})

    if st.get("breakout") == "up":
        out.append({"type": "bull", "title": "向上突破摆动高点", "detail": "结构突破，需放量确认有效性"})
    elif st.get("breakout") == "down":
        out.append({"type": "bear", "title": "向下跌破摆动低点", "detail": "结构破位，注意止损保护"})

    for d in div:
        out.append({"type": d["type"], "title": d["name"], "detail": d["detail"]})
    for p in pats:
        out.append({"type": p["bias"], "title": p["name"], "detail": p["detail"]})

    if abs(by["volume"]["score"]) >= 25:
        out.append({"type": "bull" if by["volume"]["score"] > 0 else "bear",
                    "title": "量能" + ("配合" if by["volume"]["score"] > 0 else "走弱"),
                    "detail": by["volume"]["detail"]})

    return out[:9]


def _risks(comps, st, div, atr_pct, ratio, close, e20, atr_v, market, rsi_v, adx_v, levels, r2):
    out = []
    if rsi_v is not None and rsi_v >= 72:
        out.append({"level": "high", "text": f"RSI {rsi_v:.0f} 进入超买区，追多的盈亏比不佳，优先等回踩"})
    if rsi_v is not None and rsi_v <= 28:
        out.append({"level": "mid", "text": f"RSI {rsi_v:.0f} 处于超卖区，存在反弹需求但不等于见底，勿盲目抄底"})
    if adx_v is not None and adx_v < 18:
        out.append({"level": "mid", "text": f"ADX {adx_v:.0f} 低于 18，趋势性弱，区间高抛低吸优于追单"})
    if r2 < 0.25:
        out.append({"level": "mid", "text": f"回归 R² 仅 {r2:.2f}，走势线性度差，趋势信号可信度下降"})
    if atr_pct > (6 if market == "crypto" else 3.5):
        out.append({"level": "high", "text": f"ATR 波动率 {atr_pct:.2f}%，止损需放宽、仓位应同步下调"})
    if e20 and atr_v and abs(close - e20) / atr_v > 2.4:
        out.append({"level": "mid", "text": "价格偏离 EMA20 超过 2.4 倍 ATR，短线乖离过大，谨防均值回归"})
    if ratio < 0.6:
        out.append({"level": "mid", "text": f"成交量仅为 20 日均量的 {ratio:.0%}，任何突破的有效性都需打折扣"})
    for d in div:
        out.append({"level": "high" if d["type"] == "bear" else "mid", "text": f"{d['name']}：{d['detail']}"})
    if st["pattern"] == "contracting":
        out.append({"level": "mid", "text": "波动收敛中，突破前的假信号偏多，务必等待收线确认"})
    if levels.get("resistances") and atr_v:
        gap = levels["resistances"][0]["price"] - close
        if 0 < gap < 1.1 * atr_v:
            out.append({"level": "mid", "text": "现价贴近上方阻力，突破前上行空间有限，注意假突破"})
    if levels.get("supports") and atr_v:
        gap = close - levels["supports"][0]["price"]
        if 0 < gap < 1.1 * atr_v:
            out.append({"level": "mid", "text": "现价贴近下方支撑，若放量跌破易触发加速下行"})
    if not out:
        out.append({"level": "low", "text": "当前指标未出现明显极端信号，但仍需按计划止损，防范突发消息冲击"})
    if len(out) == 1:
        out.append({"level": "low", "text": "技术分析基于历史价格，遇到宏观数据或突发事件可能瞬间失效"})
    return out[:6]


def _summary(res, swing_high=None, swing_low=None):
    lv = res["levels"]
    s1 = lv["supports"][0]["price"] if lv["supports"] else None
    r1 = lv["resistances"][0]["price"] if lv["resistances"] else None
    parts = [f"{res['verdict']}，综合评分 {res['score']:+.0f}。"]
    parts.append(f"{res['structure']['label']}，{res['trend']['ma_state']}，{res['momentum']['macd_state']}。")
    parts.append(f"RSI {res['momentum']['rsi']}（{res['momentum']['rsi_state']}），ADX {res['trend']['adx']}（{res['trend']['adx_state']}）。")
    if r1 and s1:
        parts.append(f"上方阻力 {money(r1)}，下方支撑 {money(s1)}。")
    return "".join(parts)


# ---------------------------------------------------------------- 交易计划
def build_plan(res, candles, ind, quote, market, tf):
    close = candles[-1]["c"]
    atr_v = _last(ind["atr"]) or close * 0.02
    e20 = _last(ind["ema20"])
    lv = res["levels"]
    bias = res["bias"]

    if bias == "neutral":
        return {
            "bias": "neutral",
            "title": "观望等待",
            "quality": "wait",
            "note": "多空因子互相抵消，当前不满足高胜率入场条件。等待结构突破或回踩关键位后再介入。",
            "watch_up": lv["resistances"][0]["price"] if lv["resistances"] else None,
            "watch_down": lv["supports"][0]["price"] if lv["supports"] else None,
            "trigger": (
                f"站上 {money(lv['resistances'][0]['price'])} 且放量转多 / 跌破 {money(lv['supports'][0]['price'])} 转空"
                if lv["resistances"] and lv["supports"] else None
            ),
            "entry_lo": None, "entry_hi": None, "stop": None, "t1": None, "t2": None, "rr": None,
        }

    long = bias == "long"
    ext = (close - e20) / atr_v if e20 else 0
    if long:
        if ext > 2.0:
            entry_lo, entry_hi, style = e20 - 0.25 * atr_v, e20 + 0.5 * atr_v, "回踩 EMA20 接多"
        elif ext < 0.4:
            entry_lo, entry_hi, style = close - 0.45 * atr_v, close + 0.25 * atr_v, "现价区轻仓"
        else:
            entry_lo, entry_hi, style = max(e20, close - 1.2 * atr_v), close - 0.15 * atr_v, "回调分批"
        entry_mid = (entry_lo + entry_hi) / 2
        sup = [s["price"] for s in lv["supports"] if s["price"] < entry_lo - 0.15 * atr_v]
        stop = (sup[0] - 0.3 * atr_v) if sup and entry_lo - sup[0] <= 2.2 * atr_v else (entry_lo - 1.6 * atr_v)
        stop = max(stop, entry_mid - 2.2 * atr_v)
        risk = max(entry_mid - stop, atr_v * 0.2)
    else:
        if ext < -2.0:
            entry_lo, entry_hi, style = e20 - 0.5 * atr_v, e20 + 0.25 * atr_v, "反弹 EMA20 做空"
        elif ext > -0.4:
            entry_lo, entry_hi, style = close - 0.25 * atr_v, close + 0.45 * atr_v, "现价区轻仓"
        else:
            entry_lo, entry_hi, style = close + 0.15 * atr_v, min(e20, close + 1.2 * atr_v), "反弹分批"
        entry_mid = (entry_lo + entry_hi) / 2
        res_lv = [r["price"] for r in lv["resistances"] if r["price"] > entry_hi + 0.15 * atr_v]
        stop = (res_lv[0] + 0.3 * atr_v) if res_lv and res_lv[0] - entry_hi <= 2.2 * atr_v else (entry_hi + 1.6 * atr_v)
        stop = min(stop, entry_mid + 2.2 * atr_v)
        risk = max(stop - entry_mid, atr_v * 0.2)

    if long:
        pool = [r["price"] for r in lv["resistances"] if r["price"] > entry_hi + 0.15 * atr_v]
        pool.sort()
        t1 = pool[0] if pool else entry_mid + 1.8 * risk
        t2 = pool[1] if len(pool) > 1 else t1 + 1.2 * risk
    else:
        pool = [s["price"] for s in lv["supports"] if s["price"] < entry_lo - 0.15 * atr_v]
        pool.sort(reverse=True)
        t1 = pool[0] if pool else entry_mid - 1.8 * risk
        t2 = pool[1] if len(pool) > 1 else t1 - 1.2 * risk

    rr = abs(t1 - entry_mid) / risk
    measured = False
    # 盈亏比不足：先把进场位挪到最近的支撑/阻力附近，而不是硬拉目标价
    if rr < 1.15 and lv["supports" if long else "resistances"]:
        anchor = lv["supports" if long else "resistances"][0]["price"]
        if (long and anchor < entry_lo - 0.2 * atr_v) or (not long and anchor > entry_hi + 0.2 * atr_v):
            if long:
                entry_lo, entry_hi = anchor + 0.05 * atr_v, anchor + 0.55 * atr_v
                stop = anchor - 0.3 * atr_v
                style = "等待回踩支撑接多"
            else:
                entry_lo, entry_hi = anchor - 0.55 * atr_v, anchor - 0.05 * atr_v
                stop = anchor + 0.3 * atr_v
                style = "等待反弹阻力做空"
            entry_mid = (entry_lo + entry_hi) / 2
            risk = max(abs(entry_mid - stop), atr_v * 0.2)
            rr = abs(t1 - entry_mid) / risk
    # 仍然不足：改用 2R 量度目标（说明上方/下方最近结构位太近）
    if rr < 1.15:
        t1 = entry_mid + 2.0 * risk if long else entry_mid - 2.0 * risk
        t2 = t1 + 1.2 * risk if long else t1 - 1.2 * risk
        rr = 2.0
        measured = True

    if long:
        t2 = min(t2, entry_mid + 4.5 * risk)
        t2 = max(t2, t1)
    else:
        t2 = max(t2, entry_mid - 4.5 * risk)
        t2 = min(t2, t1)

    quality = "good" if rr >= 1.6 else ("ok" if rr >= 1.2 else "poor")
    note = (
        f"止损 {money(stop)}（{abs(entry_mid - stop) / entry_mid * 100:.2f}%），第一目标 {money(t1)}，盈亏比 {rr:.2f}。"
    )
    if measured:
        note += " 最近结构位离进场区太近，第一目标按 2R 量度测算，需先突破该结构位。"
    if quality == "poor":
        note += " 当前盈亏比不足 1.2，建议等待回踩更深或突破确认后再执行。"
    if market == "crypto":
        units = 100.0 / risk if risk else 0
        note += f" 以 1 万 USDT、单笔风险 1% 计算，仓位约 {units:,.3f} 单位（名义 {units * entry_mid:,.0f} USDT）。"
    else:
        units = 100.0 / risk if risk else 0
        note += f" 以 1 万美元、单笔风险 1% 计算，仓位约 {units:,.0f} 股（名义 {units * entry_mid:,.0f} 美元）。"

    trig_hi = res["structure"].get("last_high")
    trig_lo = res["structure"].get("last_low")
    if long:
        trigger = f"回踩 {money(entry_lo)}–{money(entry_hi)} 分批；或站稳 {money(trig_hi or entry_hi)} 后突破追入"
    else:
        trigger = f"反弹 {money(entry_lo)}–{money(entry_hi)} 分批；或跌破 {money(trig_lo or entry_lo)} 后顺势追空"

    return {
        "bias": "long" if long else "short",
        "title": style,
        "quality": quality,
        "entry_lo": fmt_price(min(entry_lo, entry_hi)),
        "entry_hi": fmt_price(max(entry_lo, entry_hi)),
        "stop": fmt_price(stop),
        "t1": fmt_price(t1),
        "t2": fmt_price(t2),
        "rr": round(rr, 2),
        "risk_pct": round(abs(entry_mid - stop) / entry_mid * 100, 2),
        "stop_atr": round(abs(entry_mid - stop) / atr_v, 2) if atr_v else None,
        "trigger": trigger,
        "note": note,
        "invalidation": f"收盘{'跌破' if long else '站上'} {money(stop)} 则计划失效",
    }
