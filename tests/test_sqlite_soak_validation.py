from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from start import sqlite_soak_validation as soak


class SQLiteSoakValidationTests(unittest.TestCase):
    def test_run_soak_collects_metrics_and_restart_continuity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "state" / "runtime_state.db")
            report = soak.run_soak(
                duration_seconds=3,
                operations_per_second=5,
                restart_at_seconds=1,
                window_seconds=120,
                sqlite_path=db_path,
                target_os="windows",
            )

        self.assertTrue(report["passed"])
        self.assertTrue(report["restart_continuity"]["restart_performed"])
        self.assertTrue(report["restart_continuity"]["key_seen_after_restart"])
        self.assertEqual(report["target_os"], "windows")
        self.assertEqual(report["pass_criteria"]["sev_incidents"], [])
        self.assertGreater(report["results"]["total_operations"], 0)

    def test_render_markdown_contains_required_sections(self):
        report = {
            "story": "11.1",
            "generated_at": "2026-05-10T00:00:00+00:00",
            "target_os": "linux",
            "duration_seconds": 60,
            "sqlite_path": "data/runtime_state.db",
            "setup_checks": [
                {
                    "name": "sqlite_enablement",
                    "passed": True,
                    "details": "ok",
                }
            ],
            "results": {
                "total_operations": 1200,
                "successful_operations": 1200,
                "failed_operations": 0,
                "error_rate_pct": 0.0,
                "latency_p50_ms": 0.5,
                "latency_p95_ms": 1.1,
                "latency_p99_ms": 1.9,
                "latency_mean_ms": 0.7,
            },
            "memory_trend": [
                {"current_mb": 1.0, "peak_mb": 1.2},
                {"current_mb": 1.1, "peak_mb": 1.3},
            ],
            "restart_continuity": {
                "restart_performed": True,
                "key_seen_after_restart": True,
            },
            "pass_criteria": {
                "zero_sev1_sev2_incidents": True,
                "sev_incidents": [],
            },
            "passed": True,
        }

        markdown = soak._render_markdown(report)
        self.assertIn("# SQLite Soak Evidence", markdown)
        self.assertIn("## Setup Checks", markdown)
        self.assertIn("## Soak Metrics", markdown)
        self.assertIn("## Restart Continuity", markdown)
        self.assertIn("## Sev-1/Sev-2 Incident Gate", markdown)
        self.assertIn("**PASS**", markdown)

    def test_main_writes_json_and_dated_evidence_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            sqlite_path = Path(tmp) / "db" / "runtime_state.db"
            json_output = artifact_dir / "sqlite-soak-report.json"

            with patch.object(soak, "ARTIFACT_DIR", artifact_dir):
                exit_code = soak.main(
                    [
                        "--duration-seconds",
                        "2",
                        "--operations-per-second",
                        "3",
                        "--restart-at-seconds",
                        "1",
                        "--window-seconds",
                        "120",
                        "--sqlite-path",
                        str(sqlite_path),
                        "--target-os",
                        "windows",
                        "--json-output",
                        str(json_output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(json_output.exists())
            evidence_files = list(artifact_dir.glob("sqlite-soak-evidence-*.md"))
            self.assertEqual(len(evidence_files), 2)
            self.assertTrue((artifact_dir / "sqlite-soak-evidence-latest.md").exists())
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["story"], "11.1")
            self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()