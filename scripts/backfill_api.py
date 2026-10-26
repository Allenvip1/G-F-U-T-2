#!/usr/bin/env python3
"""一次性补最近几天的缺口：CME 官网"结算价"页面的数据接口只能查最近约 5 个交易日，但能给出每个合约月份的成交量和持仓量。
对 data/futures_total.csv 里缺失的这些日子，用它补上 ES、NQ 的逐合约数据和合计（已有日期不覆盖）。
口径和日报略有不同（接口的数据时间点和成交量口径不同，差异约 1%~2%），持仓量取下一个交易日的接口数（见 main 的说明）。
用法： python scripts/backfill_api.py [YYYY-MM-DD ...]   不带日期就检查最近 8 个工作日
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fut

IDS = {"es": 133, "nq": 146}
URL = "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/{pid}/FUT?strategy=DEFAULT&pageSize=500&isProtected&_t=1&tradeDate={d}"
MON = {m.title(): m for m in fut.MONTHS}


def fetch(pid: int, day: dt.date):
    from curl_cffi import requests
    headers = {"Referer": "https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.settlements.html", "Accept": "application/json, text/plain, */*"}
    r = requests.get(URL.format(pid=pid, d=day.strftime("%m/%d/%Y")), headers=headers, impersonate="chrome120", timeout=60)
    r.raise_for_status()
    return json.loads(r.text).get("settlements", [])


def num(s) -> int:
    s = str(s).replace(",", "").strip()
    return int(s) if s.isdigit() else 0


def next_workday(d: dt.date) -> dt.date:
    d += dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def parse_rows(rows):
    """-> ({合约月份标签: (成交量, 持仓量)}, (总成交量, 总持仓量))"""
    per, total = {}, None
    for x in rows:
        if x["month"] == "Total":
            total = (num(x["volume"]), num(x["openInterest"]))
            continue
        mon, yy = x["month"].split()
        if mon.title() in MON:
            per[f"{MON[mon.title()]}{yy}"] = (num(x["volume"]), num(x["openInterest"]))
    return per, total


def main() -> None:
    """接口里 D 日的"持仓量"其实是 D-1 日收盘的持仓量（持仓量要隔天才公布），日报里 D 日的持仓量则是 D 日收盘的数。
    所以要补日报口径的 D 日：成交量取接口 D 日，持仓量取接口"下一个交易日"，持仓量变化 = 下一个交易日 − D 日 的接口持仓量。"""
    today = dt.date.today()
    days = [dt.date.fromisoformat(a) for a in sys.argv[1:]] or [today - dt.timedelta(days=i) for i in range(8, 0, -1) if (today - dt.timedelta(days=i)).weekday() < 5]
    tot = fut.read_totals()
    added = 0
    for day in sorted(days):
        for metal, pid in IDS.items():
            if (day.isoformat(), metal) in tot:
                continue
            per_d, t_d = parse_rows(fetch(pid, day))                       # D 日：成交量
            per_n, t_n = parse_rows(fetch(pid, next_workday(day)))        # 下一个交易日：D 日收盘的持仓量
            if not t_d or not t_n or t_d[0] == 0 or t_n[1] == 0:
                print(f"{day} {metal}: 接口没有数据，跳过")
                continue
            chg = t_n[1] - t_d[1]
            contracts = [(metal, m, fut.expiry_date(2000 + int(m[3:]), fut.MONTHS[m[:3]]), per_d.get(m, (0, 0))[0], v[1], v[1] - per_d.get(m, (0, 0))[1]) for m, v in per_n.items()]
            fut.upsert(day, contracts)
            tot[(day.isoformat(), metal)] = {"date": day.isoformat(), "metal": metal, "vol": t_d[0], "oi": t_n[1], "oi_chg": chg}
            added += 1
            print(f"{day} {metal}: 成交量 {t_d[0]:,} 持仓量 {t_n[1]:,} 变化 {chg:+,}")
    fut.write_totals(tot)
    print(f"新增 {added} 条")


if __name__ == "__main__":
    main()
