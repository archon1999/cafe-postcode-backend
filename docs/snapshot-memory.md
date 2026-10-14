# POS snapshot memory

Large saved Tasnif package directories made two existing query patterns costly:
each order item joined its catalog item, and each menu product joined its category.
JSON decoding constructed separate Python copies for repeated rows before the
compact fiscal projection ran. Compact response JSON alone did not solve this.

POS order items now prefetch catalog items in one separate query. Items using
the same product share its model and raw JSON; the order graph needs eight
queries instead of seven, independently of the number of orders or items.
Menu reverse prefetch shares the already loaded parent category. Online group
members prefetch products and categories rather than joining their JSON for
every member. Snapshot serialization also reuses its restaurant/default station.

Fiscal projections are cached by source identity in the serializer context.
The cache keeps source references only for that serialization, returns fresh
output dictionaries, and does not survive requests or workers. Saved lookup
payloads, returned fields, marking/cash restrictions, and retention of orders
for unfinished shifts or fiscal receipts are preserved.

An opt-in disposable SQLite benchmark uses 301 products, 20 categories with
562-package directories, 330 orders and 3,521 items referencing 31 products.
It uses a fixed clock and compares complete rendered-response hashes:

| Snapshot | Before peak Python MiB | After peak Python MiB | Equal SHA-256 |
| --- | ---: | ---: | --- |
| Menu | 224.20 | 14.12 | Yes |
| Orders | 167.38 | 55.79 | Yes |

These are traced synthetic local measurements, not production RSS measurements.
Run with `RUN_SNAPSHOT_MEMORY_BENCHMARK=1` and set
`SNAPSHOT_MEMORY_BENCHMARK_OUTPUT` to a local JSON output path, then execute
`python manage.py test apps.local_agents.test_snapshot_memory_benchmark` against
a disposable local test database. The normal suite does not run this benchmark.

Production web defaults are 500 requests per worker plus 0–100 random jitter,
a 3 GiB container memory limit and a 1 GiB soft reservation. Operators can set
`GUNICORN_MAX_REQUESTS`, `GUNICORN_MAX_REQUESTS_JITTER`, `WEB_MEMORY_LIMIT` and
`WEB_MEMORY_RESERVATION`. Recycling drains in-flight work; it bounds long-lived
allocator retention and supplements the query fix. Size these limits against
the configured worker/thread count and measured workloads. After rollout,
verify the actual command, cgroup limit, readiness, worker RSS and snapshot
latency; a container-health result alone is not a memory acceptance test.
