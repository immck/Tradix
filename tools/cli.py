"""命令行快速分析：python tools/cli.py BTC 1d"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analysis as an  # noqa: E402
from core import datasource as ds  # noqa: E402
from core import indicators as ta  # noqa: E402


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    tf = sys.argv[2] if len(sys.argv) > 2 else "1d"
    market = sys.argv[3] if len(sys.argv) > 3 else "auto"
    candles, quote, meta = ds.get_ohlc(symbol, market, tf)
    ind = ta.compute_all(candles)
    res = an.evaluate(candles, ind, meta["market"])
    plan = an.build_plan(res, candles, ind, quote, meta["market"], tf)

    print(f"\n{meta['display']}  {meta.get('name')}  [{meta['market']} · {meta['tf_label']}]  {meta['source']}")
    print(f"价格 {quote.get('price')}  涨跌 {quote.get('chg_pct'):+.2f}%  K线 {meta['bars']} 根  最新 {meta['last_t']}")
    print(f"\n结论: {res['verdict']}  评分 {res['score']:+.1f}  置信度 {res['confidence']:.0f}%")
    print("摘要:", res["summary"])
    print(f"\n结构: {res['structure']['label']} | 突破: {res['structure']['breakout']}")
    print(f"关键位: 支撑 {[s['price'] for s in res['levels']['supports']]}")
    print(f"        阻力 {[r['price'] for r in res['levels']['resistances']]}")
    print("\n指标矩阵:")
    for c in res["components"]:
        bar = "#" * int(abs(c["score"]) / 10)
        print(f"  {c['label']:<8} {c['score']:>6.1f}  {c['state']:<18} {c['detail']}")
    print("\n交易计划:", json.dumps(plan, ensure_ascii=False, indent=2))
    print("\n信号:")
    for s in res["signals"]:
        print(f"  [{s['type']}] {s['title']} — {s['detail']}")
    print("\n风险:")
    for r in res["risks"]:
        print(f"  ({r['level']}) {r['text']}")


if __name__ == "__main__":
    main()
