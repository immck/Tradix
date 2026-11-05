"""Tradix · 交易矩阵 —— 交易结构分析本地服务。

用法:
    python server.py            # http://127.0.0.1:8899
    python server.py --port 9000
"""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import sys
import time
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import analysis as an
from core import datasource as ds
from core import indicators as ta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

MTF_WEIGHTS = {
    "crypto": [("1h", 0.14), ("4h", 0.24), ("1d", 0.36), ("1w", 0.26)],
    "us": [("1h", 0.12), ("4h", 0.18), ("1d", 0.40), ("1w", 0.30)],
    "cn": [("1d", 0.62), ("1w", 0.38)],
}

CACHE_TTL = {"crypto": 45, "us": 120, "cn": 90}
_result_cache: dict = {}


def _mtf_one(symbol: str, market: str, tf: str, label: str):
    try:
        candles, quote, meta = ds.get_ohlc(symbol, market, tf)
        if len(candles) < 60:
            return None
        ind = ta.compute_all(candles)
        r = an.evaluate(candles, ind, market)
        return {
            "tf": tf,
            "label": label,
            "score": r["score"],
            "verdict": r["verdict"],
            "verdict_short": r["verdict_short"],
            "adx": r["trend"]["adx"],
            "rsi": r["momentum"]["rsi"],
            "ma_state": r["trend"]["ma_state"],
            "structure": r["structure"]["label"],
            "price": r["price"],
        }
    except Exception as e:  # noqa: BLE001
        return {"tf": tf, "label": label, "error": str(e), "score": None}


def build_mtf(symbol: str, market: str, primary_tf: str):
    weights = MTF_WEIGHTS.get(market, MTF_WEIGHTS["us"])
    jobs = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for tf, w in weights:
            if tf == primary_tf:
                continue
            jobs.append((ex.submit(_mtf_one, symbol, market, tf, ds.TF_LABEL[tf]), tf, w))
        out = []
        for fut, tf, w in jobs:
            r = fut.result()
            if r:
                r["weight"] = w
                out.append(r)
    order = {tf: i for i, (tf, _) in enumerate(weights)}
    out.sort(key=lambda x: order.get(x["tf"], 9))
    return out


def combine_overall(primary: dict, mtf: list):
    valid = [m for m in mtf if m.get("score") is not None]
    if not valid:
        return {
            "score": primary["score"],
            "bias": primary["bias"],
            "resonance": "数据不足",
            "aligned": 0,
            "total": 0,
            "detail": "缺少其他周期数据，仅按当前周期判断",
        }
    wsum = sum(m["weight"] for m in valid)
    mtf_score = sum(m["score"] * m["weight"] for m in valid) / wsum
    final = primary["score"] * 0.62 + mtf_score * 0.38

    sign = 1 if primary["score"] >= 0 else -1
    aligned = [m for m in valid if (m["score"] >= 10 if sign > 0 else m["score"] <= -10)]
    against = [m for m in valid if (m["score"] <= -10 if sign > 0 else m["score"] >= 10)]
    if len(aligned) == len(valid):
        resonance = "多周期共振"
    elif len(aligned) > len(against):
        resonance = "多数周期一致"
    elif len(against) > len(aligned):
        resonance = "周期分歧"
    else:
        resonance = "方向不明"
    detail = " · ".join(f"{m['label']} {m['score']:+.0f}" for m in valid)
    return {
        "score": round(final, 1),
        "bias": "long" if final >= 18 else ("short" if final <= -18 else "neutral"),
        "resonance": resonance,
        "aligned": len(aligned),
        "against": len(against),
        "total": len(valid),
        "detail": detail,
        "mtf_score": round(mtf_score, 1),
    }


def build_chart(candles, ind, res, plan, meta):
    n = len(candles)
    take = min(n, 320)
    start = n - take
    rows = [[c["t"], an._round(c["o"], 6), an._round(c["h"], 6), an._round(c["l"], 6), an._round(c["c"], 6), an._round(c["v"], 2)]
            for c in candles[start:]]

    def cut(key):
        return [None if v is None else an._round(v, 6) for v in ind[key][start:]]

    chart = {
        "candles": rows,
        "ema20": cut("ema20"),
        "ema50": cut("ema50"),
        "ema200": cut("ema200"),
        "bb_up": cut("bb_up"),
        "bb_low": cut("bb_low"),
        "bb_mid": cut("bb_mid"),
        "vol_ma20": cut("vol_ma20"),
        "macd_dif": cut("macd_dif"),
        "macd_dea": cut("macd_dea"),
        "macd_hist": cut("macd_hist"),
        "rsi": cut("rsi14"),
        "levels": {
            "supports": [{"price": s["price"], "strength": s["strength"]} for s in res["levels"]["supports"]],
            "resistances": [{"price": r["price"], "strength": r["strength"]} for r in res["levels"]["resistances"]],
        },
        "plan": {k: plan.get(k) for k in ("bias", "entry_lo", "entry_hi", "stop", "t1", "t2")},
        "swings": [{"t": s["t"], "price": s["price"], "type": s["type"]} for s in res["swings"]],
        "tz": meta.get("tz", "UTC"),
        "market": meta["market"],
        "tf": meta["tf"],
    }
    return chart


def api_analyze(params):
    symbol = (params.get("symbol") or "").strip()
    market = (params.get("market") or "auto").strip().lower()
    tf = ds.detect_tf(params.get("tf") or "1d")

    key = f"{symbol}|{market}|{tf}"
    hit = _result_cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL.get(market, 60) / 2:
        return hit[1]

    candles, quote, meta = ds.get_ohlc(symbol, market, tf)
    ind = ta.compute_all(candles)
    res = an.evaluate(candles, ind, meta["market"])
    plan = an.build_plan(res, candles, ind, quote, meta["market"], tf)
    mtf = build_mtf(symbol, meta["market"], tf)
    overall = combine_overall(res, mtf)
    if overall["resonance"] == "周期分歧":
        res["risks"].insert(0, {"level": "mid", "text": "多周期方向不一致（" + overall["detail"] + "），单周期信号需降级使用"})
    if meta.get("stale"):
        res["risks"].insert(0, {"level": "high", "text": "当前展示的是本地缓存数据，行情源暂时不可用，请谨慎参考"})
    chart = build_chart(candles, ind, res, plan, meta)

    payload = {
        "ok": True,
        "meta": {
            "symbol": meta["code"],
            "display": meta["display"],
            "name": meta.get("name"),
            "market": meta["market"],
            "market_label": {"crypto": "加密货币", "us": "美股", "cn": "A股"}[meta["market"]],
            "currency": meta.get("currency", "USD"),
            "source": meta.get("source"),
            "tf": meta["tf"],
            "tf_label": meta["tf_label"],
            "bars": meta["bars"],
            "last_t": meta["last_t"],
            "last_closed": meta["last_closed"],
            "stale": meta["stale"],
            "fetched_at": meta["fetched_at"],
            "tz": meta.get("tz", "UTC"),
            "generated_at": time.time(),
        },
        "quote": quote,
        "analysis": res,
        "plan": plan,
        "mtf": mtf,
        "overall": overall,
        "chart": chart,
    }
    _result_cache[key] = (time.time(), payload)
    if len(_result_cache) > 200:
        for k in list(_result_cache)[:80]:
            _result_cache.pop(k, None)
    return payload


def api_scan(params):
    raw = params.get("symbols") or ""
    symbols = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()][:10]
    if not symbols:
        return {"ok": False, "error": "缺少 symbols 参数"}
    tf = ds.detect_tf(params.get("tf") or "1d")

    def one(sym):
        try:
            candles, quote, meta = ds.get_ohlc(sym, "auto", tf)
            if len(candles) < 60:
                raise ds.DataError("数据不足")
            ind = ta.compute_all(candles)
            r = an.evaluate(candles, ind, meta["market"])
            return {
                "symbol": meta["display"],
                "name": meta.get("name"),
                "market": meta["market"],
                "price": quote.get("price"),
                "chg_pct": quote.get("chg_pct"),
                "score": r["score"],
                "verdict": r["verdict_short"],
                "rsi": r["momentum"]["rsi"],
                "adx": r["trend"]["adx"],
                "change_5": round((candles[-1]["c"] / candles[-6]["c"] - 1) * 100, 2) if len(candles) > 6 else 0,
                "change_20": round((candles[-1]["c"] / candles[-21]["c"] - 1) * 100, 2) if len(candles) > 21 else 0,
            }
        except Exception as e:  # noqa: BLE001
            return {"symbol": sym, "error": str(e)[:80]}

    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(one, symbols))
    return {"ok": True, "items": out, "ts": time.time()}


class Handler(BaseHTTPRequestHandler):
    server_version = "Tradix/1.0"

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False, gzip_ok: bool = True):
        use_gzip = gzip_ok and len(body) > 1200 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if use_gzip:
            body = gzip.compress(body, 5)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "public, max-age=60" if cache else "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        try:
            if path == "/api/analyze":
                self._json(api_analyze(params))
            elif path == "/api/scan":
                self._json(api_scan(params))
            elif path == "/api/health":
                self._json({"ok": True, "ts": time.time(), "version": self.server_version})
            elif path.startswith("/api/"):
                self._json({"ok": False, "error": "未知接口"}, 404)
            else:
                self._static(path)
        except ds.NotFound as e:
            self._json({"ok": False, "error": str(e)}, 404)
        except ds.DataError as e:
            self._json({"ok": False, "error": str(e)}, 502)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            msg = f"服务异常: {e}"
            if "NoneType" in str(e) or "list index" in str(e):
                msg = "未找到该品种的数据，请检查代码或切换市场类型后重试"
            self._json({"ok": False, "error": msg}, 500)

    def _static(self, path: str):
        if path in ("/", ""):
            path = "/index.html"
        safe = os.path.normpath(path.lstrip("/")).replace("..", "")
        full = os.path.join(WEB_DIR, safe)
        if not os.path.isfile(full):
            self._send(404, b"Not Found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".json": "application/json; charset=utf-8",
        }.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        self._send(200, body, ctype, cache=ext not in (".html", ".js", ".css"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8899")))
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print("=" * 58)
    print("  TRADIX · 交易矩阵  结构分析终端")
    print(f"  本地地址: http://{args.host}:{args.port}")
    print("  数据源: Gate.io / 新浪财经 / 腾讯财经")
    print("  Ctrl+C 停止服务")
    print("=" * 58)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
