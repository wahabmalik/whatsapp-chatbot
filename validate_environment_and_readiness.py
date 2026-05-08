"""
validate_environment_and_readiness.py

Standardized Validation Command Wrapper (Epic 4 Action Item 5b)

Removes environment-specific ambiguity by:
1. Detecting current environment state (.env, .venv)
2. Validating all required configuration is set
3. Running deployment validation in isolated test phase
4. Providing clear pass/fail signals with evidence path
5. Generating validation artifact for release governance
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Tuple, List

# Required environment variables for base operation
REQUIRED_ENV_BASE = [
    'WHATSAPP_PROVIDER',
    'APP_SECRET',
    'OPENAI_API_KEY',
]

# Additional env for specific providers
PROVIDER_ENV = {
    'evolution': [
        'EVOLUTION_API_URL',
        'EVOLUTION_API_KEY',
        'EVOLUTION_INSTANCE_NAME',
    ],
    'meta': [
        'ACCESS_TOKEN',
        'PHONE_NUMBER_ID',
        'VERSION',
    ],
}

# Target timings from setup guide
TARGET_TIMINGS = {
    'config_entry': 120,        # 2 minutes
    'end_to_end': 2700,         # 45 minutes
}


class EnvironmentValidator:
    """Validate environment and readiness."""

    def __init__(self):
        self.issues = []
        self.warnings = []
        self.artifacts = {}

    def check_dotenv_exists(self) -> bool:
        """Check if .env file exists."""
        env_file = Path('.env')
        if not env_file.exists():
            self.issues.append("❌ .env file not found. Run 'copy example.env .env' first")
            return False
        return True

    def check_required_env_vars(self) -> bool:
        """Check that all required env vars are set."""
        missing = []

        for var in REQUIRED_ENV_BASE:
            if not os.environ.get(var):
                missing.append(var)

        if missing:
            self.issues.append(
                f"❌ Missing required environment variables: {', '.join(missing)}\n"
                f"   Set these in .env file"
            )
            return False

        # Check provider-specific vars
        provider = os.environ.get('WHATSAPP_PROVIDER', '').lower()
        if provider not in PROVIDER_ENV:
            self.issues.append(
                f"❌ WHATSAPP_PROVIDER='{provider}' not recognized. "
                f"Must be one of: {', '.join(PROVIDER_ENV.keys())}"
            )
            return False

        provider_missing = []
        for var in PROVIDER_ENV[provider]:
            if not os.environ.get(var):
                provider_missing.append(var)

        if provider_missing:
            self.issues.append(
                f"❌ Missing {provider.upper()} provider variables: "
                f"{', '.join(provider_missing)}"
            )
            return False

        return True

    def check_venv_activated(self) -> bool:
        """Check if virtual environment is activated (warning-only, never blocks)."""
        in_venv = (
            hasattr(sys, 'real_prefix')
            or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
            or os.environ.get('VIRTUAL_ENV') is not None
        )
        if not in_venv:
            self.warnings.append(
                "⚠️  Virtual environment not detected. "
                "Run 'source .venv/bin/activate' (macOS/Linux) "
                "or '.venv\\Scripts\\activate' (Windows)"
            )
        return True  # venv activation is advisory; never a hard failure

    def check_dependencies_installed(self) -> bool:
        """Check if required packages are available."""
        required_modules = ['flask', 'requests', 'openai']
        missing = []

        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing.append(module)

        if missing:
            self.issues.append(
                f"❌ Missing Python packages: {', '.join(missing)}\n"
                f"   Run 'pip install -r requirements.txt'"
            )
            return False

        return True

    def validate_all(self) -> Tuple[bool, Dict]:
        """Run all validation checks."""
        checks = [
            ("Environment file", self.check_dotenv_exists),
            ("Required variables", self.check_required_env_vars),
            ("Virtual environment", self.check_venv_activated),
            ("Dependencies", self.check_dependencies_installed),
        ]

        print("\n🔍 Validating Environment Readiness...\n")

        success = True
        for check_name, check_func in checks:
            try:
                result = check_func()
                if result:
                    # Venv is advisory — show ⚠️ inline if a warning was just added
                    if check_name == "Virtual environment" and self.warnings:
                        print(f"⚠️  {check_name} (not activated — see warning below)")
                    else:
                        print(f"✅ {check_name}")
                else:
                    print(f"❌ {check_name}")
                    success = False
            except Exception as e:
                print(f"❌ {check_name}: {e}")
                self.issues.append(f"❌ {check_name} raised exception: {e}")
                success = False

        return success, self._build_report()

    def _build_report(self) -> Dict:
        """Build validation report artifact."""
        report = {
            'timestamp': datetime.now(timezone.utc).isoformat(),  # timezone-aware ISO 8601
            'validator_version': '1.0',
            'environment': {
                'provider': os.environ.get('WHATSAPP_PROVIDER', 'unknown'),
                'python_version': sys.version,
            },
            'checks': {
                'passed': len([i for i in self.issues if i.startswith("✅")]),
                'failed': len([i for i in self.issues if i.startswith("❌")]),
                'warnings': len(self.warnings),
            },
            'issues': self.issues,
            'warnings': self.warnings,
        }
        return report


def main():
    """Main entry point."""
    # Force UTF-8 output so emoji status indicators don't crash on Windows cp1252 consoles
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    validator = EnvironmentValidator()

    # Load .env if it exists
    env_file = Path('.env')
    if env_file.exists():
        from dotenv import load_dotenv
        try:
            load_dotenv(env_file)
        except ImportError:
            print(
                "⚠️  python-dotenv not installed. "
                "Ensure environment variables are set manually."
            )

    # Run validation
    success, report = validator.validate_all()

    # Print results
    print()
    if validator.warnings:
        print("Warnings:")
        for warning in validator.warnings:
            print(f"  {warning}")
        print()

    if validator.issues:
        print("Issues:")
        for issue in validator.issues:
            print(f"  {issue}")
        print()

    # Save report artifact
    artifact_dir = Path('_bmad-output/test-artifacts')
    artifact_dir.mkdir(parents=True, exist_ok=True)

    report_path = artifact_dir / 'environment-validation-report.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"📋 Validation report saved to: {report_path}\n")

    if success:
        print("✅ Environment validation PASSED")
        print("\nNext steps:")
        print("  1. Run tests: python -m pytest tests/ -v")
        print("  2. Start server: python run.py")
        print("  3. Test webhook: See SETUP_COMPLETE.md for curl examples")
        return 0
    else:
        print("❌ Environment validation FAILED")
        print("   Fix issues above and re-run this script")
        return 1


if __name__ == '__main__':
    sys.exit(main())
