from __future__ import annotations

# Add project root to Python path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import tempfile
import unittest
import unittest.mock

import yaml

from validate_contract_test_categories import validate_contract_test_categories
from validate_launch_gate_artifact_completeness import (
    validate_launch_gate_artifact_completeness,
)
from validate_story_closure_evidence import validate_story_closure_evidence


class ContractCategoryValidatorTests(unittest.TestCase):
    def test_passes_when_adapter_and_analytics_contract_files_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            (tests_dir / "test_channel_delivery_contract.py").write_text("# adapter\n", encoding="utf-8")
            (tests_dir / "test_conversation_analytics_event_foundation.py").write_text(
                "# analytics\n",
                encoding="utf-8",
            )

            issues = validate_contract_test_categories(tests_dir)

        self.assertEqual(issues, [])

    def test_fails_when_required_category_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            (tests_dir / "test_channel_delivery_contract.py").write_text("# adapter\n", encoding="utf-8")

            issues = validate_contract_test_categories(tests_dir)

        self.assertTrue(any("analytics" in issue for issue in issues))

    def test_fails_when_adapter_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            (tests_dir / "test_conversation_analytics_event_foundation.py").write_text("# analytics\n", encoding="utf-8")

            issues = validate_contract_test_categories(tests_dir)

        self.assertTrue(any("adapter" in issue for issue in issues))


class StoryClosureValidatorTests(unittest.TestCase):
    def test_passes_for_legacy_and_modern_done_story_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status.yaml").write_text(
                yaml.safe_dump(
                    {
                        "development_status": {
                            "1-1-legacy": "done",
                            "9-1-modern": "done",
                            "epic-1": "done",
                            "epic-1-retrospective": "done",
                        }
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "1-1-legacy.md").write_text(
                "## Completion State\n\n## Dev Agent Record\n",
                encoding="utf-8",
            )
            (impl_dir / "9-1-modern.md").write_text(
                "## Dev Agent Record\n\n### Completion Notes List\n\n### File List\n\n### Change Log\n",
                encoding="utf-8",
            )

            issues = validate_story_closure_evidence(impl_dir)

        self.assertEqual(issues, [])

    def test_fails_when_done_story_has_no_evidence_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status-next-cycle.yaml").write_text(
                yaml.safe_dump(
                    {"development_status": {"next-cycle-9-1-missing": "done"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "next-cycle-9-1-missing.md").write_text("# Story\n", encoding="utf-8")

            issues = validate_story_closure_evidence(impl_dir)

        self.assertTrue(any("missing closure evidence" in issue for issue in issues))

    def test_passes_for_legacy_story_with_dev_agent_completion_and_file_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status.yaml").write_text(
                yaml.safe_dump(
                    {"development_status": {"1-2-legacy": "done"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "1-2-legacy.md").write_text(
                "## Dev Agent Record\n\n### Debug Log\n\n### Completion Notes\n\n## File List\n",
                encoding="utf-8",
            )

            issues = validate_story_closure_evidence(impl_dir)

        self.assertEqual(issues, [])

    def test_next_cycle_done_story_requires_modern_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status-next-cycle.yaml").write_text(
                yaml.safe_dump(
                    {"development_status": {"next-cycle-9-1-risk": "done"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "next-cycle-9-1-risk.md").write_text(
                "## Dev Agent Record\n\n### Completion Notes\n\n## File List\n",
                encoding="utf-8",
            )

            issues = validate_story_closure_evidence(impl_dir)

        self.assertTrue(any("next-cycle stories require modern closure sections" in issue for issue in issues))

    def test_preserves_legacy_compatibility_when_both_sprint_files_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status-next-cycle.yaml").write_text(
                yaml.safe_dump(
                    {"development_status": {"next-cycle-9-1-modern": "done"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "sprint-status.yaml").write_text(
                yaml.safe_dump(
                    {"development_status": {"1-3-legacy-missing": "done"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "next-cycle-9-1-modern.md").write_text(
                "## Dev Agent Record\n\n### Completion Notes List\n\n### File List\n\n### Change Log\n",
                encoding="utf-8",
            )
            (impl_dir / "1-3-legacy-missing.md").write_text("# Story\n", encoding="utf-8")

            issues = validate_story_closure_evidence(impl_dir)

        self.assertEqual(issues, [])

    def test_fails_gracefully_when_sprint_status_yaml_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status.yaml").write_text(
                "development_status: [broken\n",
                encoding="utf-8",
            )

            issues = validate_story_closure_evidence(impl_dir)

        self.assertTrue(any("YAML parsing error in sprint-status.yaml" in issue for issue in issues))

    def test_fails_for_malformed_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status.yaml").write_text("invalid: [unclosed", encoding="utf-8")

            issues = validate_story_closure_evidence(impl_dir)

        self.assertTrue(any("YAML parsing error in sprint-status.yaml" in issue for issue in issues))

    def test_partial_modern_sections_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            impl_dir = Path(tmp)
            (impl_dir / "sprint-status-next-cycle.yaml").write_text(
                yaml.safe_dump(
                    {"development_status": {"next-cycle-9-1-risk": "done"}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (impl_dir / "next-cycle-9-1-risk.md").write_text(
                "## Dev Agent Record\n\n### Completion Notes\n",
                encoding="utf-8",
            )

            issues = validate_story_closure_evidence(impl_dir)

        self.assertTrue(any("missing closure evidence" in issue for issue in issues))


class LaunchGateCompletenessValidatorTests(unittest.TestCase):
    def test_passes_when_artifacts_have_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "_bmad-output" / "test-artifacts"
            docs_dir = root / "docs"
            artifacts.mkdir(parents=True)
            docs_dir.mkdir(parents=True)

            (docs_dir / "operations_runbook.md").write_text("Rollback playbook\n", encoding="utf-8")

            launch_doc = {
                "version": "1.0",
                "generated": "2026-05-08",
                "gates": [
                    {
                        "id": "G-1",
                        "label": "Security all pass",
                        "domain": "security",
                        "blocking": True,
                        "source": "test_results",
                        "key": "security_tests_all_pass",
                    },
                    {
                        "id": "G-2",
                        "label": "Staging latency",
                        "domain": "performance",
                        "blocking": True,
                        "source": "staging_report",
                        "key": "latency_p50_ok",
                    },
                    {
                        "id": "G-3",
                        "label": "Runbook exists",
                        "domain": "operations",
                        "blocking": True,
                        "source": "file_exists",
                        "key": "docs/operations_runbook.md",
                    },
                    {
                        "id": "G-4",
                        "label": "Runbook rollback line",
                        "domain": "operations",
                        "blocking": True,
                        "source": "file_contains",
                        "key": "docs/operations_runbook.md::rollback playbook",
                    },
                    {
                        "id": "G-5",
                        "label": "Manual attestation",
                        "domain": "operations",
                        "blocking": False,
                        "source": "manual",
                        "key": "manual_attestation_present",
                    },
                ],
            }
            (artifacts / "launch-gates.yaml").write_text(
                yaml.safe_dump(launch_doc, sort_keys=False),
                encoding="utf-8",
            )
            (artifacts / "test-results-summary.json").write_text(
                json.dumps({"security_tests_all_pass": True}),
                encoding="utf-8",
            )
            (artifacts / "staging-validation-report.json").write_text(
                json.dumps({"latency_p50_ok": True}),
                encoding="utf-8",
            )

            issues = validate_launch_gate_artifact_completeness(root)

        self.assertEqual(issues, [])

    def test_fails_when_required_root_field_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "_bmad-output" / "test-artifacts"
            artifacts.mkdir(parents=True)

            (artifacts / "launch-gates.yaml").write_text(
                yaml.safe_dump({"gates": []}, sort_keys=False),
                encoding="utf-8",
            )

            issues = validate_launch_gate_artifact_completeness(root)

        self.assertTrue(any("missing required root field" in issue for issue in issues))

    def test_fails_when_manual_source_key_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts_dir = Path(tmp) / "_bmad-output" / "test-artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            launch_gates_path = artifacts_dir / "launch-gates.yaml"
            launch_gates_path.write_text(
                yaml.safe_dump(
                    {
                        "version": "1.0",
                        "generated": "2026-05-09",
                        "gates": [
                            {"id": "gate-1", "label": "Manual Gate", "domain": "test", "blocking": True, "source": "manual", "key": ""}
                        ]
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            issues = validate_launch_gate_artifact_completeness(artifacts_dir.parent.parent)

        self.assertTrue(any("manual" in issue and "empty key" in issue for issue in issues))

    def test_fails_when_manual_source_key_is_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "_bmad-output" / "test-artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / "launch-gates.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": "1.0",
                        "generated": "2026-05-09",
                        "gates": [
                            {
                                "id": "gate-1",
                                "label": "Manual Gate",
                                "domain": "test",
                                "blocking": True,
                                "source": "manual",
                                "key": None,
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            issues = validate_launch_gate_artifact_completeness(root)

        self.assertTrue(any("manual" in issue and "empty key" in issue for issue in issues))

    def test_fails_when_file_contains_needle_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "_bmad-output" / "test-artifacts"
            docs_dir = root / "docs"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "operations_runbook.md").write_text("Rollback playbook\n", encoding="utf-8")

            (artifacts_dir / "launch-gates.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": "1.0",
                        "generated": "2026-05-09",
                        "gates": [
                            {
                                "id": "gate-1",
                                "label": "Runbook contains marker",
                                "domain": "test",
                                "blocking": True,
                                "source": "file_contains",
                                "key": "docs/operations_runbook.md::",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            issues = validate_launch_gate_artifact_completeness(root)

        self.assertTrue(any("non-empty substring" in issue for issue in issues))

    def test_fails_gracefully_when_test_results_json_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "_bmad-output" / "test-artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            (artifacts_dir / "launch-gates.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": "1.0",
                        "generated": "2026-05-09",
                        "gates": [
                            {
                                "id": "gate-1",
                                "label": "Security all pass",
                                "domain": "security",
                                "blocking": True,
                                "source": "test_results",
                                "key": "security_tests_all_pass",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "test-results-summary.json").write_text("{not-json", encoding="utf-8")

            issues = validate_launch_gate_artifact_completeness(root)

        self.assertTrue(any("Invalid test-results summary JSON" in issue for issue in issues))

    def test_fails_gracefully_when_staging_report_json_is_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "_bmad-output" / "test-artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            (artifacts_dir / "launch-gates.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": "1.0",
                        "generated": "2026-05-09",
                        "gates": [
                            {
                                "id": "gate-1",
                                "label": "Latency p50",
                                "domain": "performance",
                                "blocking": True,
                                "source": "staging_report",
                                "key": "latency_p50_ok",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "staging-validation-report.json").write_text("{not-json", encoding="utf-8")

            issues = validate_launch_gate_artifact_completeness(root)

        self.assertTrue(any("Invalid staging validation report JSON" in issue for issue in issues))


if __name__ == "__main__":
    def test_fails_gracefully_when_launch_gates_yaml_raises_oserror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "_bmad-output" / "test-artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / "launch-gates.yaml").write_text("version: '1.0'\n", encoding="utf-8")

            with unittest.mock.patch(
                "validate_launch_gate_artifact_completeness.open",
                side_effect=OSError("permission denied"),
            ):
                issues = validate_launch_gate_artifact_completeness(root)

            self.assertTrue(any("Unable to read" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()

class _OSErrorLaunchGateTest(unittest.TestCase):
    def test_fails_gracefully_when_launch_gates_yaml_raises_oserror(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "_bmad-output" / "test-artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / "launch-gates.yaml").write_text("version: '1.0'\n", encoding="utf-8")

            with unittest.mock.patch(
                "validate_launch_gate_artifact_completeness.open",
                side_effect=OSError("permission denied"),
            ):
                issues = validate_launch_gate_artifact_completeness(root)

            self.assertTrue(any("Unable to read" in issue for issue in issues))
