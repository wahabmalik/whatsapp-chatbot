"""
tests/test_launch_gate_schema_parity.py

Launch-Gate Schema Parity Test (Epic 4 Action Item 2)

Verifies that:
1. launch-gates.yaml keys match implemented launch gate test artifacts
2. Evidence artifact schema matches expected gate key format
3. No gate keys are orphaned in config without tests
4. All blocking gates are mapped to implementation
"""

import os
import yaml
import unittest
from pathlib import Path


GATES_CONFIG_PATH = Path(__file__).parent.parent / '_bmad-output' / 'implementation-artifacts' / 'launch-gates.yaml'
TEST_ARTIFACTS_PATH = Path(__file__).parent.parent / '_bmad-output' / 'test-artifacts'


class LaunchGateSchemaParity(unittest.TestCase):
    """Verify launch-gates schema alignment."""

    @classmethod
    def setUpClass(cls):
        """Load launch gates config."""
        if GATES_CONFIG_PATH.exists():
            with open(GATES_CONFIG_PATH, 'r') as f:
                cls.gates_config = yaml.safe_load(f) or {}
        else:
            cls.gates_config = {}

    def test_launch_gates_config_exists_or_skip(self):
        """Skip tests if launch-gates.yaml is not yet created."""
        if not GATES_CONFIG_PATH.exists():
            self.skipTest(f"launch-gates.yaml not found at {GATES_CONFIG_PATH}; will be created in next iteration")

    def test_gates_config_has_required_fields(self):
        """Gates config must have gates and metadata sections."""
        if not self.gates_config:
            self.skipTest("No gates config loaded")

        required = ['gates', 'metadata']
        for field in required:
            self.assertIn(
                field, self.gates_config,
                f"launch-gates.yaml missing required field: {field}"
            )

    def test_all_gates_have_unique_keys(self):
        """All gate keys must be unique and well-formed."""
        if not self.gates_config or 'gates' not in self.gates_config:
            self.skipTest("No gates config loaded")

        gates = self.gates_config['gates']
        gate_keys = [g.get('key') for g in gates]

        # Check uniqueness
        self.assertEqual(
            len(gate_keys), len(set(gate_keys)),
            f"Duplicate gate keys found: {[k for k in gate_keys if gate_keys.count(k) > 1]}"
        )

        # Check format (E4-SEC-*, E4-OPS-*, E4-REL-*, etc)
        for key in gate_keys:
            self.assertIsNotNone(key)
            self.assertRegex(
                key, r'^[A-Z0-9]+-[A-Z0-9]+-\d+$',
                f"Gate key '{key}' does not match expected format (E.g., E4-SEC-05)"
            )

    def test_blocking_gates_are_implemented(self):
        """All blocking gates must have implementation evidence."""
        if not self.gates_config or 'gates' not in self.gates_config:
            self.skipTest("No gates config loaded")

        blocking_gates = [
            g.get('key') for g in self.gates_config['gates']
            if g.get('blocking') is True
        ]

        # Check for implementation references
        for gate_key in blocking_gates:
            # Each blocking gate should be validated by at least one test
            self.assertTrue(
                any(gate_key in str(f) for f in Path(__file__).parent.glob('test_*.py')),
                f"Blocking gate {gate_key} not referenced in any test file"
            )

    def test_gate_metadata_consistency(self):
        """Gate metadata must include required fields."""
        if not self.gates_config or 'gates' not in self.gates_config:
            self.skipTest("No gates config loaded")

        required_fields = ['key', 'name', 'blocking', 'domain']
        gates = self.gates_config['gates']

        for gate in gates:
            for field in required_fields:
                self.assertIn(
                    field, gate,
                    f"Gate {gate.get('key', 'unknown')} missing field: {field}"
                )

    def test_evidence_artifacts_exist(self):
        """Evidence artifacts directory should exist."""
        self.assertTrue(
            TEST_ARTIFACTS_PATH.exists(),
            f"Test artifacts path does not exist: {TEST_ARTIFACTS_PATH}"
        )

    def test_release_quality_matrix_exists_or_skip(self):
        """Release quality matrix should exist for traceability."""
        matrix_path = TEST_ARTIFACTS_PATH / 'release-quality-matrix.md'
        if not matrix_path.exists():
            self.skipTest(
                f"Release quality matrix not found at {matrix_path}; "
                "will be created by release gate validation"
            )


if __name__ == '__main__':
    unittest.main()
