#!/usr/bin/env python3
"""一次性补历史：PG11 的 Wayback 存档有缺日，缺的日子用同一时期的汇总页 PG01C（股指期货和期权汇总）补上 ES、NQ 的总成交量、总持仓量，
写入 data/futures_total.csv（已有日期不覆盖）。汇总页只有合计，没有分合约月份。
用法： python scripts/backfill_total.py [起始日期YYYYMMDD，默认20260101]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fut
import backfill

ORIG = "cmegroup.com/daily_bulletin/current/Section01C_Summary_Volume_And_Open_Interest_Equity_Index_Futures_And_Options.pdf"
# ES E-MINI S&P 500 FUTURES <电子盘量> <场内量> <合计量> <持仓量> (+|-) <变化> ...
LINE = re.compile(r"^(ES|NQ) E-MINI [A-Z0-9& ]*FUTURES (\d+) (\d+) (\d+) (\d+) (?:([+-]) (\d+)|UNCH)")


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "20260101"
    idx = json.loads(backfill.get(f"https://web.archive.org/cdx/search/cdx?url={ORIG}&output=json&fl=timestamp&filter=statuscode:200&from={start}&limit=1000"))
    stamps = [r[0] for r in idx[1:]]
    have = fut.read_totals()
    added = 0
    print(f"共 {len(stamps)} 份存档")
    for ts in stamps:
        try:
            data = backfill.get(f"https://web.archive.org/web/{ts}id_/https://www.{ORIG}")
            if not data.startswith(b"%PDF"):
                continue
            text = fut.pdf_text(data)
            day = fut.bulletin_date(text).isoformat()
            for ln in text.splitlines():
                m = LINE.match(ln.strip())
                if not m:
                    continue
                metal = "es" if m.group(1) == "ES" else "nq"
                key = (day, metal)
                if key in have:
                    continue
                chg = 0 if m.group(6) is None else int(m.group(7)) * (1 if m.group(6) == "+" else -1)
                have[key] = {"date": day, "metal": metal, "vol": int(m.group(2)), "oi": int(m.group(5)), "oi_chg": chg}
                added += 1
        except Exception as e:                                       # noqa: BLE001
            print(ts, "失败：", e)
    fut.write_totals(have)
    print(f"新增 {added} 条，合计 {len(have)} 条")


if __name__ == "__main__":
    main()
