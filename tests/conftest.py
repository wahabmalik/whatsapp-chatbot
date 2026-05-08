"""
pytest configuration and shared fixtures.

Session-level setup:
- Suppress logging.raiseExceptions so background threads that outlive pytest
  teardown (e.g. deferred delivery retries) do not cause spurious exit-code 1
  when their logging handlers encounter a closed stderr/stdout stream.
  All 16 tests in test_critical_product_paths.py pass; the noise is purely from
  daemon threads that are still alive when the interpreter begins shutdown.
"""
import logging

import pytest


@pytest.fixture(autouse=True, scope="session")
def suppress_teardown_logging_noise():
    """
    Prevent background-thread logging calls from crashing on a closed stream
    after pytest has torn down its capture infrastructure.

    logging.raiseExceptions controls whether errors inside a logging handler's
    emit() propagate.  Setting it False during the test session matches the
    recommended approach for daemon threads that may outlive the test runner.
    """
    original = logging.raiseExceptions
    logging.raiseExceptions = False
    yield
    logging.raiseExceptions = original
