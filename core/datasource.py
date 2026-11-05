"""行情数据层：Gate.io（加密货币）/ 新浪财经（美股）/ 腾讯（A股）。

- 统一输出 [{t,o,h,l,c,v}]，t 为 UTC 秒
- 内存 + 磁盘两级缓存，网络失败时回退到最近缓存（标记 stale）
"""
from __future__ import annotations

import gzip
import io
import json
import math
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "data", "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
try:
    NY = ZoneInfo("America/New_York")
    CN = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    raise SystemExit("Missing timezone data. Run: python -m pip install -r requirements.txt")

_SSL_CTX = ssl.create_default_context()
_SSL_LAX = ssl.create_default_context()
_SSL_LAX.check_hostname = False
_SSL_LAX.verify_mode = ssl.CERT_NONE

_mem: dict = {}
_mem_lock = threading.Lock()

TF_LABEL = {
    "15m": "15分钟",
    "30m": "30分钟",
    "1h": "1小时",
    "4h": "4小时",
    "1d": "日线",
    "1w": "周线",
    "1M": "月线",
}


class DataError(Exception):
    pass


class NotFound(DataError):
    pass


# ---------------------------------------------------------------- HTTP
def http_get(url: str, timeout: int = 15, referer: str | None = None, retries: int = 2) -> bytes:
    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if referer:
        headers["Referer"] = referer
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            try:
                resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
            except ssl.SSLError:
                resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_LAX)
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                data = gzip.GzipFile(fileobj=io.BytesIO(data)).read()
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 404):
                break
            time.sleep(0.4 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise DataError(f"请求失败: {url.split('?')[0]} ({last})")


def _json(url: str, **kw):
    return json.loads(http_get(url, **kw).decode("utf-8", "ignore"))


# ---------------------------------------------------------------- 缓存
def _cache_key(market: str, symbol: str, tf: str) -> str:
    return f"{market}_{symbol.replace('/', '_')}_{tf}"


def _ttl(market: str, tf: str) -> int:
    if tf in ("1d", "1w", "1M"):
        return 120 if market == "crypto" else 300
    return 45 if market == "crypto" else 60


def cache_get(key: str, ttl: int):
    now = time.time()
    with _mem_lock:
        hit = _mem.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], False
    path = os.path.join(CACHE_DIR, key + ".json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        age = now - payload.get("_saved", 0)
        if age < ttl:
            with _mem_lock:
                _mem[key] = (payload.get("_saved", now), payload)
            return payload, False
    except (OSError, ValueError):
        pass
    return None, False


def cache_put(key: str, payload: dict):
    payload["_saved"] = time.time()
    with _mem_lock:
        _mem[key] = (payload["_saved"], payload)
    try:
        with open(os.path.join(CACHE_DIR, key + ".json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    except OSError:
        pass


def cache_stale(key: str, max_age: int = 7 * 86400):
    path = os.path.join(CACHE_DIR, key + ".json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if time.time() - payload.get("_saved", 0) < max_age:
            return payload
    except (OSError, ValueError):
        pass
    return None


# ---------------------------------------------------------------- 品种解析
KNOWN_CRYPTO = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "TON", "TRX",
    "LTC", "BCH", "SHIB", "SUI", "APT", "ARB", "OP", "PEPE", "WIF", "NEAR", "INJ", "TIA",
    "SEI", "HBAR", "ICP", "FIL", "ATOM", "UNI", "AAVE", "ETC", "XLM", "ALGO", "VET", "RENDER",
    "FET", "STX", "IMX", "GRT", "THETA", "LDO", "JUP", "PYTH", "BONK", "FLOKI", "TAO", "WLD",
    "ENS", "MKR", "CRV", "COMP", "SNX", "DYDX", "GMT", "SAND", "MANA", "AXS", "GALA", "CHZ",
    "APE", "NEO", "EOS", "KSM", "ZEC", "DASH", "ORDI", "SATS", "NOT", "TON", "ONDO", "ENA",
    "ETHFI", "STRK", "MANTA", "ALT", "PIXEL", "AEVO", "BOME", "MEW", "POPCAT", "BRETT",
}


def normalize(symbol: str, market: str = "auto"):
    """返回 (market, code, display)"""
    raw = (symbol or "").strip().upper().replace(" ", "").lstrip("$")
    if not raw:
        raise NotFound("请输入交易品种，例如 BTC、ETH、NVDA、AAPL")
    if market not in ("auto", "crypto", "us", "cn"):
        raise DataError("不支持的市场类型")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9./_-]{0,30}", raw):
        raise NotFound("代码格式不正确，请输入交易代码")

    explicit = market in ("crypto", "us", "cn")

    # ---- 加密货币：BTCUSDT / BTC-USDT / BTC/USDT / ETHBTC
    cm = re.fullmatch(r"([A-Z0-9]{2,15})[-_/]?(USDT|USDC|USD|BTC|ETH)", raw)
    is_crypto = (
        explicit and market == "crypto"
        or not explicit and (
            (cm is not None and cm.group(2) in ("USDT", "USDC", "USD"))
            or (cm is not None and len(cm.group(1)) >= 3 and cm.group(2) in ("BTC", "ETH"))
            or raw in KNOWN_CRYPTO
        )
    )
    if is_crypto:
        if cm:
            base, quote = cm.group(1), cm.group(2)
        else:
            base, quote = raw, "USDT"
        if not re.fullmatch(r"[A-Z0-9]{1,20}", base):
            raise NotFound("加密货币代码格式不正确")
        if quote == "USD":
            quote = "USDT"
        return "crypto", f"{base}_{quote}", f"{base}/{quote}"

    # ---- A 股：600519 / SH600519 / 600519.SH
    m = re.fullmatch(r"(SH|SZ|BJ)?(\d{6})(?:\.(SH|SZ|BJ))?", raw) if market != "us" else None
    if m:
        code = m.group(2)
        pre = m.group(1) or m.group(3)
        if not pre:
            pre = "SH" if code[0] in "69" else "BJ" if code[0] in "48" else "SZ"
        return "cn", f"{pre.lower()}{code}", code

    # ---- 美股
    if market == "cn":
        raise NotFound("A股请输入六位代码，例如 600519")
    sym = re.sub(r"\.(US|O|N)$", "", raw)
    if not re.fullmatch(r"[A-Z0-9]+(?:[.-][A-Z0-9]+)*", sym):
        raise NotFound("美股代码格式不正确")
    return "us", sym, sym


def detect_tf(tf: str) -> str:
    tf = (tf or "1d").strip()
    if tf == "1M":
        return tf
    tf = tf.lower()
    return tf if tf in TF_LABEL else "1d"


# ---------------------------------------------------------------- K 线工具
def _clean(candles):
    out = []
    for c in candles:
        try:
            o, h, l, cl = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
            v = float(c.get("v") or 0)
            t = int(c["t"])
        except (TypeError, ValueError, KeyError):
            continue
        if not all(math.isfinite(x) and x > 0 for x in (o, h, l, cl)):
            continue
        out.append({"t": t, "o": o, "h": h, "l": l, "c": cl, "v": v})
    out.sort(key=lambda x: x["t"])
    dedup = []
    for c in out:
        if dedup and dedup[-1]["t"] == c["t"]:
            dedup[-1] = c
        else:
            dedup.append(c)
    return dedup


def resample(candles, seconds: int):
    buckets: dict[int, dict] = {}
    order = []
    for c in candles:
        key = c["t"] // seconds * seconds
        b = buckets.get(key)
        if b is None:
            buckets[key] = {"t": key, "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]}
            order.append(key)
        else:
            b["h"] = max(b["h"], c["h"])
            b["l"] = min(b["l"], c["l"])
            b["c"] = c["c"]
            b["v"] += c["v"]
    return [buckets[k] for k in order]


def resample_session(candles, bars_per_bucket: int, tz=NY):
    """按交易日内每 N 根 1 小时线合并（美股 4H 用），时间戳取该段最后一根 K 线的收盘时间。"""
    out = []
    cur = None
    count = 0
    cur_date = None
    for c in candles:
        d = datetime.fromtimestamp(c["t"], tz).date()
        if cur is None or d != cur_date or count >= bars_per_bucket:
            if cur:
                out.append(cur)
            cur = {"t": c["t"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]}
            cur_date = d
            count = 1
        else:
            cur["h"] = max(cur["h"], c["h"])
            cur["l"] = min(cur["l"], c["l"])
            cur["c"] = c["c"]
            cur["v"] += c["v"]
            cur["t"] = c["t"]
            count += 1
    if cur:
        out.append(cur)
    return out


def resample_daily_to(candles, mode: str, tz=NY):
    out = []
    key_prev = None
    cur = None
    for c in candles:
        dt = datetime.fromtimestamp(c["t"], tz)
        if mode == "week":
            y, w, _ = dt.isocalendar()
            key = (y, w)
        else:
            key = (dt.year, dt.month)
        if key != key_prev:
            if cur:
                out.append(cur)
            cur = {"t": c["t"], "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]}
            key_prev = key
        else:
            cur["h"] = max(cur["h"], c["h"])
            cur["l"] = min(cur["l"], c["l"])
            cur["c"] = c["c"]
            cur["v"] += c["v"]
    if cur:
        out.append(cur)
    return out


def parse_jsonp(text: str):
    i = text.find("(")
    j = text.rfind(")")
    if i < 0 or j <= i:
        raise DataError("行情返回格式异常")
    return json.loads(text[i + 1 : j])


# ---------------------------------------------------------------- Gate.io
GATE = "https://api.gateio.ws/api/v4"
GATE_TF = {"15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "7d", "1M": "30d"}


def _gate_candles(pair: str, tf: str, limit: int = 700):
    interval = GATE_TF.get(tf, "1d")
    url = f"{GATE}/spot/candlesticks?currency_pair={pair}&interval={interval}&limit={limit}"
    rows = _json(url)
    if not isinstance(rows, list):
        raise DataError("Gate 行情返回异常")
    candles = []
    for r in rows:
        # [t, quote_vol, close, high, low, open, base_vol, closed]
        t, cv, c, h, l, o, bv = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        closed = len(r) > 7 and str(r[7]).lower() == "true"
        candles.append({"t": int(float(t)), "o": float(o), "h": float(h), "l": float(l),
                        "c": float(c), "v": float(bv), "_closed": closed})
    return _clean(candles)


def _gate_ticker(pair: str):
    key = f"tg_{pair}"
    cached, _ = cache_get(key, 25)
    if cached:
        return cached.get("data") or {}
    try:
        rows = _json(f"{GATE}/spot/tickers?currency_pair={pair}")
        d = rows[0] if isinstance(rows, list) and rows else {}
    except DataError:
        d = {}
    cache_put(key, {"data": d})
    return d


def _gate_info(pair: str):
    key = f"info_{pair}"
    cached, _ = cache_get(key, 86400)
    if cached:
        return cached.get("data") or {}
    try:
        d = _json(f"{GATE}/spot/currency_pairs/{pair}")
    except DataError:
        d = {}
    cache_put(key, {"data": d})
    return d


def fetch_crypto(symbol: str, code: str, tf: str):
    pair = code
    if "_" not in pair:
        pair = f"{pair}_USDT"
    # 尝试常见计价币
    candidates = [pair]
    base = pair.split("_")[0]
    for q in ("USDT", "USDC", "BTC"):
        p = f"{base}_{q}"
        if p not in candidates:
            candidates.append(p)
    last_err = None
    used = None
    rows = None
    ticker, info = {}, {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        ft = ex.submit(_gate_ticker, pair)
        fi = ex.submit(_gate_info, pair)
        for cand in candidates:
            try:
                rows = _gate_candles(cand, tf, limit=700 if tf in ("1d", "1w", "1M") else 600)
                if rows:
                    used = cand
                    break
            except DataError as e:
                last_err = e
                continue
        try:
            ticker = ft.result(timeout=12)
            info = fi.result(timeout=12)
        except Exception:  # noqa: BLE001
            pass
    if used and used != pair:
        ticker = _gate_ticker(used)
        info = _gate_info(used)
    if not rows or not used:
        raise NotFound(f"未找到交易对 {base}，请检查币种或改用 XXXUSDT 格式（{last_err}）")

    ticker, info = ticker or {}, info or {}
    base_name = info.get("base_name") or base
    price = float(ticker.get("last") or rows[-1]["c"])
    chg_pct = float(ticker.get("change_percentage") or 0)
    quote = {
        "price": price,
        "chg": price - price / (1 + chg_pct / 100) if chg_pct > -100 else 0.0,
        "chg_pct": chg_pct,
        "high": float(ticker.get("high_24h") or rows[-1]["h"]),
        "low": float(ticker.get("low_24h") or rows[-1]["l"]),
        "volume": float(ticker.get("base_volume") or 0),
        "volume_usd": float(ticker.get("quote_volume") or 0),
        "extra": {
            "24h额": float(ticker.get("quote_volume") or 0),
            "买一": float(ticker.get("highest_bid") or 0),
            "卖一": float(ticker.get("lowest_ask") or 0),
        },
    }
    meta = {
        "market": "crypto",
        "code": used,
        "display": used.replace("_", "/"),
        "name": base_name,
        "currency": used.rsplit("_", 1)[-1],
        "source": "Gate.io",
        "tz": "Asia/Shanghai",
    }
    return rows, quote, meta


# ---------------------------------------------------------------- 新浪美股
SINA_US_DAILY = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/x/US_MinKService.getDailyK?symbol={sym}"
SINA_US_MIN = "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/x/US_MinKService.getMinK?symbol={sym}&type={t}"
SINA_REF = "https://finance.sina.com.cn"


def _sina_rows(text: str, is_minute: bool):
    arr = parse_jsonp(text)
    if not isinstance(arr, list):
        raise NotFound("该代码在美股行情源中没有数据，请检查代码是否正确")
    out = []
    for r in arr:
        if not isinstance(r, dict):
            continue
        d = r.get("d", "")
        try:
            if is_minute:
                dt = datetime.strptime(d, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)
            else:
                dt = datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=NY)
            t = int(dt.timestamp())
            out.append({"t": t, "o": float(r["o"]), "h": float(r["h"]),
                        "l": float(r["l"]), "c": float(r["c"]), "v": float(r.get("v") or 0)})
        except (ValueError, KeyError, TypeError):
            continue
    return _clean(out)


def _sina_name(sym: str) -> str:
    try:
        raw = http_get(f"https://hq.sinajs.cn/list=gb_{sym.lower()}", referer=SINA_REF, retries=0)
        txt = raw.decode("gbk", "ignore")
        body = txt.split('="', 1)[-1].rsplit('"', 1)[0]
        return body.split(",")[0].strip() or sym.upper()
    except Exception:  # noqa: BLE001
        return sym.upper()


def fetch_us(symbol: str, code: str, tf: str):
    sym = code.upper()
    daily_cache = _cache_key("us", sym, "1d")
    if tf in ("1w", "1M"):
        payload, stale = _load_or_fetch(daily_cache, 300, lambda: _us_daily(sym))
        rows = payload["candles"]
        data = resample_daily_to(rows, "week" if tf == "1w" else "month", NY)
        quote = payload["quote"]
        meta = payload["meta"]
    elif tf == "4h":
        payload, stale = _load_or_fetch(_cache_key("us", sym, "1h"), 60, lambda: _us_intraday(sym, "60"))
        data = resample_session(payload["candles"], 4, NY)
        quote, meta = payload["quote"], payload["meta"]
    elif tf in ("1h", "30m", "15m"):
        t = {"1h": "60", "30m": "30", "15m": "5"}[tf]
        payload, stale = _load_or_fetch(_cache_key("us", sym, tf), 60, lambda: _us_intraday(sym, t))
        data = payload["candles"]
        if tf == "30m":
            data = resample(payload["candles"], 1800)
        if tf == "15m":
            data = resample(payload["candles"], 900)
        quote, meta = payload["quote"], payload["meta"]
    else:
        payload, stale = _load_or_fetch(daily_cache, 300, lambda: _us_daily(sym))
        data = payload["candles"]
        quote, meta = payload["quote"], payload["meta"]

    meta = dict(meta)
    meta["stale"] = stale
    meta["fetched_at"] = payload.get("fetched_at", payload.get("_saved", time.time()))
    return data, quote, meta


def _us_daily(sym: str):
    rows = _sina_rows(http_get(SINA_US_DAILY.format(sym=sym), referer=SINA_REF).decode("utf-8", "ignore"), False)
    if len(rows) < 30:
        raise NotFound(f"美股代码 {sym} 未获取到足够历史数据，请检查代码")
    rows = rows[-1200:]
    quote = _quote_from_rows(rows)
    meta = {"market": "us", "code": sym, "display": sym, "name": _sina_name(sym),
            "currency": "USD", "source": "新浪财经", "tz": "America/New_York", "stale": False}
    return {"candles": rows, "quote": quote, "meta": meta}


def _us_intraday(sym: str, t: str):
    rows = _sina_rows(http_get(SINA_US_MIN.format(sym=sym, t=t), referer=SINA_REF).decode("utf-8", "ignore"), True)
    if len(rows) < 20:
        raise NotFound(f"{sym} 的分钟线数据不足，请切换到日线分析")
    quote = _quote_from_rows(rows)
    meta = {"market": "us", "code": sym, "display": sym, "name": sym,
            "currency": "USD", "source": "新浪财经", "tz": "America/New_York", "stale": False}
    return {"candles": rows, "quote": quote, "meta": meta}


# ---------------------------------------------------------------- 腾讯 A 股
TX_KLINE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{period},,,{n},qfq"
TX_QUOTE = "https://qt.gtimg.cn/q={code}"


def fetch_cn(symbol: str, code: str, tf: str):
    if tf not in ("1d", "1w", "1M"):
        raise DataError("A股行情源仅支持日线、周线和月线，请切换周期")
    period = {"1d": "day", "1w": "week", "1M": "month"}[tf]
    key = _cache_key("cn", code, tf)
    payload, stale = _load_or_fetch(key, 120 if tf in ("1d", "1w", "1M") else 60,
                                    lambda: _cn_fetch(code, period))
    data = payload["candles"]
    quote, meta = payload["quote"], dict(payload["meta"], stale=stale)
    meta["fetched_at"] = payload.get("fetched_at", payload.get("_saved", time.time()))
    return data, quote, meta


def _cn_fetch(code: str, period: str):
    url = TX_KLINE.format(code=code, period=period, n=800)
    obj = _json(url)
    node = (obj.get("data") or {}).get(code) or {}
    rows = node.get("qfq" + period) or node.get(period) or []
    if not rows:
        raise NotFound(f"A股代码 {code} 未获取到数据")
    candles = []
    for r in rows:
        try:
            d = str(r[0])
            fmt = "%Y-%m-%d %H:%M" if len(d) > 10 else "%Y-%m-%d"
            dt = datetime.strptime(d, fmt).replace(tzinfo=CN)
            candles.append({"t": int(dt.timestamp()), "o": float(r[1]), "c": float(r[2]),
                            "h": float(r[3]), "l": float(r[4]), "v": float(r[5])})
        except (ValueError, IndexError, TypeError):
            continue
    candles = _clean(candles)
    if len(candles) < 20:
        raise NotFound(f"A股 {code} 数据不足")
    name, price, prev, high, low, vol = _cn_quote(code, candles)
    quote = {
        "price": price or candles[-1]["c"],
        "chg": (price - prev) if price and prev else 0.0,
        "chg_pct": ((price - prev) / prev * 100) if price and prev else 0.0,
        "high": high or candles[-1]["h"],
        "low": low or candles[-1]["l"],
        "volume": vol or candles[-1]["v"],
        "volume_usd": (vol or 0) * (price or candles[-1]["c"]),
        "extra": {},
    }
    meta = {"market": "cn", "code": code, "display": code, "name": name or code,
            "currency": "CNY", "source": "腾讯财经", "tz": "Asia/Shanghai", "stale": False}
    return {"candles": candles, "quote": quote, "meta": meta}


def _cn_quote(code: str, candles):
    try:
        raw = http_get(TX_QUOTE.format(code=code), referer="https://gu.qq.com", retries=0)
        txt = raw.decode("gbk", "ignore")
        body = txt.split('="', 1)[-1].rsplit('"', 1)[0]
        f = body.split("~")
        return f[1], float(f[3]), float(f[4]), float(f[33]), float(f[34]), float(f[36]) * 100
    except Exception:  # noqa: BLE001
        return code, None, None, None, None, None


# ---------------------------------------------------------------- 行情兜底
def _quote_from_rows(rows):
    if len(rows) < 2:
        return {}
    last, prev = rows[-1], rows[-2]
    chg = last["c"] - prev["c"]
    return {
        "price": last["c"],
        "chg": chg,
        "chg_pct": chg / prev["c"] * 100 if prev["c"] else 0.0,
        "high": last["h"],
        "low": last["l"],
        "volume": last["v"],
        "volume_usd": last["v"] * last["c"],
        "extra": {
            "昨收": prev["c"],
            "振幅": (last["h"] - last["l"]) / prev["c"] * 100 if prev["c"] else 0.0,
        },
    }


# ---------------------------------------------------------------- 统一入口
def _load_or_fetch(key: str, ttl: int, fn):
    cached, _ = cache_get(key, ttl)
    if cached:
        return cached, bool(cached.get("stale") or cached.get("meta", {}).get("stale"))
    try:
        payload = fn()
        payload["fetched_at"] = payload.get("meta", {}).get("fetched_at", time.time())
        if payload.get("stale") or payload.get("meta", {}).get("stale"):
            return payload, True
        cache_put(key, payload)
        return payload, False
    except Exception as e:  # noqa: BLE001
        stale = cache_stale(key)
        if stale:
            stale = dict(stale)
            stale["stale"] = True
            return stale, True
        raise e


def get_ohlc(symbol: str, market: str = "auto", tf: str = "1d"):
    tf = detect_tf(tf)
    market, code, display = normalize(symbol, market)
    if market == "cn" and tf not in ("1d", "1w", "1M"):
        raise DataError("A股行情源仅支持日线、周线和月线，请切换周期")
    key = _cache_key(market, code, tf)
    ttl = _ttl(market, tf)

    def load():
        if market == "crypto":
            rows, quote, meta = fetch_crypto(symbol, code, tf)
        elif market == "cn":
            rows, quote, meta = fetch_cn(symbol, code, tf)
        else:
            rows, quote, meta = fetch_us(symbol, code, tf)
        rows = _clean(rows)[-1000:]
        meta.update({"tf": tf, "tf_label": TF_LABEL[tf]})
        return {"candles": rows, "quote": quote, "meta": meta, "stale": bool(meta.get("stale"))}

    payload, stale = _load_or_fetch(key, ttl, load)
    candles = payload["candles"]
    if len(candles) < 30:
        raise DataError(f"{payload['meta'].get('display', symbol)} 的 {TF_LABEL[tf]} 数据不足（{len(candles)} 根）")

    meta = dict(payload["meta"])
    meta["stale"] = bool(stale or payload.get("stale") or meta.get("stale"))
    meta["fetched_at"] = payload.get("fetched_at", time.time())
    meta["bars"] = len(candles)
    meta["last_t"] = candles[-1]["t"]
    meta["last_closed"] = _is_closed(meta, candles, tf)
    meta["tf"] = tf
    meta["tf_label"] = TF_LABEL[tf]
    return candles, payload.get("quote", {}), meta


def _is_closed(meta, candles, tf) -> bool:
    tz = NY if meta["market"] == "us" else CN
    last = datetime.fromtimestamp(candles[-1]["t"], tz)
    now = datetime.now(tz)
    if meta["market"] == "crypto":
        dur = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
               "1w": 604800, "1M": 2592000}.get(tf, 86400)
        return time.time() >= candles[-1]["t"] + dur
    if tf in ("1d", "1w", "1M"):
        if tf == "1d":
            if last.date() < now.date():
                return True
            return now.hour >= (16 if meta["market"] == "us" else 15)
        if tf == "1w":
            return last.isocalendar()[:2] != now.isocalendar()[:2]
        return (last.year, last.month) != (now.year, now.month)
    # 分钟线：新浪/腾讯时间戳为 K 线结束时间
    return time.time() >= candles[-1]["t"] + 60


def get_quotes(symbols, market="auto"):
    """轻量批量报价（自选列表用）"""
    def one(s):
        try:
            candles, quote, meta = get_ohlc(s, market, "1d")
            return {"symbol": s, "ok": True, "display": meta["display"], "name": meta.get("name"),
                    "price": quote.get("price"), "chg_pct": quote.get("chg_pct"), "meta": meta}
        except Exception as e:  # noqa: BLE001
            return {"symbol": s, "ok": False, "error": str(e)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        return list(ex.map(one, symbols[:12]))
