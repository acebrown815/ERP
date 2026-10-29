"""Small load test: signs in and hits the busiest read endpoints concurrently, then prints latency percentiles.

    python tools/loadtest/loadtest.py --base http://localhost:3000 --email admin@example.com --password ... \
        --requests 300 --concurrency 10

Needs httpx (installed with the API's dev extras). Read-only: it never creates or changes data.
"""

import argparse
import asyncio
import statistics
import time
from datetime import date, timedelta

import httpx


def endpoints() -> list[str]:
    today = date.today()
    month_ago = (today - timedelta(days=30)).isoformat()
    return [
        "/api/v1/dashboard/company",
        "/api/v1/payment-entries?page_size=25",
        "/api/v1/accounts",
        f"/api/v1/reports/trial-balance?from={today.replace(month=1, day=1)}&to={today}",
        f"/api/v1/reports/profit-and-loss?from={month_ago}&to={today}",
        "/api/v1/reports/project-profitability",
        "/api/v1/reports/employee-salary",
        f"/api/v1/calendar/feed?from={month_ago}&to={today + timedelta(days=30)}",
        "/api/v1/tasks?page_size=100",
        "/api/v1/salary-periods",
    ]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:3000")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--requests", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=10)
    args = ap.parse_args()

    async with httpx.AsyncClient(base_url=args.base, timeout=60) as client:
        r = await client.post("/api/v1/auth/login", json={"email": args.email, "password": args.password})
        r.raise_for_status()
        urls = endpoints()
        timings: dict[str, list[float]] = {u.split("?")[0]: [] for u in urls}
        errors = 0
        sem = asyncio.Semaphore(args.concurrency)

        async def one(i: int) -> None:
            nonlocal errors
            url = urls[i % len(urls)]
            async with sem:
                t0 = time.perf_counter()
                res = await client.get(url)
                timings[url.split("?")[0]].append((time.perf_counter() - t0) * 1000)
                if res.status_code != 200:
                    errors += 1

        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(args.requests)))
        wall = time.perf_counter() - t0

    every = sorted(t for ts in timings.values() for t in ts)
    p = lambda q: every[min(len(every) - 1, int(len(every) * q))]  # noqa: E731
    print(f"{args.requests} requests, concurrency {args.concurrency}, {wall:.1f}s, {args.requests / wall:.1f} req/s, errors {errors}")
    print(f"all       p50 {p(0.5):7.0f} ms   p95 {p(0.95):7.0f} ms   max {every[-1]:7.0f} ms")
    for url, ts in timings.items():
        ts.sort()
        print(f"{url:45s} p50 {statistics.median(ts):6.0f} ms   p95 {ts[min(len(ts) - 1, int(len(ts) * 0.95))]:6.0f} ms")


if __name__ == "__main__":
    asyncio.run(main())
