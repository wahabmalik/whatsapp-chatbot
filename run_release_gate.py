"""
Release Gate Test Runner Script

Usage:
    python run_release_gate.py [--domain SECURITY|RELIABILITY|LATENCY|ALL]
    
Purpose:
    Orchestrate critical product path tests as pre-deployment release gate.
    
Exit Codes:
    0 = All tests passed, safe to deploy
    1 = Test failures, do not deploy
    2 = Configuration/environment error
"""

import sys
import subprocess
import json
import time
from enum import Enum
from pathlib import Path
from typing import Tuple, Dict, List


class GateDomain(Enum):
    SECURITY = "CriticalPathSecurityTests"
    RELIABILITY = "CriticalPathReliabilityTests"
    LATENCY = "CriticalPathLatencyTests"
    INTEGRATION = "CriticalPathIntegrationTests"
    ALL = None


class ReleaseGateRunner:
    def __init__(self):
        self.results: Dict[str, Dict] = {}
        self.start_time = None
        self.end_time = None
    
    def run_tests(self, domain: GateDomain) -> int:
        """Run critical product path tests for specified domain."""
        self.start_time = time.time()
        
        if domain == GateDomain.ALL:
            domains = [GateDomain.SECURITY, GateDomain.RELIABILITY, 
                      GateDomain.LATENCY, GateDomain.INTEGRATION]
        else:
            domains = [domain]
        
        all_passed = True
        for d in domains:
            passed = self._run_domain_tests(d)
            all_passed = all_passed and passed
        
        self.end_time = time.time()
        self._print_summary()
        
        return 0 if all_passed else 1
    
    def _run_domain_tests(self, domain: GateDomain) -> bool:
        """Run tests for a specific domain."""
        test_class = domain.value
        cmd = [
            sys.executable,
            "-m", "pytest",
            f"tests/test_critical_product_paths.py::{test_class}",
            "-v",
            "--tb=short",
            "--color=yes",
        ]
        
        print(f"\n{'='*70}")
        print(f"Running {domain.name} domain tests...")
        print(f"Command: {' '.join(cmd)}")
        print(f"{'='*70}\n")
        
        result = subprocess.run(cmd, capture_output=False)
        
        self.results[domain.name] = {
            "passed": result.returncode == 0,
            "exit_code": result.returncode,
        }
        
        return result.returncode == 0
    
    def _print_summary(self):
        """Print test execution summary."""
        elapsed = self.end_time - self.start_time
        
        print(f"\n{'='*70}")
        print("RELEASE GATE SUMMARY")
        print(f"{'='*70}\n")
        
        passed_count = sum(1 for r in self.results.values() if r["passed"])
        total_count = len(self.results)
        
        for domain_name, result in self.results.items():
            status = "✅ PASS" if result["passed"] else "❌ FAIL"
            print(f"  {domain_name:25} {status}")
        
        print(f"\n{'-'*70}")
        print(f"Overall: {passed_count}/{total_count} domains passed")
        print(f"Duration: {elapsed:.2f}s")
        
        if passed_count == total_count:
            print("\n🚀 RELEASE GATE PASSED - Safe to deploy")
        else:
            print(f"\n⛔ RELEASE GATE FAILED - {total_count - passed_count} domain(s) failed")
            print("   Regressions detected. Investigate before deployment.")
        
        print(f"{'='*70}\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Critical Product Paths Release Gate Runner"
    )
    parser.add_argument(
        "--domain",
        type=str,
        default="ALL",
        choices=["SECURITY", "RELIABILITY", "LATENCY", "INTEGRATION", "ALL"],
        help="Test domain to run (default: ALL)",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Fail if any test generates warnings (strict mode)",
    )
    
    args = parser.parse_args()
    
    domain = GateDomain[args.domain]
    runner = ReleaseGateRunner()
    exit_code = runner.run_tests(domain)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
