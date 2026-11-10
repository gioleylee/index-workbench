"""Compare SQLite index designs using an identical workload and result checks."""

import argparse
import hashlib
import json
import random
import sqlite3
from contextlib import closing
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter_ns


LAYOUTS = {
    "baseline": "",
    "tenant": "CREATE INDEX event_tenant ON events(tenant)",
    "composite": "CREATE INDEX event_tenant_time ON events(tenant, ts DESC)",
    "covering": "CREATE INDEX event_covering ON events(tenant, ts DESC, kind, amount)",
    "covering_plus_time": """
        CREATE INDEX event_covering ON events(tenant, ts DESC, kind, amount);
        CREATE INDEX event_time ON events(ts DESC);
    """,
}
QUERY_TENANT = """
SELECT ts, kind, amount FROM events
WHERE tenant = ? AND ts BETWEEN ? AND ?
ORDER BY ts DESC LIMIT 50
"""
QUERY_GLOBAL = """
SELECT ts, kind, amount FROM events
WHERE ts BETWEEN ? AND ?
ORDER BY ts DESC LIMIT 50
"""


def events(count, seed):
    rng = random.Random(seed)
    return [
        (0 if rng.random() < 0.2 else rng.randint(1, 999), ts,
         rng.choice(("open", "view", "close")), rng.randint(1, 1000))
        for ts in range(count)
    ]


def workloads(count, lookups, seed):
    rng = random.Random(seed + 1)
    hot, cold, global_ = [], [], []
    width = max(1, count // 10)
    for _ in range(lookups):
        end = rng.randint(width - 1, count - 1)
        interval = (end - width + 1, end)
        hot.append((0, *interval))
        cold.append((rng.randint(1, 999), *interval))
        global_.append(interval)
    return {
        "hot_tenant": (QUERY_TENANT, hot),
        "cold_tenant": (QUERY_TENANT, cold),
        "all_tenants": (QUERY_GLOBAL, global_),
    }


def time_query(db, sql, params):
    query_plan = [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql, params[0])]
    for values in params:
        db.execute(sql, values).fetchall()
    timings, digest = [], hashlib.sha256()
    for values in params:
        started = perf_counter_ns()
        rows = db.execute(sql, values).fetchall()
        timings.append((perf_counter_ns() - started) / 1_000)
        digest.update(json.dumps(rows, separators=(",", ":")).encode())
        digest.update(b"\n")
    return {
        "p50_us": round(median(timings), 2),
        "p95_us": round(quantiles(timings, n=100, method="inclusive")[94], 2),
        "plan": query_plan,
        "result_sha256": digest.hexdigest(),
    }


def evaluate(path, layout, data, queries):
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA cache_size = -32768")
        db.execute("CREATE TABLE events(tenant INTEGER, ts INTEGER, kind TEXT, amount INTEGER)")
        db.executescript(layout)
        started = perf_counter_ns()
        with db:
            db.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", data)
        ingest_ms = (perf_counter_ns() - started) / 1_000_000
        db.execute("ANALYZE")
        db.commit()
        metrics = {name: time_query(db, sql, params) for name, (sql, params) in queries.items()}
        version = sqlite3.sqlite_version
    return {"sqlite": version, "file_bytes": path.stat().st_size, "ingest_ms": round(ingest_ms, 2),
            "queries": metrics}


def run(count, lookups, seed):
    data = events(count, seed)
    queries = workloads(count, lookups, seed)
    report = {"rows": count, "lookups_per_workload": lookups, "seed": seed, "layouts": {}}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        expected = {}
        for name, layout in LAYOUTS.items():
            result = evaluate(root / (name + ".sqlite"), layout, data, queries)
            for query, metrics in result["queries"].items():
                actual = metrics["result_sha256"]
                if expected.setdefault(query, actual) != actual:
                    raise RuntimeError(f"query results changed for {name} / {query}")
            report["layouts"][name] = result
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=250_000)
    parser.add_argument("--lookups", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    args = parser.parse_args()
    if args.rows < 1 or args.lookups < 2:
        parser.error("expected a positive row count and at least two lookups")
    result = run(args.rows, args.lookups, args.seed)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, item in result["layouts"].items():
        print(name, item["file_bytes"], {query: sample["p50_us"] for query, sample in item["queries"].items()})
