"""
Verification script for Phase 4: Content-Hash Cache.

Runs the same question twice against the API and compares costs.
The second run should be cheaper (cache hits on LLM calls → $0 cost).

Usage:
    docker compose up -d
    python scripts/verify_cache.py

Requires: the full stack running (Postgres, Redis, app on port 8000).
"""
import sys
import httpx


BASE_URL = "http://localhost:8000"
QUESTION = "What is 25 * 47?"


def run_question(label: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    resp = httpx.post(f"{BASE_URL}/run", json={"question": QUESTION}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    run_id = data["run_id"]
    status = data["status"]
    total_cost = float(data["total_cost_usd"])

    print(f"  Run ID:     {run_id}")
    print(f"  Status:     {status}")
    print(f"  Total cost: ${total_cost:.8f}")

    spans = data.get("spans", [])
    print(f"  Spans:      {len(spans)}")
    for s in spans:
        cache_flag = " [CACHE HIT]" if s.get("cache_hit") else ""
        print(f"    - {s['step_type']:10s}  cost=${float(s['cost_usd']):.8f}  "
              f"tokens_in={s['tokens_in']}  tokens_out={s['tokens_out']}{cache_flag}")

    return data


def main():
    print("Phase 4 Cache Verification")
    print("=" * 60)
    print(f"Question: {QUESTION}")

    try:
        health = httpx.get(f"{BASE_URL}/health", timeout=5)
        health.raise_for_status()
    except Exception as e:
        print(f"\nERROR: Cannot reach {BASE_URL}/health — is the stack running?")
        print(f"  {e}")
        print("\nStart with: docker compose up -d")
        sys.exit(1)

    run1 = run_question("Run 1 (cache miss expected)")
    run2 = run_question("Run 2 (cache hit expected)")

    cost1 = float(run1["total_cost_usd"])
    cost2 = float(run2["total_cost_usd"])

    print(f"\n{'='*60}")
    print("  COMPARISON")
    print(f"{'='*60}")
    print(f"  Run 1 cost: ${cost1:.8f}")
    print(f"  Run 2 cost: ${cost2:.8f}")

    if cost1 > 0 and cost2 < cost1:
        savings = ((cost1 - cost2) / cost1) * 100
        print(f"  Savings:    {savings:.1f}%")
        print(f"\n  PASS: Second run is cheaper (cache working)")
    elif cost2 == 0 and cost1 > 0:
        print(f"  Savings:    100%")
        print(f"\n  PASS: Second run cost $0 (full cache hit)")
    else:
        print(f"\n  NOTE: Costs are equal — cache may not have had effect.")
        print(f"  This can happen if Redis is not running or TTL expired.")

    spans2 = run2.get("spans", [])
    cache_hits = sum(1 for s in spans2 if s.get("cache_hit"))
    print(f"\n  Run 2 cache hits: {cache_hits}/{len(spans2)} spans")


if __name__ == "__main__":
    main()
