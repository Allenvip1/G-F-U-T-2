#!/usr/bin/env python3
"""把 data/*.csv 合成页面数据，写进 index.html 的 <script id="fut-data">（页面是纯静态的，数据内嵌）。
"""
import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML = ROOT / "index.html"


def rd(name):
    p = DATA / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    totals = defaultdict(list)
    for r in rd("futures_total.csv"):
        totals[r["metal"]].append([r["date"], int(r["vol"]), int(r["oi"]), int(r["oi_chg"])])
    for metal, pf, vf in (("es", "price_es.csv", "vix.csv"), ("nq", "price_nq.csv", "vxn.csv")):
        total = sorted(totals[metal])
        out[metal] = {
            "price": [[r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])] for r in rd(pf)],
            "total": total,
            "vol": [[r["date"], float(r["close"])] for r in rd(vf) if total and r["date"] >= total[0][0]],     # 标普 VIX / 纳指 VXN（波动率指数收盘）
        }
    html = HTML.read_text(encoding="utf-8")
    # 数据没变化就不重写页面：这样"页面更新于"保持上一次真正更新数据的时间，也不会产生空提交去触发多余的部署
    old = re.search(r'<script id="fut-data">window\.FUT_DATA=(.*?);</script>', html, flags=re.S)
    if old:
        try:
            prev = json.loads(old.group(1))
            if {k: v for k, v in prev.items() if k != "updated"} == {k: v for k, v in out.items() if k != "updated"}:
                print("数据没有变化，保持页面不变。")
                return
        except ValueError:
            pass
    js = "window.FUT_DATA=" + json.dumps(out, separators=(",", ":"), ensure_ascii=False) + ";"
    new, n = re.subn(r'(<script id="fut-data">).*?(</script>)', lambda m: m.group(1) + js + m.group(2), html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("index.html 里没找到 <script id=\"fut-data\">")
    HTML.write_text(new, encoding="utf-8")
    print(f"【成功】已写入 index.html：标普 {len(out['es']['total'])} 天，纳指 {len(out['nq']['total'])} 天")


if __name__ == "__main__":
    main()
