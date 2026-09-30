# Revenue dashboard fixes

1. Revenue caches are isolated by authenticated tenant and property. Old shared keys are ignored.
2. Revenue reads PostgreSQL through a reusable async SQLAlchemy pool. Database failures return HTTP 503 rather than fabricated successful totals.
3. The property selector reads the tenant's properties. Ownership is checked before every revenue cache lookup; foreign and nonexistent property IDs return the same 404.
4. Optional month/year filters use property-local check-in dates, with inclusive start and exclusive next-month boundaries converted independently to UTC. This accounts for DST. All-time reporting remains available.
5. PostgreSQL sums NUMERIC amounts by currency. Python Decimal rounds each final currency sum once, using ROUND_HALF_UP and Babel's standard currency decimal places. The browser formats decimal strings without numeric conversion. No FX conversion or mixed-currency grand total is invented.

## Monetary API contract

`GET /api/v1/dashboard/summary?property_id=prop-001&month=3&year=2024`

Amounts are now decimal strings, replacing JSON numbers. `revenue_by_currency` contains `currency`, `total_revenue` (rounded for display), `exact_total_revenue` (unrounded database sum), and `reservations_count` for each currency.

Top-level `total_revenue` and `currency` are populated only when exactly one currency is present. Both are null for empty or mixed-currency results. Top-level `reservations_count` always counts the selected reservations. An empty period returns an empty currency list; the UI shows an explicit empty state. Missing or unrecognized reservation currencies fail with 503 rather than being mislabeled USD.

The cache namespace changes for this contract so prior combined/float-era totals are not reused. Deploy the backend and frontend changes together and refresh open dashboard tabs.

## Verification

```sh
docker compose exec -T -e RUN_DB_TESTS=1 backend python -B -m unittest discover -s tests -v
npm --prefix frontend run test:dashboard
```

PostgreSQL integration tests use connection-local temporary tables and roll back; they do not alter seeded reservations. The tests cover tenant ownership, cache isolation, database failures, calendar boundaries, DST in Paris and New York, cache periods, exact aggregation, currency-specific rounding, refunds, large string totals, and frontend selection/error/race behavior.

For a walkthrough, sign in with the supplied accounts:

- Sunset / Beach House Alpha: March 2024 shows USD 2,250.00 and four bookings. The check-in at February 29, 23:30 UTC is March 1 in Paris, so February shows no revenue.
- Ocean / Mountain Lodge Beta: no bookings and no revenue; the selector contains Ocean's own property names.
- Foreign property requests return 404, even if a revenue cache entry exists.
- Mixed currencies and sub-cent fixtures are demonstrated by the PostgreSQL monetary test: three USD amounts (333.333, 333.333, 333.334) sum to USD 1,000.00; EUR 2.675 is separately displayed as EUR 2.68 with the exact total retained.

This documents the code and test evidence; the required Loom walkthrough has not been recorded.

## End-to-end requirement audit — 2026-09-30

- All four development services (frontend, backend, PostgreSQL, Redis) are running. Both application URLs respond.
- Fresh automated runs: 31 backend tests, including PostgreSQL integration tests, and 11 frontend tests passed.
- 48 live summary requests across both accounts, all six properties, all-time and February/March/April 2024 matched independent SQL and their tenant-specific Redis payloads. Both account request orders were exercised.
- Missing/invalid authentication and incorrect login credentials were rejected. Spoofed tenant query/header values did not change property ownership. Foreign and nonexistent properties returned 404; invalid/incomplete reporting periods returned 422.
- Native Chrome checks confirmed Sunset's own property names and March 2024 USD 2,250.00 / four bookings; after logout/login, Ocean showed only its three property names and Mountain Lodge Beta showed no revenue / zero bookings.
- In an isolated API process with an unreachable PostgreSQL URL, both property and summary endpoints returned 503. No revenue was cached. The running database was not stopped or changed.
- Monetary behavior with mixed currencies, sub-cent values, refunds, and large totals is covered by temporary PostgreSQL fixtures and frontend component tests. The seeded accounts themselves contain USD reservations, so they alone do not demonstrate mixed-currency behavior.

### Outstanding at audit time

1. Annual summaries are mentioned in ASSIGNMENT.md's system overview but are not implemented: only monthly and all-time reporting exist, and a year-only summary request returns 422. All-time is not an annual report.
2. The fifth fix (currency/precision), its tests, and these notes are not committed or pushed yet. Four meaningful fix commits are already pushed, satisfying the requested minimum of four.
3. No required 5–10 minute Loom recording/link has been produced as part of this task.

The existing frontend Dockerfile edits and generated Python bytecode remain outside the fix commits. This audit verifies the local development dashboard flow; it is not a production deployment or a security audit of unrelated application modules.
