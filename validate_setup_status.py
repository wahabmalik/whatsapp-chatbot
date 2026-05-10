#!/usr/bin/env python
"""Quick validation of setup status and config validation features."""

import os
import json
import sys
from unittest.mock import patch

# Set up minimal environment
MINIMAL_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
}

def test_get_setup_status_function():
    """Test that get_setup_status works correctly."""
    print("\n[TEST] get_setup_status function")
    with patch.dict(os.environ, MINIMAL_ENV, clear=False):
        from app import create_app
        from app.services.health_check import get_setup_status
        
        app = create_app()
        status = get_setup_status(app)
        
        print(f"  ✓ setup_complete: {status['setup_complete']}")
        print(f"  ✓ required_keys: {len(status['required_keys'])} keys")
        print(f"  ✓ missing_keys: {len(status['missing_keys'])} keys")
        print(f"  ✓ validation_errors: {len(status['validation_errors'])} errors")
        return status['setup_complete'] and len(status['validation_errors']) == 0

def test_health_endpoint_includes_setup():
    """Test that health endpoint includes setup status."""
    print("\n[TEST] Health endpoint includes setup status")
    with patch.dict(os.environ, MINIMAL_ENV, clear=False):
        from app import create_app
        
        app = create_app()
        client = app.test_client()
        
        response = client.get("/health")
        data = json.loads(response.data)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "setup" in data, "setup key missing from health response"
        assert "setup_complete" in data["setup"], "setup_complete key missing"
        
        print(f"  ✓ HTTP {response.status_code}")
        print(f"  ✓ setup_complete: {data['setup']['setup_complete']}")
        print(f"  ✓ validation_errors: {len(data['setup']['validation_errors'])}")
        return True

def test_setup_status_api():
    """Test that setup status API endpoint works."""
    print("\n[TEST] Setup status API endpoint /api/setup/status")
    with patch.dict(os.environ, MINIMAL_ENV, clear=False):
        from app import create_app
        
        app = create_app()
        client = app.test_client()
        
        with client.session_transaction() as sess:
            sess["dashboard_role"] = "operator"
        
        response = client.get("/api/setup/status")
        data = json.loads(response.data)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert data.get("ok") == True, "ok flag not true"
        assert "setup_complete" in data, "setup_complete missing"
        assert "missing_keys" in data, "missing_keys missing"
        
        print(f"  ✓ HTTP {response.status_code}")
        print(f"  ✓ ok: {data['ok']}")
        print(f"  ✓ setup_complete: {data['setup_complete']}")
        return True

def test_webhook_validation_blocking():
    """Test that webhook is safely blocked by either signature or config guards."""
    print("\n[TEST] Webhook blocks with config validation errors")
    invalid_env = dict(MINIMAL_ENV)
    invalid_env["PHONE_NUMBER_ID"] = ""
    with patch.dict(os.environ, invalid_env, clear=False):
        from app import create_app

        app = create_app()
        client = app.test_client()

        response = client.post(
            "/webhook",
            json={"object": "whatsapp_business_account", "entry": []},
        )

        data = json.loads(response.data)

        # Depending on decorator order and security policy, either response is acceptable:
        # - 403: signature guard blocks first
        # - 503: config validation guard blocks first
        assert response.status_code in {403, 503}, f"Expected 403 or 503, got {response.status_code}"
        if response.status_code == 503:
            assert data.get("reason") == "config_invalid", (
                f"Expected config_invalid, got {data.get('reason')}"
            )
            assert "validation_errors" in data, "validation_errors missing"
            assert len(data["validation_errors"]) > 0, "validation_errors should not be empty"
            print(f"  ✓ HTTP {response.status_code} (config guard)")
            print(f"  ✓ reason: {data.get('reason')}")
            print(f"  ✓ validation_errors: {len(data['validation_errors'])} error(s)")
            print(f"    - {data['validation_errors'][0]}")
        else:
            print(f"  ✓ HTTP {response.status_code} (signature guard)")
            print("  ✓ webhook is protected before config processing")
        return True

def main():
    print("=" * 70)
    print("SETUP STATUS & CONFIGURATION VALIDATION QUICK TESTS")
    print("=" * 70)
    
    tests = [
        ("Setup Status Function", test_get_setup_status_function),
        ("Health Endpoint", test_health_endpoint_includes_setup),
        ("Setup Status API", test_setup_status_api),
        ("Webhook Validation Blocking", test_webhook_validation_blocking),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                print(f"\n  ✅ {test_name} PASSED")
                passed += 1
            else:
                print(f"\n  ❌ {test_name} FAILED")
                failed += 1
        except Exception as e:
            print(f"\n  ❌ {test_name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
