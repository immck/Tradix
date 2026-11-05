import json
import math
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from core import analysis as an
from core import datasource as ds
from core import indicators as ta
import server


def candles(scale=1.0):
    rows = []
    for i in range(260):
        close = (100 + i * 0.12 + math.sin(i / 5) * 2) * scale
        rows.append(dict(t=1700000000 + i * 86400, o=close * 0.998,
                         h=close * 1.01, l=close * 0.99, c=close, v=1000 + i))
    return rows


class MarketTests(unittest.TestCase):
    def test_monthly_timeframe_is_not_daily(self):
        self.assertEqual(ds.detect_tf("1M"), "1M")
        self.assertEqual(ds.detect_tf("4H"), "4h")

    def test_explicit_market_and_supported_symbols(self):
        self.assertEqual(ds.normalize("600519")[0], "cn")
        self.assertEqual(ds.normalize("600519", "us")[0], "us")
        self.assertEqual(ds.normalize("BTC/USDT"), ("crypto", "BTC_USDT", "BTC/USDT"))
        self.assertEqual(ds.normalize("BRK.B", "us")[1], "BRK.B")

    def test_invalid_symbols_cannot_become_cache_paths(self):
        for symbol, market in [("BTC/../../file", "crypto"), ("C:\\file", "us"), ("NVDA", "cn")]:
            with self.subTest(symbol=symbol), self.assertRaises(ds.DataError):
                ds.normalize(symbol, market)

    def test_cn_intraday_rejected_before_reading_existing_bad_cache(self):
        with patch.object(ds, "cache_get") as cache:
            with self.assertRaises(ds.DataError):
                ds.get_ohlc("600519", tf="4h")
            cache.assert_not_called()

    def test_cn_weekly_cannot_fall_back_to_daily_rows(self):
        with patch.object(ds, "_json", return_value={"data": {"sh600519": {"qfqday": []}}}):
            with self.assertRaises(ds.DataError):
                ds._cn_fetch("sh600519", "week")

    def test_crypto_absolute_change_uses_previous_price(self):
        with patch.object(ds, "_gate_candles", return_value=candles()), \
             patch.object(ds, "_gate_ticker", return_value={"last": "110", "change_percentage": "10"}), \
             patch.object(ds, "_gate_info", return_value={}):
            _, quote, meta = ds.fetch_crypto("BTC", "BTC_USDT", "1d")
        self.assertAlmostEqual(quote["chg"], 10)
        self.assertEqual(meta["currency"], "USDT")

    def test_nested_stale_data_keeps_timestamp_and_is_not_recached(self):
        payload = {"meta": {"stale": True, "fetched_at": 123}, "stale": True}
        with patch.object(ds, "cache_get", return_value=(None, False)), \
             patch.object(ds, "cache_put") as put:
            result, stale = ds._load_or_fetch("test", 60, lambda: payload)
        self.assertTrue(stale)
        self.assertEqual(result["fetched_at"], 123)
        put.assert_not_called()

    def test_stale_flag_survives_a_fresh_outer_cache(self):
        payload = {"candles": candles(), "meta": {"market": "us", "stale": True}, "stale": True}
        with patch.object(ds, "cache_get", return_value=(payload, False)):
            _, _, meta = ds.get_ohlc("NVDA")
        self.assertTrue(meta["stale"])


class AnalysisTests(unittest.TestCase):
    def test_flat_rsi_is_neutral(self):
        self.assertEqual(ta.rsi([100.0] * 40)[-1], 50.0)
        self.assertEqual(ta.rsi(list(range(40)))[-1], 100.0)
        self.assertEqual(ta.rsi(list(range(40, 0, -1)))[-1], 0.0)

    def test_tiny_prices_and_macd_survive_full_api_serialization(self):
        rows = candles(1e-10)
        ind = ta.compute_all(rows)
        result = an.evaluate(rows, ind, "crypto")
        plan = an.build_plan(result, rows, ind, {}, "crypto", "1d")
        chart = server.build_chart(rows, ind, result, plan, {"market": "crypto", "tf": "1d"})
        decoded = json.loads(json.dumps(chart, allow_nan=False))
        self.assertGreater(decoded["candles"][-1][4], 0)
        self.assertAlmostEqual(decoded["candles"][-1][4] / rows[-1]["c"], 1, places=5)
        self.assertNotEqual(decoded["macd_dif"][-1], 0)
        self.assertNotEqual(an.money(rows[-1]["c"]), "0.00000")

    def test_nearby_structural_target_retains_poor_reward_ratio(self):
        result = {"bias": "long", "levels": {"supports": [], "resistances": [{"price": 100.9}]}}
        plan = an.build_plan(result, [{"c": 100}], {"atr": [2], "ema20": [100]}, {}, "crypto", "1d")
        self.assertEqual(plan["t1"], 100.9)
        self.assertEqual(plan["quality"], "poor")
        self.assertLess(plan["rr"], 1.2)

    def test_cn_position_uses_yuan_and_warns_about_shorting(self):
        result = {"bias": "short", "levels": {"supports": [{"price": 90}], "resistances": []}}
        plan = an.build_plan(result, [{"c": 100}], {"atr": [2], "ema20": [100]}, {}, "cn", "1d")
        self.assertIn("1 万元", plan["note"])
        self.assertNotIn("美元", plan["note"])
        self.assertIn("不能直接卖空", plan["note"])

    def test_stale_other_timeframes_do_not_inflate_resonance(self):
        overall = server.combine_overall({"score": 30, "bias": "long"},
                                         [{"score": 90, "weight": 1, "stale": True}])
        self.assertEqual(overall["score"], 30)
        self.assertEqual(overall["total"], 0)


class StaticFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.worker = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = "http://127.0.0.1:" + str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.worker.join()

    def test_static_assets_and_health_are_accessible(self):
        for path in ("/", "/app.js", "/api/health"):
            with urllib.request.urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)

    def test_encoded_windows_traversal_cannot_read_source(self):
        for path in ("/%2e%2e%5cserver.py", "/..%2fserver.py", "/D:%5cWindows%5cwin.ini"):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.url + path)
            self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
