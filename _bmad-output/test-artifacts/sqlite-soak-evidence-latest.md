# SQLite Soak Evidence

Generated: 2026-05-10T01:59:25.549427+00:00
Story: 11.1
Target OS: windows
Soak Duration: 1800 seconds
SQLite Path: C:\Users\wahab\OneDrive\Documents\GitHub\python-whatsapp-bot\data\runtime_state.db

## Setup Checks

| Check | Result | Details |
|---|---|---|
| sqlite_enablement | FAIL | Unexpected seen_recently behavior during setup |
| sqlite_failover_to_memory | PASS | SQLite init failure degraded to memory store as configured |

## Soak Metrics

| Metric | Value |
|---|---|
| Total operations | 45000 |
| Successful operations | 45000 |
| Failed operations | 0 |
| Error rate | 0.0% |
| Latency p50 | 0.9278 ms |
| Latency p95 | 38.4141 ms |
| Latency p99 | 49.1382 ms |
| Latency mean | 8.3002 ms |

## Memory Trend

| Snapshot | Current MB | Peak MB |
|---|---|---|
| Start | 0.0053 | 0.0056 |
| End | 1.8555 | 1.8672 |

## Restart Continuity

- Restart performed: yes
- Continuity assertion (key survives restart): pass

## Sev-1/Sev-2 Incident Gate

- Zero incidents required: fail
- Incident list: setup_check_failed:sqlite_enablement

## Final Determination

**FAIL**