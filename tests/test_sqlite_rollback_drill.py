from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from start import sqlite_rollback_drill as drill


class SQLiteRollbackDrillTests(unittest.TestCase):
    def test_run_rollback_drill_passes_and_records_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "state" / "runtime_state.db")
            report = drill.run_rollback_drill(
                window_seconds=120,
                sqlite_path=db_path,
                target_os="windows",
                simulate_restart=True,
            )

        self.assertTrue(report["passed"])
        self.assertEqual(report["story"], "11.2")
        self.assertEqual(report["target_os"], "windows")
        self.assertGreaterEqual(report["elapsed_seconds"], 0.0)
        self.assertTrue(report["acceptance"]["steps_passed"])
        self.assertTrue(report["acceptance"]["within_15_minutes"])
        self.assertEqual(report["transition_summary"]["backend_after_rollback"], "memory")

    def test_render_markdown_contains_required_sections(self):
        report = {
            "story": "11.2",
            "generated_at": "2026-05-10T00:00:00+00:00",
            "target_os": "linux",
            "sqlite_path": "data/runtime_state.db",
            "elapsed_seconds": 12.5,
            "elapsed_minutes": 0.2083,
            "steps": [
                {
                    "name": "sqlite_precheck",
                    "passed": True,
                    "elapsed_seconds": 0.5,
                    "details": "ok",
                },
                {
                    "name": "rollback_transition",
                    "passed": True,
                    "elapsed_seconds": 0.8,
                    "details": "ok",
                },
            ],
            "transition_summary": {
                "backend_after_rollback": "memory",
                "post_transition_first_seen": False,
                "memory_probe_first": False,
                "memory_probe_second": True,
            },
            "acceptance": {
                "steps_passed": True,
                "within_15_minutes": True,
                "duration_limit_minutes": 15.0,
            },
            "passed": True,
        }

        markdown = drill._render_markdown(report)
        self.assertIn("# SQLite Rollback Drill Evidence", markdown)
        self.assertIn("## Steps Executed", markdown)
        self.assertIn("## Timing Acceptance", markdown)
        self.assertIn("## Final Determination", markdown)
        self.assertIn("## Sign-off", markdown)
        self.assertIn("**PASS**", markdown)

    def test_main_writes_json_and_dated_evidence_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            sqlite_path = Path(tmp) / "db" / "runtime_state.db"
            json_output = artifact_dir / "sqlite-rollback-drill-report.json"

            with patch.object(drill, "ARTIFACT_DIR", artifact_dir):
                exit_code = drill.main(
                    [
                        "--window-seconds",
                        "120",
                        "--sqlite-path",
                        str(sqlite_path),
                        "--target-os",
                        "windows",
                        "--simulate-restart",
                        "--json-output",
                        str(json_output),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(json_output.exists())
            evidence_files = list(artifact_dir.glob("sqlite-rollback-drill-*.md"))
            self.assertEqual(len(evidence_files), 2)
            self.assertTrue((artifact_dir / "sqlite-rollback-drill-latest.md").exists())
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["story"], "11.2")
            self.assertTrue(report["passed"])

    def test_transition_fails_when_backend_remains_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "state" / "runtime_state.db")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            precheck_step, precheck_meta = drill._step_precheck_sqlite(
                sqlite_path=db_path,
                window_seconds=120,
            )
            self.assertTrue(precheck_step.passed)

            sqlite_store = drill.SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace=drill.ROLLBACK_NAMESPACE,
                window_seconds=120,
            )
            try:
                with patch("start.sqlite_rollback_drill.create_expiring_store", return_value=sqlite_store):
                    transition_step, transition_meta = drill._step_rollback_transition(
                        sqlite_path=db_path,
                        window_seconds=120,
                        transition_key=precheck_meta["transition_key"],
                        simulate_restart=False,
                    )
            finally:
                sqlite_store.close()

            self.assertFalse(transition_step.passed)
            self.assertEqual(transition_meta["backend"], "SQLiteExpiringKeyStore")
            self.assertTrue(transition_meta["post_transition_first_seen"])


if __name__ == "__main__":
    unittest.main()