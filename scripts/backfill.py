#!/usr/bin/env python3
"""一次性补历史：从 Wayback Machine 下载 PG11 的历史存档（2026 年内），解析后写入 data/futures_oi.csv。
同一个公报日有多份存档（初步版/最终版）时，按"存档时间越晚越优先"依次写入，后写的覆盖先写的。
用法： python scripts/backfill.py [起始日期YYYYMMDD，默认20260101]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fut

ORIG = "cmegroup.com/daily_bulletin/current/Section11_Equity_And_Index_Futures.pdf"
CACHE = Path(__file__).resolve().parent.parent / "_pdf_cache"


def get(url: str, tries: int = 4) -> bytes:
    from curl_cffi import requests
    for i in range(tries):
        try:
            r = requests.get(url, impersonate="chrome120", timeout=90)
            r.raise_for_status()
            return r.content
        except Exception as e:
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(err)


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "20260101"
    idx = json.loads(get(f"https://web.archive.org/cdx/search/cdx?url={ORIG}&output=json&fl=timestamp&filter=statuscode:200&from={start}&limit=1000"))
    stamps = [r[0] for r in idx[1:]]
    CACHE.mkdir(exist_ok=True)
    print(f"共 {len(stamps)} 份存档")
    seen = {}
    for ts in stamps:
        f = CACHE / f"{ts}.pdf"
        try:
            if not f.exists():
                f.write_bytes(get(f"https://web.archive.org/web/{ts}id_/https://www.{ORIG}"))
            data = f.read_bytes()
            if not data.startswith(b"%PDF"):
                print(ts, "不是 PDF，跳过")
                continue
            day = fut.process(data)
            seen.setdefault(day, []).append(ts)
            print(ts, "->", day)
        except Exception as e:
            print(ts, "失败：", e)
    print(f"完成：{len(seen)} 个公报日")


if __name__ == "__main__":
    main()
