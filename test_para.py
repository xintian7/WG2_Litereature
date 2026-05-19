"""Parallel load test for literature search backend.

Simulates 30 concurrent users sending keyword searches to OpenAlex,
then reports latency and error statistics.

Usage:
    python test_para.py
    python test_para.py --users 30 --requests-per-user 1 --timeout 20
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from pyalex import Works


DEFAULT_KEYWORDS = [
    "climate adaptation",
    "urban resilience",
    "food security",
    "water scarcity",
    "coastal flooding",
    "heatwave mortality",
    "climate migration",
    "nature-based solutions",
    "disaster risk reduction",
    "renewable energy transition",
    "carbon neutrality",
    "biodiversity loss",
    "sustainable agriculture",
    "public health climate",
    "climate justice",
    "vulnerability assessment",
    "extreme precipitation",
    "wildfire risk",
    "sea level rise",
    "ecosystem services",
]


@dataclass
class SearchResult:
    user_id: int
    request_id: int
    keyword: str
    ok: bool
    latency_s: float
    result_count: int
    error: str | None = None


def _run_single_search(
    user_id: int,
    request_id: int,
    keyword: str,
    start_year: int,
    end_year: int,
    per_page: int,
) -> SearchResult:
    started = time.perf_counter()
    try:
        query = (
            Works()
            .search(keyword)
            .filter(
                from_publication_date=f"{start_year}-01-01",
                to_publication_date=f"{end_year}-12-31",
            )
            .sort(relevance_score="desc")
        )
        data = query.get(per_page=per_page, page=1)
        latency = time.perf_counter() - started
        return SearchResult(
            user_id=user_id,
            request_id=request_id,
            keyword=keyword,
            ok=True,
            latency_s=latency,
            result_count=len(data or []),
        )
    except Exception as exc:  # noqa: BLE001
        latency = time.perf_counter() - started
        return SearchResult(
            user_id=user_id,
            request_id=request_id,
            keyword=keyword,
            ok=False,
            latency_s=latency,
            result_count=0,
            error=str(exc),
        )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def run_parallel_test(
    users: int,
    requests_per_user: int,
    start_year: int,
    end_year: int,
    per_page: int,
) -> list[SearchResult]:
    tasks: list[tuple[int, int, str]] = []
    for user_id in range(1, users + 1):
        for request_id in range(1, requests_per_user + 1):
            keyword = random.choice(DEFAULT_KEYWORDS)
            tasks.append((user_id, request_id, keyword))

    results: list[SearchResult] = []

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=users) as executor:
        futures = {
            executor.submit(
                _run_single_search,
                user_id,
                request_id,
                keyword,
                start_year,
                end_year,
                per_page,
            ): (user_id, request_id, keyword)
            for (user_id, request_id, keyword) in tasks
        }

        for future in as_completed(futures):
            results.append(future.result())
    wall_elapsed = time.perf_counter() - wall_start

    print("\n=== Parallel Search Load Test (test_para) ===")
    print(f"Users (concurrent): {users}")
    print(f"Requests per user: {requests_per_user}")
    print(f"Total requests: {len(tasks)}")
    print(f"Total wall time: {wall_elapsed:.2f}s")

    return results


def print_summary(results: list[SearchResult]) -> None:
    total = len(results)
    success = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]

    latencies = sorted(r.latency_s for r in results)
    success_latencies = sorted(r.latency_s for r in success)

    print("\n--- Summary ---")
    print(f"Success: {len(success)}/{total}")
    print(f"Errors: {len(failed)}/{total}")

    if latencies:
        print(f"Avg latency (all): {statistics.mean(latencies):.2f}s")
        print(f"Median latency (all): {statistics.median(latencies):.2f}s")
        print(f"P95 latency (all): {_percentile(latencies, 0.95):.2f}s")
        print(f"Max latency (all): {max(latencies):.2f}s")

    if success_latencies:
        print(f"Avg latency (success): {statistics.mean(success_latencies):.2f}s")

    # A simple delay signal threshold for quick interpretation.
    delayed_threshold_s = 3.0
    delayed_count = sum(1 for r in results if r.latency_s > delayed_threshold_s)
    print(
        f"Delayed responses > {delayed_threshold_s:.1f}s: {delayed_count}/{total}"
    )

    if failed:
        print("\n--- Error details ---")
        for idx, r in enumerate(failed, start=1):
            print(
                f"{idx}. user={r.user_id} request={r.request_id} "
                f"keyword='{r.keyword}' latency={r.latency_s:.2f}s error={r.error}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate concurrent literature search users and measure delays/errors."
    )
    parser.add_argument("--users", type=int, default=30, help="Concurrent users.")
    parser.add_argument(
        "--requests-per-user",
        type=int,
        default=1,
        help="How many searches each user performs.",
    )
    parser.add_argument("--start-year", type=int, default=2000, help="Start year filter.")
    parser.add_argument("--end-year", type=int, default=2026, help="End year filter.")
    parser.add_argument(
        "--per-page",
        type=int,
        default=20,
        help="Number of records requested from OpenAlex per search.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible keyword selection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.users < 1:
        raise ValueError("--users must be >= 1")
    if args.requests_per_user < 1:
        raise ValueError("--requests-per-user must be >= 1")
    if args.start_year > args.end_year:
        raise ValueError("--start-year must be <= --end-year")
    if args.per_page < 1:
        raise ValueError("--per-page must be >= 1")

    random.seed(args.seed)

    results = run_parallel_test(
        users=args.users,
        requests_per_user=args.requests_per_user,
        start_year=args.start_year,
        end_year=args.end_year,
        per_page=args.per_page,
    )
    print_summary(results)


if __name__ == "__main__":
    main()
