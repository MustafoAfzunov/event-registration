"""Concurrency stress test against a RUNNING stack, over real HTTP (through nginx to the
2-worker backend), printing the invariants that must hold.

Phase 1 (registration storm): N distinct emails + D emails each sent K times with case/space
variants, ALL fired at once at an event with C seats.
Phase 2 (mixed): X seat holders cancel (manage links taken from their real ticket emails in
Mailpit) while Y newcomers register, all at once. Freed seats must go to the oldest waitlisters.

Run (dev stack):    make stress
Run (E2E stack):    E2E_WITH_STRESS=1 scripts/e2e.sh   (also part of `make proof`)
Exit code 1 if any invariant is violated.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

PASSWORD = os.environ.get("ORGANIZER_PASSWORD", "organizer-dev-password")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


async def timed(coro: Any, latencies: list[float]) -> httpx.Response:
    start = time.perf_counter()
    try:
        return await coro  # type: ignore[no-any-return]
    finally:
        latencies.append(time.perf_counter() - start)


def pct(values: list[float], q: float) -> float:
    return sorted(values)[min(len(values) - 1, int(q * len(values)))] * 1000 if values else 0.0


async def admin_state(admin: httpx.AsyncClient, event_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stats = (await admin.get(f"/api/admin/events/{event_id}/stats")).json()
    rows = (await admin.get(f"/api/admin/events/{event_id}/registrations")).json()
    return stats, rows


def common_invariants(report: Report, phase: str, capacity: int, stats: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    active = [r for r in rows if r["status"] != "cancelled"]
    holders = [r for r in rows if r["status"] in ("confirmed", "checked_in")]
    waiting = sorted((r for r in rows if r["status"] == "waitlisted"), key=lambda r: r["waitlist_position"])
    dup = [e for e, n in Counter(r["email"].strip().lower() for r in active).items() if n > 1]
    report.check(f"{phase}: confirmed <= limit", len(holders) <= capacity, f"{len(holders)} seat holders, limit {capacity}")
    report.check(f"{phase}: no duplicate emails", not dup, f"{len(dup)} emails with >1 active registration {dup[:3]}")
    report.check(
        f"{phase}: no free seat while people wait",
        not (len(holders) < capacity and waiting),
        f"{capacity - len(holders)} free, {len(waiting)} waiting",
    )
    report.check(
        f"{phase}: waitlist positions 1..n",
        [r["waitlist_position"] for r in waiting] == list(range(1, len(waiting) + 1)),
        f"{len(waiting)} waitlisted",
    )
    report.check(
        f"{phase}: stats API == list",
        (stats["registered"], stats["waitlisted"]) == (len(holders), len(waiting)),
        f"stats {stats['registered']}/{stats['waitlisted']} vs list {len(holders)}/{len(waiting)}",
    )


async def manage_tokens(mailpit: str, title: str, want: int) -> dict[str, str]:
    """email -> manage token, from the real ticket emails the worker sent."""
    found: dict[str, str] = {}
    async with httpx.AsyncClient(base_url=mailpit, timeout=10) as mp:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and len(found) < want:
            r = await mp.get("/api/v1/search", params={"query": f'subject:"Your ticket for {title}"', "limit": 500})
            messages = r.json()["messages"]
            for m in messages:
                address = m["To"][0]["Address"].lower()
                if address in found:
                    continue
                text = (await mp.get(f"/api/v1/message/{m['ID']}")).json()["Text"]
                token = re.search(r"/r/([A-Za-z0-9_-]+)", text)
                if token:
                    found[address] = token.group(1)
            if len(found) < want:
                await asyncio.sleep(0.5)
    return found


async def run(args: argparse.Namespace) -> Report:
    report = Report()
    limits = httpx.Limits(max_connections=args.registrations + 100, max_keepalive_connections=50)
    async with (
        httpx.AsyncClient(base_url=args.base, timeout=60, limits=limits) as http,
        httpx.AsyncClient(base_url=args.base, timeout=30) as admin,
    ):
        r = await admin.post("/api/admin/login", json={"password": PASSWORD})
        assert r.status_code == 204, f"organizer login failed: {r.status_code}"
        title = f"Stress {uuid.uuid4().hex[:8]}"
        starts = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        event = (await admin.post("/api/admin/events", json={"title": title, "starts_at": starts, "capacity": args.capacity})).json()
        event_id = event["id"]

        # ---------------- phase 1: registration storm
        unique = [f"s{i}-{uuid.uuid4().hex[:6]}@example.com" for i in range(args.registrations)]
        dup_emails = [f"dup{i}-{uuid.uuid4().hex[:6]}@example.com" for i in range(args.duplicates)]
        variants = lambda e: [e, e.upper(), f"  {e} ", e.capitalize(), f"{e}\t"]  # noqa: E731
        bodies = unique + [v for e in dup_emails for v in variants(e)[: args.dup_copies]]
        latencies: list[float] = []
        start = time.perf_counter()
        responses = await asyncio.gather(
            *[timed(http.post(f"/api/events/{event_id}/registrations", json={"email": b}), latencies) for b in bodies],
            return_exceptions=True,
        )
        elapsed = time.perf_counter() - start
        errors = [x for x in responses if isinstance(x, BaseException) or x.status_code >= 300]
        ok_responses = [x for x in responses if isinstance(x, httpx.Response) and x.status_code < 300]
        created = sum(1 for x in ok_responses if x.json()["created"])
        pids = {x.headers.get("x-backend-pid") for x in ok_responses} - {None}
        people = len(unique) + len(dup_emails)
        report.numbers.update(
            requests=len(bodies), seconds=round(elapsed, 2), rps=round(len(bodies) / elapsed, 1),
            p50_ms=round(pct(latencies, 0.5)), p95_ms=round(pct(latencies, 0.95)), max_ms=round(max(latencies) * 1000),
            backend_workers_seen=len(pids),
        )  # fmt: skip
        report.check("storm: every request answered 2xx", not errors, f"{len(errors)} errors {errors[:2]}")
        report.check("storm: one registration per person", created == people, f"{created} created for {people} distinct people")

        stats, rows = await admin_state(admin, event_id)
        common_invariants(report, "storm", args.capacity, stats, rows)
        expected_holders = min(args.capacity, people)
        report.check(
            "storm: all seats filled, rest waitlisted",
            (stats["registered"], stats["waitlisted"]) == (expected_holders, people - expected_holders),
            f"{stats['registered']} confirmed + {stats['waitlisted']} waitlisted for {people} people",
        )

        # ---------------- phase 2: cancels and registrations at the same moment
        holders = [r["email"].lower() for r in rows if r["status"] == "confirmed"]
        queue_before = [r["email"].lower() for r in sorted((r for r in rows if r["status"] == "waitlisted"), key=lambda r: r["waitlist_position"])]
        tokens = await manage_tokens(args.mailpit, title, want=len(holders))
        leaving = [e for e in holders if e in tokens][: args.cancels]
        report.check("mixed: manage links found in Mailpit", len(leaving) == min(args.cancels, len(holders)), f"{len(leaving)} cancel links")
        newcomers = [f"n{i}-{uuid.uuid4().hex[:6]}@example.com" for i in range(args.newcomers)]
        ops = [http.post(f"/api/registrations/{tokens[e]}/cancel") for e in leaving] + [
            http.post(f"/api/events/{event_id}/registrations", json={"email": n}) for n in newcomers
        ]
        mixed = await asyncio.gather(*[timed(op, latencies) for op in ops], return_exceptions=True)
        mixed_errors = [x for x in mixed if isinstance(x, BaseException) or x.status_code >= 300]
        report.check("mixed: every request answered 2xx", not mixed_errors, f"{len(mixed_errors)} errors")

        stats2, rows2 = await admin_state(admin, event_id)
        common_invariants(report, "mixed", args.capacity, stats2, rows2)
        status_of = {r["email"].lower(): r["status"] for r in rows2 if r["status"] != "cancelled"}
        promoted_expected = queue_before[: len(leaving)]
        report.check(
            "mixed: freed seats went to the oldest waitlisters (FIFO)",
            all(status_of.get(e) == "confirmed" for e in promoted_expected),
            f"{sum(status_of.get(e) == 'confirmed' for e in promoted_expected)}/{len(promoted_expected)} promoted in order",
        )
        report.check(
            "mixed: no newcomer jumped the queue",
            all(status_of.get(n) == "waitlisted" for n in newcomers) if queue_before else True,
            f"{sum(status_of.get(n) == 'confirmed' for n in newcomers)} newcomers got a seat",
        )
        report.numbers["event_id"] = event_id
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://frontend", help="frontend/nginx URL (or backend URL)")
    parser.add_argument("--mailpit", default="http://mailpit:8025")
    parser.add_argument("--capacity", type=int, default=50)
    parser.add_argument("--registrations", type=int, default=200, help="distinct emails in the storm")
    parser.add_argument("--duplicates", type=int, default=10, help="emails sent several times")
    parser.add_argument("--dup-copies", type=int, default=5, help="copies per duplicated email")
    parser.add_argument("--cancels", type=int, default=20)
    parser.add_argument("--newcomers", type=int, default=30)
    parser.add_argument("--report", help="write a JSON report here")
    args = parser.parse_args()

    report = asyncio.run(run(args))
    width = max(len(c.name) for c in report.checks)
    print(f"\nStress against {args.base}  ({args.registrations} + {args.duplicates}x{args.dup_copies} "
          f"concurrent registrations, {args.capacity} seats, then {args.cancels} cancels + {args.newcomers} registrations)")
    print("  " + "  ".join(f"{k}={v}" for k, v in report.numbers.items()))
    print(f"\n  {'invariant'.ljust(width)}  result  detail")
    for c in report.checks:
        print(f"  {c.name.ljust(width)}  {'PASS' if c.ok else 'FAIL':6}  {c.detail}")
    print(f"\nSTRESS {'PASS' if report.ok else 'FAIL'}: {sum(c.ok for c in report.checks)}/{len(report.checks)} invariants hold")
    if args.report:
        with open(args.report, "w") as f:
            json.dump({"ok": report.ok, "numbers": report.numbers, "checks": [c.__dict__ for c in report.checks]}, f, indent=2)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
