"""
Launch Gate Parity Tests — Epic 4 Carry-Forward Action #2

Verifies that every key referenced in launch-gates.yaml has a matching entry
in the corresponding evidence file (test-results-summary.json or
staging-validation-report.json).

CI should fail if a gate key is added to launch-gates.yaml but the evidence
file has not been updated to produce that key.

Sources:
  "test_results"   → _bmad-output/test-artifacts/test-results-summary.json
  "staging_report" → _bmad-output/test-artifacts/staging-validation-report.json
  "file_exists"    → value is True when the referenced path exists on disk
  "file_contains"  → validates required text exists in referenced file
  "manual"         → no automated evidence; attestation checked in evaluator
"""
import json
import pathlib
import re
import unittest

try:
    import yaml  # pyyaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_GATES_FILE = _PROJECT_ROOT / "_bmad-output" / "test-artifacts" / "launch-gates.yaml"
_TEST_RESULTS_FILE = _PROJECT_ROOT / "_bmad-output" / "test-artifacts" / "test-results-summary.json"
_STAGING_REPORT_FILE = _PROJECT_ROOT / "_bmad-output" / "test-artifacts" / "staging-validation-report.json"


def _load_yaml(path: pathlib.Path) -> dict:
    """Load a YAML file, returning the parsed structure."""
    if not HAS_YAML:
        raise ImportError("pyyaml is required for launch gate parity tests. Run: pip install pyyaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_json(path: pathlib.Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _get_gates(source_filter: str) -> list:
    """Return all gate entries for the given source type."""
    doc = _load_yaml(_GATES_FILE)
    gates = doc.get("gates", [])
    return [g for g in gates if g.get("source") == source_filter]


class GatesFileExistsTests(unittest.TestCase):
    """Prerequisite: all artifact files required for gate checks exist."""

    def test_launch_gates_yaml_exists(self):
        """launch-gates.yaml must exist for parity checks to run."""
        self.assertTrue(
            _GATES_FILE.exists(),
            f"launch-gates.yaml not found at {_GATES_FILE}",
        )

    def test_test_results_summary_json_exists(self):
        """test-results-summary.json must exist (produced by test runner)."""
        self.assertTrue(
            _TEST_RESULTS_FILE.exists(),
            f"test-results-summary.json not found at {_TEST_RESULTS_FILE}",
        )

    def test_staging_validation_report_json_exists(self):
        """staging-validation-report.json must exist (produced by staging run)."""
        self.assertTrue(
            _STAGING_REPORT_FILE.exists(),
            f"staging-validation-report.json not found at {_STAGING_REPORT_FILE}",
        )


@unittest.skipUnless(_GATES_FILE.exists() and _TEST_RESULTS_FILE.exists(), "Artifact files missing")
class TestResultsGateParityTests(unittest.TestCase):
    """Every gate with source=test_results has its key in test-results-summary.json."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = _load_json(_TEST_RESULTS_FILE)
        cls.gates = _get_gates("test_results")

    def test_at_least_one_test_results_gate_defined(self):
        """Sanity check: launch-gates.yaml should have test_results gates."""
        self.assertGreater(
            len(self.gates),
            0,
            "No test_results gates found in launch-gates.yaml. "
            "File may be empty or corrupt.",
        )

    def test_all_test_results_keys_present_in_evidence(self):
        """Every test_results gate key exists in test-results-summary.json."""
        missing = [
            f"{g['id']} (key={g['key']})"
            for g in self.gates
            if g.get("key") not in self.evidence
        ]
        self.assertEqual(
            missing,
            [],
            f"These test_results gate keys are absent from test-results-summary.json: "
            f"{missing}. Update the test runner to produce them.",
        )

    def test_security_tests_all_pass_key_present(self):
        """security_tests_all_pass is a required key in test-results-summary.json."""
        self.assertIn("security_tests_all_pass", self.evidence)

    def test_security_replay_test_pass_key_present(self):
        """security_replay_test_pass is a required key."""
        self.assertIn("security_replay_test_pass", self.evidence)

    def test_idempotency_memory_pass_key_present(self):
        """idempotency_memory_pass is a required key."""
        self.assertIn("idempotency_memory_pass", self.evidence)

    def test_idempotency_sqlite_pass_key_present(self):
        """idempotency_sqlite_pass is a required key."""
        self.assertIn("idempotency_sqlite_pass", self.evidence)

    def test_sqlite_fallback_pass_key_present(self):
        """sqlite_fallback_pass is a required key."""
        self.assertIn("sqlite_fallback_pass", self.evidence)

    def test_outbound_retry_test_pass_key_present(self):
        """outbound_retry_test_pass is a required key."""
        self.assertIn("outbound_retry_test_pass", self.evidence)

    def test_outbound_fallback_test_pass_key_present(self):
        """outbound_fallback_test_pass is a required key."""
        self.assertIn("outbound_fallback_test_pass", self.evidence)


@unittest.skipUnless(_GATES_FILE.exists() and _STAGING_REPORT_FILE.exists(), "Artifact files missing")
class StagingReportGateParityTests(unittest.TestCase):
    """Every gate with source=staging_report has its key in staging-validation-report.json."""

    @classmethod
    def setUpClass(cls):
        cls.evidence = _load_json(_STAGING_REPORT_FILE)
        cls.gates = _get_gates("staging_report")

    def test_at_least_one_staging_report_gate_defined(self):
        """Sanity check: launch-gates.yaml should have staging_report gates."""
        self.assertGreater(
            len(self.gates),
            0,
            "No staging_report gates found in launch-gates.yaml.",
        )

    def test_all_staging_report_keys_present_in_evidence(self):
        """Every staging_report gate key exists in staging-validation-report.json."""
        missing = [
            f"{g['id']} (key={g['key']})"
            for g in self.gates
            if g.get("key") not in self.evidence
        ]
        self.assertEqual(
            missing,
            [],
            f"These staging_report gate keys are absent from staging-validation-report.json: "
            f"{missing}. Re-run staging_validation.py to refresh the report.",
        )

    def test_latency_p50_ok_key_present(self):
        """latency_p50_ok is a required staging report key."""
        self.assertIn("latency_p50_ok", self.evidence)

    def test_latency_p95_ok_key_present(self):
        """latency_p95_ok is a required staging report key."""
        self.assertIn("latency_p95_ok", self.evidence)

    def test_success_rate_ok_key_present(self):
        """success_rate_ok is a required staging report key."""
        self.assertIn("success_rate_ok", self.evidence)

    def test_throughput_ok_key_present(self):
        """throughput_ok is a required staging report key."""
        self.assertIn("throughput_ok", self.evidence)

    def test_fallback_timing_ok_key_present(self):
        """fallback_timing_ok is a required staging report key."""
        self.assertIn("fallback_timing_ok", self.evidence)

    def test_sample_count_ok_key_present(self):
        """sample_count_ok is a required staging report key."""
        self.assertIn("sample_count_ok", self.evidence)


@unittest.skipUnless(_GATES_FILE.exists(), "launch-gates.yaml missing")
class FileExistsGateParityTests(unittest.TestCase):
    """Every gate with source=file_exists has the referenced file on disk."""

    @classmethod
    def setUpClass(cls):
        cls.gates = _get_gates("file_exists")

    def test_at_least_one_file_exists_gate_defined(self):
        """Sanity: some file_exists gates should be present."""
        self.assertGreater(len(self.gates), 0)

    def test_all_file_exists_gate_paths_are_present_on_disk(self):
        """Every file_exists gate path resolves to an existing file."""
        missing = []
        for g in self.gates:
            key = g.get("key", "")
            target = _PROJECT_ROOT / key
            if not target.exists():
                missing.append(f"{g['id']} (path={key})")
        self.assertEqual(
            missing,
            [],
            f"These file_exists gates reference missing files: {missing}. "
            f"Create the files or update the gate key.",
        )


@unittest.skipUnless(_GATES_FILE.exists(), "launch-gates.yaml missing")
class FileContainsGateParityTests(unittest.TestCase):
    """Every gate with source=file_contains has parseable key and matching content."""

    @classmethod
    def setUpClass(cls):
        cls.gates = _get_gates("file_contains")

    def test_all_file_contains_keys_are_valid_and_match_content(self):
        failures = []
        for g in self.gates:
            raw = g.get("key", "")
            path_part, sep, needle = raw.partition("::")
            if not sep:
                failures.append(f"{g['id']} invalid format: {raw}")
                continue
            target = _PROJECT_ROOT / path_part.strip()
            if not target.exists():
                failures.append(f"{g['id']} missing file: {path_part.strip()}")
                continue
            text = target.read_text(encoding="utf-8").lower()
            if needle.strip().lower() not in text:
                failures.append(f"{g['id']} missing substring: {needle.strip()}")
        self.assertEqual(
            failures,
            [],
            f"These file_contains gates failed parity checks: {failures}",
        )


@unittest.skipUnless(_GATES_FILE.exists(), "launch-gates.yaml missing")
class GateSchemaValidationTests(unittest.TestCase):
    """Each gate entry has required fields with valid values."""

    _VALID_SOURCES = {"test_results", "staging_report", "file_exists", "file_contains", "manual"}

    @classmethod
    def setUpClass(cls):
        doc = _load_yaml(_GATES_FILE)
        cls.gates = doc.get("gates", [])

    def test_all_gates_have_id_field(self):
        """Every gate entry has a non-empty id field."""
        bad = [g for g in self.gates if not g.get("id")]
        self.assertEqual(bad, [], f"Gates missing id: {bad}")

    def test_all_gates_have_label_field(self):
        """Every gate entry has a non-empty label field."""
        bad = [g for g in self.gates if not g.get("label")]
        self.assertEqual(bad, [], f"Gates missing label: {bad}")

    def test_all_gates_have_valid_source(self):
        """Every gate entry has a recognized source value."""
        bad = [
            g["id"] for g in self.gates
            if g.get("source") not in self._VALID_SOURCES
        ]
        self.assertEqual(
            bad,
            [],
            f"Gates with unknown source: {bad}. Valid: {self._VALID_SOURCES}",
        )

    def test_all_gates_have_key_field(self):
        """Every gate entry has a key field."""
        bad = [g["id"] for g in self.gates if "key" not in g]
        self.assertEqual(bad, [], f"Gates missing key field: {bad}")

    def test_gate_ids_are_unique(self):
        """Gate IDs must be unique within the gates list."""
        ids = [g.get("id") for g in self.gates]
        seen = set()
        dupes = [x for x in ids if x in seen or seen.add(x)]
        self.assertEqual(dupes, [], f"Duplicate gate IDs: {dupes}")


if __name__ == "__main__":
    unittest.main()
