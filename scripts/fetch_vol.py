#!/usr/bin/env python3
"""从 CBOE 官网下载标普 500 波动率指数 VIX（用 SPX 期权）、纳指 100 波动率指数 VXN（用 NDX 期权） 的每日收盘，写入 data/vix.csv、data/vxn.csv（date,close）。
VIX、VXN 由 CBOE 用指数期权算出未来 30 天的年化隐含波动率（%）。任何一个失败只告警、保留旧文件。
"""
import csv
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/{sym}_History.csv"
SERIES = {"VIX": ("vix.csv", "CLOSE"), "VXN": ("vxn.csv", "CLOSE")}      # 代码 -> (输出文件, 收盘价列名)


def fetch(sym: str, col: str):
    for attempt in range(3):                                      # 偶尔握手失败，重试几次
        try:
            out = subprocess.run(["curl", "-sL", "-m", "60", "-A", "Mozilla/5.0", URL.format(sym=sym)], capture_output=True, check=True).stdout.decode("utf-8-sig")
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(2)
    rows = []
    for r in csv.DictReader(out.splitlines()):
        try:
            d = dt.datetime.strptime(r["DATE"].strip(), "%m/%d/%Y").date().isoformat()
            rows.append((d, round(float(r[col]), 2)))
        except (KeyError, ValueError):
            continue
    rows.sort()
    if len(rows) < 500:
        raise ValueError(f"{sym} 只取到 {len(rows)} 行，疑似异常")
    return rows


def main() -> None:
    DATA.mkdir(exist_ok=True)
    for sym, (fname, col) in SERIES.items():
        try:
            rows = fetch(sym, col)
            with (DATA / fname).open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["date", "close"])
                w.writerows(rows)
            print(f"【成功】{sym} -> {fname}：{len(rows)} 行，{rows[0][0]} ~ {rows[-1][0]}")
        except Exception as e:                                    # noqa: BLE001
            print(f"【警告】{sym} 抓取失败，保留旧文件：{e}", file=sys.stderr)


if __name__ == "__main__":
    main()
