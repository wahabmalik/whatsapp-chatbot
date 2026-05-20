# SQLite Soak Operations Checklist (POC -> 24h)

Date: 2026-05-10
Owner: Reliability / QA
Scope: Story 11.1 SQLite soak evidence gating

## 1) Pre-run controls (mandatory)

- [ ] Confirm Python env is active and project root is current working directory.
- [ ] Confirm disk path for SQLite exists and is writable: `data/runtime_state.db` parent directory.
- [ ] Reset soak namespace state before each POC run to avoid false setup-check failures.
- [ ] Option A (preferred): remove `data/runtime_state.db` before run if no production-like data is required.
- [ ] Option B: keep DB but verify `soak_enablement` namespace/key isolation is clean.
- [ ] Record run config: duration, ops/sec, restart-at, target OS, window-seconds.

## 2) 30-min POC command

`c:/Users/wahab/OneDrive/Documents/GitHub/python-whatsapp-bot/.venv/Scripts/python.exe sqlite_soak_validation.py --duration-seconds 1800 --operations-per-second 25 --restart-at-seconds 900 --window-seconds 300 --target-os windows`

## 3) Artifact checks (must all pass)

- [ ] `sqlite-soak-report.json` exists and is from current run timestamp.
- [ ] `sqlite-soak-evidence-YYYYMMDD.md` exists and `sqlite-soak-evidence-latest.md` updated.
- [ ] Setup checks: `sqlite_enablement=PASS`, `sqlite_failover_to_memory=PASS`.
- [ ] Runtime checks: failed operations = 0, error rate = 0.0%.
- [ ] Continuity checks: restart performed = yes, key_seen_after_restart = true.
- [ ] Sev gate: zero Sev-1/Sev-2 incidents = pass.
- [ ] Final determination: PASS.

## 4) 24h soak green-light criteria

- [ ] 30-min POC passes all checks in Section 3.
- [ ] No unexplained memory growth pattern in POC trend.
- [ ] Launch reliability gates remain blocking and mapped to evidence artifacts.
- [ ] Gate owner signs off go/no-go in release notes.

Decision policy:
- If any setup check fails, do not green-light 24h soak; open blocker and rerun after remediation.
- If all checks pass, green-light 24h soak with same command pattern using `--duration-seconds 86400` and midpoint restart.

## 5) Code review handoff package

- [ ] Include latest markdown evidence, JSON report, and this checklist.
- [ ] Attach root-cause note for any failed gate.
- [ ] Request review focus: setup check determinism, namespace isolation, and false-negative prevention.
