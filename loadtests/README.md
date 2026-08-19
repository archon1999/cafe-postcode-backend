# Load Testing

The default profile targets 500 concurrent POS API users, ramps at 25 users per second, and runs for 15 minutes.

The legacy Locust profile is restricted to an isolated stack with
`DEVICE_POS_PROOF_REQUIRED=0`. Use pre-issued, scoped test sessions:

```bash
export LOCUST_TOKEN_POOL='<restaurant uuid>:<test token>,<restaurant uuid>:<test token>'
```

`LOCUST_TOKEN=<test token>` is also supported for a single restaurant. The
`LOCUST_RESTAURANT_ID` + `LOCUST_PIN` shortcut is likewise isolated-stack only.
This profile intentionally refuses to model production device private keys and
must not be pointed at production; device-proof load is covered by the signed
transport/E2E harness.

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
