# Index Workbench

A reproducible SQLite experiment that measures how index design changes read latency, bulk insert time, and database size. Each layout sees the same 250,000 events and query parameters. The benchmark checks that ordered query results have identical hashes across layouts.

```sh
python -m unittest -v
python benchmark.py
```

Use Python 3.11+. The workload generates event times, tenants, event kinds, and amounts. One hot tenant owns roughly 20% of the events. Each query returns at most 50 newest matching events within a time range.

## Results

The table shows medians in microseconds from one local Windows run with SQLite 3.49.1. Database size and insert time include the stated indexes. See [benchmark-results.json](benchmark-results.json) for 95th percentiles, query plans, and output digests.

| Layout | Hot tenant | Cold tenant | All tenants | Database size | Bulk insert |
| --- | ---: | ---: | ---: | ---: | ---: |
| Table only | 12,606 µs | 10,824 µs | 16,974 µs | 5.4 MB | 205 ms |
| Tenant | 12,285 µs | 412 µs | 17,085 µs | 8.3 MB | 426 ms |
| Tenant + time | 310 µs | 291 µs | 3,662 µs | 9.9 MB | 529 ms |
| Covering tenant + time | 293 µs | 263 µs | 3,453 µs | 12.6 MB | 502 ms |
| Covering plus separate time index | 290 µs | 312 µs | 322 µs | 18.5 MB | 733 ms |

The tenant-only index helped the cold lookup and left the hot lookup scanning and sorting many matches. The composite index let the hot lookup constrain both columns and read the result in order. The covering index also supplied the projected columns. The all-tenant lookup still needed a temporary sort until the layout added an index beginning with time.

Each layout uses a fresh database, the same cache size, and `ANALYZE`. The benchmark warms each query set before timing and includes Python row materialization. It excludes index definition and `ANALYZE` from the insert measurement. Layouts run in a fixed order, and the latency and ingest numbers reflect one local run. The benchmark does not measure concurrent traffic, cold cache performance, or incremental schema migration.
