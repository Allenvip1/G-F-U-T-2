#!/usr/bin/env python3
"""从 Yahoo Finance 抓 E-mini 标普 500、纳指 100 期货的日线，写入 data/price_es.csv、data/price_nq.csv。

使用连续合约 ES=F、NQ=F，每次整体覆盖。Yahoo 日线有个毛病：美东 18:00 新交易日开盘之后到午夜之前，最后一根日线会被"新交易日刚开盘的几个小时"顶替，
所以用小时线合成的交易日做修复（见 fix_latest_rows）。只用标准库。任何一个品种抓取失败都只告警并保留旧文件。
"""
import csv
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
URL = "https://{host}/v8/finance/chart/{sym}?range={rng}&interval={interval}"
UA = "Mozilla/5.0"   # Yahoo 对更长的浏览器 UA 反而返回 429，简短的 UA 可用


def fetch(sym: str, rng: str = "2y", interval: str = "1d") -> dict:
    last_err = None
    for attempt in range(3):
        for host in HOSTS:
            url = URL.format(host=host, sym=sym, rng=rng, interval=interval)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:
                last_err = e
                try:
                    out = subprocess.run(["curl", "-s", "-m", "40", "-A", UA, url], capture_output=True, check=True).stdout
                    return json.loads(out.decode("utf-8"))
                except Exception as e2:
                    last_err = e2
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Yahoo 请求失败：{last_err}")


def to_rows(payload: dict, with_volume: bool = False):
    results = payload["chart"]["result"]
    if not results:
        raise ValueError("Yahoo 没有这个代码的数据")
    res = results[0]
    off = res["meta"]["gmtoffset"]
    q = res["indicators"]["quote"][0]
    seen = {}
    for i, t in enumerate(res["timestamp"]):
        if q["close"][i] is None or q["open"][i] is None or q["high"][i] is None or q["low"][i] is None:
            continue
        day = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date().isoformat()
        row = (day, round(q["open"][i], 2), round(q["high"][i], 2), round(q["low"][i], 2), round(q["close"][i], 2))
        if with_volume:
            row += (q["volume"][i] or 0,)
        seen.setdefault(day, row)      # Yahoo 末尾常有同一天的重复/盘中行：同一天只保留第一条
    return sorted(seen.values())


def yahoo_sessions(sym: str, rng: str = "7d"):
    """用 Yahoo 小时线合成"交易日"：COMEX 期货每个交易日从前一天美东 18:00 到当天 17:00。
    返回按日期排序的 [(日期, [开, 高, 低, 收], 小时线根数)]。"""
    res = fetch(sym, rng, "1h")["chart"]["result"]
    if not res:
        raise ValueError("Yahoo 没有这个代码的小时线")
    res = res[0]
    off, q = res["meta"]["gmtoffset"], res["indicators"]["quote"][0]
    sess = {}
    for i, t in enumerate(res["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        et = dt.datetime.fromtimestamp(t + off, dt.timezone.utc)          # 交易所本地时间
        day = (et + dt.timedelta(hours=6)).date()                         # 18:00 起算下一个交易日
        if day.weekday() >= 5:
            continue                                                      # 周五 18:00 之后到周日 18:00 休市
        r = sess.get(day.isoformat())
        if r is None:
            sess[day.isoformat()] = [q["open"][i], q["high"][i], q["low"][i], q["close"][i], 1]
        else:
            r[1] = max(r[1], q["high"][i]); r[2] = min(r[2], q["low"][i]); r[3] = q["close"][i]; r[4] += 1
    return [(d, [round(x, 2) for x in v[:4]], v[4]) for d, v in sorted(sess.items())]


def fix_latest_rows(rows, sym: str):
    """Yahoo 日线有个毛病：美东 18:00 新交易日开盘之后到午夜之前，最后一根日线是"新交易日刚开盘的几个小时"，
    却贴着刚结束那一天的日期，把那天完整的日线顶替掉了（北京时间约 06:00~12:00 抓取会撞上，手动运行尤其容易）。
    用小时线合成的交易日识别并修复：某天的日线若开盘价等于"下一个交易日"的开盘价（而不是自己的开盘价），就判定被污染，
    改用该日自己的小时线合成值；日线里缺失的完整交易日也用小时线补上。小时线抓不到时原样返回。"""
    try:
        sess = yahoo_sessions(sym)
    except Exception as e:
        print(f"【警告】{sym} 小时线抓取失败，最后一根日线可能不准：{e}", file=sys.stderr)
        return rows
    by = {r[0]: tuple(r[:5]) for r in rows}
    fixed = []
    for i, (d, ohlc, n) in enumerate(sess):
        row = by.get(d)
        nxt = sess[i + 1][1] if i + 1 < len(sess) else None
        corrupted = bool(row and nxt and abs(row[1] - nxt[0]) <= 0.011 and abs(row[1] - ohlc[0]) > 0.011)   # 日线的开盘价 = 下一个交易日的开盘价、且不是自己的开盘价
        if (corrupted or row is None) and n >= 20:
            by[d] = (d, *ohlc)
            fixed.append(d)
        elif corrupted:
            del by[d]
    if fixed:
        print(f"{sym}: 用小时线修复了 {len(fixed)} 根被污染/缺失的日线 {fixed}")
    return [by[k] for k in sorted(by)]


def write_rows(fname: str, rows) -> None:
    with (DATA / fname).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close"])
        w.writerows(r[:5] for r in rows)


def read_rows(fname: str):
    p = DATA / fname
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [(r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in csv.DictReader(f)]


SYMBOLS = {"ES=F": "price_es.csv", "NQ=F": "price_nq.csv"}


def main() -> None:
    DATA.mkdir(exist_ok=True)
    for sym, fname in SYMBOLS.items():
        try:
            rows = to_rows(fetch(sym))
            if len(rows) < 100:
                raise ValueError(f"只取到 {len(rows)} 行，疑似异常")
            rows = fix_latest_rows(rows, sym)
            write_rows(fname, rows)
            print(f"【成功】{sym} -> {fname}：{len(rows)} 行，{rows[0][0]} ~ {rows[-1][0]}")
        except Exception as e:
            print(f"【警告】{sym} 抓取失败，保留旧文件：{e}", file=sys.stderr)


if __name__ == "__main__":
    main()
