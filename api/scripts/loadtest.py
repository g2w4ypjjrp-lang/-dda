"""Basit yük testi: herkese açık okuma uçlarına eşzamanlı istek, gecikme yüzdelikleri.

Kullanım (çalışan API'ye karşı; yalnızca kendi ortamınızda):
    uv run python scripts/loadtest.py --base http://127.0.0.1:8080 --concurrency 20 --duration 30

Çıktı JSON'dur: uç başına istek sayısı, hata sayısı, p50/p95/p99 ve en uzun süre (ms), toplam RPS.
Bir "geçti/kaldı" eşiği ``--p95-ms`` ile verilir (varsayılan 300 ms) ve 5xx oranı %0 olmalıdır.
Sonuçlar yalnızca ölçüldüğü makine ve veri hacmi için geçerlidir; üretim kapasitesi ayrıca
ölçülmelidir (M-G3 dağıtımından sonra).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict

import httpx

PATHS = (
    "/v1/design",
    "/v1/notice",
    "/v1/football/status",
    "/v1/football/competitions",
    "/v1/football/fixtures?date={today}",
    "/v1/football/fixtures?status=finished&limit=50",
    "/v1/predictions",
    "/v1/predictions/performance",
    "/v1/billing/plans",
    "/v1/content/faq",
    "/health",
)


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[k], 1)


async def worker(
    client: httpx.AsyncClient,
    paths: list[str],
    stop: float,
    lat: dict[str, list[float]],
    errs: dict[str, int],
    other: dict[str, int],
    idx: int,
) -> None:
    i = idx
    while time.perf_counter() < stop:
        path = paths[i % len(paths)]
        i += 1
        t0 = time.perf_counter()
        try:
            r = await client.get(path)
            status = r.status_code
        except httpx.HTTPError:
            status = 599
        lat[path].append((time.perf_counter() - t0) * 1000)
        if status >= 500:
            errs[path] += 1
        elif status >= 300:
            other[path] += 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--p95-ms", type=float, default=300.0)
    args = ap.parse_args()
    today = time.strftime("%Y-%m-%d", time.gmtime())
    paths = [p.format(today=today) for p in PATHS]
    lat: dict[str, list[float]] = defaultdict(list)
    errs: dict[str, int] = defaultdict(int)
    other: dict[str, int] = defaultdict(int)  # 3xx/4xx (ör. hız sınırı 429)
    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency
    )
    async with httpx.AsyncClient(base_url=args.base, timeout=10.0, limits=limits) as client:
        for p in paths:  # ısınma
            await client.get(p)
        started = time.perf_counter()
        stop = started + args.duration
        await asyncio.gather(
            *(worker(client, paths, stop, lat, errs, other, n) for n in range(args.concurrency))
        )
        elapsed = time.perf_counter() - started
    total = sum(len(v) for v in lat.values())
    every = [x for v in lat.values() for x in v]
    report = {
        "base": args.base,
        "concurrency": args.concurrency,
        "duration_s": round(elapsed, 1),
        "requests": total,
        "rps": round(total / elapsed, 1),
        "errors_5xx": sum(errs.values()),
        "non_2xx_other": sum(other.values()),
        "overall": {
            "p50": pct(every, 0.5),
            "p95": pct(every, 0.95),
            "p99": pct(every, 0.99),
            "max": round(max(every), 1),
        },
        "paths": {
            p: {
                "n": len(v),
                "errors_5xx": errs[p],
                "p50": pct(v, 0.5),
                "p95": pct(v, 0.95),
                "p99": pct(v, 0.99),
                "mean": round(statistics.fmean(v), 1),
            }
            for p, v in lat.items()
        },
    }
    report["passed"] = report["errors_5xx"] == 0 and report["overall"]["p95"] <= args.p95_ms
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
