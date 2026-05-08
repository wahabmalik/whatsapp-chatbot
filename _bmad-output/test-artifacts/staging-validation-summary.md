# Staging Validation Summary

Generated: 2026-05-01T10:37:00.480130+00:00
Base URL: http://127.0.0.1:8000
Payload kind: status
Sample count: 1000

## Results

| Metric | Value | Gate Threshold | Pass? |
|--------|-------|----------------|-------|
| P50 Latency | 0.020s | <= 4.0s | ✅ |
| P95 Latency | 0.051s | <= 8.0s | ✅ |
| Success Rate | 100.00% | >= 99.0% | ✅ |
| Throughput | 35.06 msg/s | >= 10.0 msg/s | ✅ |
| Fallback Timing | 7.0114s | <= 10.0s | ✅ |
| Sample Count | 1000 | >= 1000 | ✅ |

## Notes

- Fallback probe passed
- Run duration: 28.522s
- Health pre-check: running
