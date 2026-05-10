# Story 10.1: Analytics Reporting API

Status: ready-for-dev

## Story

As an operations lead,
I want an API that aggregates conversation analytics events into operational summaries (volume trends, escalation rates, delivery outcomes, latency percentiles),
so that I can monitor platform health without needing direct access to raw event files or a separate BI system.

## Acceptance Criteria

1. AC 10.1.1: `GET /api/analytics/summary` returns: message volume trend (daily, last 7 days), escalation trend (daily, last 7 days), delivery outcome breakdown (success/retry/failure counts), and latency summary (p50/p95/p99 from event data) — all sourced from the event foundation.
2. AC 10.1.2: Response format is stable and contract-tested; any breaking change fails the consumer contract test.
3. AC 10.1.3: Retention policy is applied: events older than the configured cap are excluded from query results and a pruning mechanism exists.
4. AC 10.1.4: Endpoint is protected by existing operator authentication (no public access).
5. AC 10.1.5: API responds within <= 500ms for <= 10,000 stored events.

## Tasks / Subtasks

- [ ] Implement analytics aggregation logic in `app/services/analytics_aggregator.py`. (AC: 10.1.1, 10.1.3, 10.1.5)
  - [ ] Load events from `conversation_analytics_events.jsonl`.
  - [ ] Filter by retention cap timestamp.
  - [ ] Aggregate daily volume (message count by day, last 7 days).
  - [ ] Aggregate daily escalation count (last 7 days).
  - [ ] Aggregate delivery outcome breakdown: success / retry / failure counts.
  - [ ] Compute latency percentiles (p50, p95, p99) from latency_ms field.
  - [ ] Add unit tests for aggregation logic with mock event data.
  - [ ] Performance assertion: <= 500ms response for <= 10,000 events.
- [ ] Implement retention policy in `app/services/analytics_aggregator.py`. (AC: 10.1.3)
  - [ ] Load configured retention cap from `app.config`.
  - [ ] Filter events older than cap before aggregation.
  - [ ] Add pruning function to remove events older than cap from the JSONL file.
  - [ ] Add tests for retention filtering and pruning.
- [ ] Implement `GET /api/analytics/summary` endpoint in `app/views.py` or new `app/views_analytics.py`. (AC: 10.1.1, 10.1.2, 10.1.4)
  - [ ] Wire aggregator into Flask route.
  - [ ] Require operator authentication via existing auth decorator.
  - [ ] Return JSON response with stable schema.
  - [ ] Add error handling for missing event file or corrupted events.
  - [ ] Log request with correlation_id and response time.
- [ ] Add contract test for response schema stability in `tests/test_analytics_contract.py`. (AC: 10.1.2)
  - [ ] Assert required top-level keys: `volume_trend`, `escalation_trend`, `delivery_breakdown`, `latency_summary`.
  - [ ] Assert trend arrays have expected structure (date, value).
  - [ ] Assert breakdown has sum equal to total deliveries.
  - [ ] Test breaking change detection (missing key fails test).
- [ ] Add integration tests for analytics API. (AC: 10.1.1, 10.1.4, 10.1.5)
  - [ ] Test with mock event data: >= 1,000 events, verify aggregation correctness.
  - [ ] Test retention cap filtering.
  - [ ] Test authentication gate (unauthenticated request rejected).
  - [ ] Test performance: assert response <= 500ms for 10,000 events.

## Dev Notes

### Analytics Aggregation Architecture

Analytics aggregation will:
1. Load events from the existing `conversation_analytics_events.jsonl` file (Story 8.3 foundation).
2. Filter by configured retention cap (`ANALYTICS_RETENTION_DAYS`, default 90).
3. Compute aggregations:
   - **Volume trend**: Daily message count (7 days, most recent first)
   - **Escalation trend**: Daily escalation count (7 days, most recent first)
   - **Delivery breakdown**: Total success, retry, failure counts
   - **Latency summary**: p50, p95, p99 percentiles from `latency_ms` field

### Response Schema

```json
{
  "volume_trend": [
    {"date": "2026-05-10", "count": 142},
    {"date": "2026-05-09", "count": 138},
    ...
  ],
  "escalation_trend": [
    {"date": "2026-05-10", "count": 3},
    {"date": "2026-05-09", "count": 2},
    ...
  ],
  "delivery_breakdown": {
    "success": 1205,
    "retry": 34,
    "failure": 5
  },
  "latency_summary": {
    "p50_ms": 245,
    "p95_ms": 890,
    "p99_ms": 2100
  }
}
```

### Retention Policy

- Events older than `ANALYTICS_RETENTION_DAYS` (default 90) are excluded from query results.
- Pruning function removes old events from the JSONL file as a background task or on-demand CLI command.
- Config variable: `ANALYTICS_RETENTION_DAYS` in `app/config.py`.

### Performance Constraints

- API response must be <= 500ms for <= 10,000 events.
- Strategy: Use in-memory numpy/scipy for percentile calculation; cache aggregation if events haven't changed.
- No database queries (stay with JSONL file for now per Epic 8.4 optional SQLite posture).

### Authentication and Authorization

- Use existing operator auth decorator (Story 5.1 CSRF hardening includes auth checks).
- No public access — 403 Forbidden for unauthenticated requests.
- Return operator's own analytics (tenant-isolated via existing correlation).

### Out of Scope

- Export formats (CSV/PDF download).
- Real-time streaming or WebSocket push.
- Per-user drill-down beyond wa_id (operational summary only).
- Data warehouse integration.

### Test Strategy

- Unit tests for aggregation logic with mock event data.
- Contract test for schema stability (breaking change detection).
- Integration test with full request/response cycle, retention filtering, auth gate.
- Performance assertion: mock 10,000 events, measure response time.

### References

- `app/services/analytics_aggregator.py` — To be created
- `app/views.py` or `app/views_analytics.py` — Endpoint implementation
- `tests/test_analytics_contract.py` — Contract and integration tests
- `app/config.py` — `ANALYTICS_RETENTION_DAYS` config
- `app/utils/observability.py` — Correlation ID and logging
- `app/repositories/` — Auth decorator (existing from Story 5.1)
- `_bmad-output/planning-artifacts/epics-next-cycle.md` — AC source

## Dev Agent Record

### Agent Model Used

Claude Haiku 4.5

### Debug Log References

TBD (implementation in progress)

### Completion Notes List

TBD (implementation in progress)

### File List

- `app/services/analytics_aggregator.py` — To be created
- `app/views_analytics.py` or updated `app/views.py` — To be created/updated
- `tests/test_analytics_contract.py` — To be created
- `app/config.py` — To be updated with `ANALYTICS_RETENTION_DAYS`
- `_bmad-output/implementation-artifacts/next-cycle-10-1-analytics-reporting-api.md` — This file

### Change Log

| Date | Change |
| --- | --- |
| 2026-05-10 | Story 10.1 created from epics-next-cycle.md; depends-on Story 9.3 complete. |
