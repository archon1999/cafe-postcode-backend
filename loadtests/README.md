# Load Testing

The default profile targets 500 concurrent POS API users, ramps at 25 users per second, and runs for 15 minutes.

Required environment:

```bash
export LOCUST_RESTAURANT_ID=<restaurant uuid>
export LOCUST_PIN=<active POS user pin>
```

Alternatively, set `LOCUST_RESTAURANT_CODE` instead of `LOCUST_RESTAURANT_ID`; the test will resolve the restaurant through `/api/v1/pos/auth/restaurant-code/`.

Run against a local Docker Compose stack:

```bash
poetry install --with loadtest
mkdir -p loadtests/reports
poetry run locust -f loadtests/locustfile.py --config loadtests/locust.conf --host http://127.0.0.1
```

Payments are disabled by default because they require an active cashier shift and fiscal integration readiness. Enable them with:

```bash
export LOCUST_ENABLE_PAYMENTS=1
```

Acceptance target: error rate below 1%, no sustained 5xx responses, and stable PostgreSQL/Redis metrics during the steady 15-minute window.
