import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from app.services.expiring_store import (
    ExpiringKeyStore,
    SQLiteExpiringKeyStore,
    create_expiring_store,
)


class InMemoryExpiringStoreTests(unittest.TestCase):
    def test_seen_recently_behaves_as_expected(self):
        current_time = [1000.0]

        def now_fn():
            return current_time[0]

        store = ExpiringKeyStore(window_seconds=10, now_fn=now_fn)

        self.assertFalse(store.seen_recently("k1"))
        self.assertTrue(store.seen_recently("k1"))

        current_time[0] += 11
        self.assertFalse(store.seen_recently("k1"))


class SQLiteExpiringStoreTests(unittest.TestCase):
    def test_sqlite_store_persists_and_expires(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "runtime_state.db")
            current_time = [1000.0]

            def now_fn():
                return current_time[0]

            store = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace="test_namespace",
                window_seconds=5,
                now_fn=now_fn,
            )

            self.assertFalse(store.seen_recently("k2"))
            self.assertTrue(store.seen_recently("k2"))

            current_time[0] += 6
            self.assertFalse(store.seen_recently("k2"))
            store.close()

    def test_factory_falls_back_to_memory_when_sqlite_fails(self):
        app = Flask(__name__)
        app.config["STATE_STORE_BACKEND"] = "sqlite"
        app.config["STATE_STORE_SQLITE_PATH"] = "data/runtime_state.db"
        app.config["STATE_STORE_FALLBACK_TO_MEMORY"] = True

        with patch(
            "app.services.expiring_store.SQLiteExpiringKeyStore",
            side_effect=sqlite3.OperationalError("cannot open db"),
        ):
            store = create_expiring_store(
                app=app,
                extension_key="test_store",
                namespace="test",
                window_seconds=10,
            )

        self.assertIsInstance(store, ExpiringKeyStore)

    def test_factory_raises_when_sqlite_fails_and_fallback_disabled(self):
        app = Flask(__name__)
        app.config["STATE_STORE_BACKEND"] = "sqlite"
        app.config["STATE_STORE_SQLITE_PATH"] = "data/runtime_state.db"
        app.config["STATE_STORE_FALLBACK_TO_MEMORY"] = False

        with patch(
            "app.services.expiring_store.SQLiteExpiringKeyStore",
            side_effect=sqlite3.OperationalError("cannot open db"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                create_expiring_store(
                    app=app,
                    extension_key="test_store_fail",
                    namespace="test",
                    window_seconds=10,
                )


class SQLiteRestartContinuityTests(unittest.TestCase):
    """
    Story 8.4 AC1 — SQLite-backed store behavior verified across restart scenarios.
    Simulates process restart by closing a store and opening a new instance
    against the same database file.
    """

    def test_sqlite_store_key_survives_simulated_restart(self):
        """State written before close persists in a new store instance (within window)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "runtime_state.db")
            current_time = [1000.0]

            def now_fn():
                return current_time[0]

            # First "process lifetime" — record a key
            store = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace="idempotency",
                window_seconds=60,
                now_fn=now_fn,
            )
            self.assertFalse(store.seen_recently("wamid-abc123"))
            store.close()

            # Simulated restart — new store instance, same DB, still within window
            current_time[0] += 5
            store2 = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace="idempotency",
                window_seconds=60,
                now_fn=now_fn,
            )
            self.assertTrue(store2.seen_recently("wamid-abc123"))
            store2.close()

    def test_sqlite_store_expired_key_not_seen_after_restart(self):
        """Keys that expired before restart are not present when a new store opens."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "runtime_state.db")
            current_time = [1000.0]

            def now_fn():
                return current_time[0]

            store = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace="idempotency",
                window_seconds=10,
                now_fn=now_fn,
            )
            self.assertFalse(store.seen_recently("old-key"))
            store.close()

            # Restart well after window expires
            current_time[0] += 20
            store2 = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace="idempotency",
                window_seconds=10,
                now_fn=now_fn,
            )
            self.assertFalse(store2.seen_recently("old-key"))
            store2.close()

    def test_sqlite_store_namespace_isolation_survives_restart(self):
        """Keys in separate namespaces do not cross-contaminate across restart."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "runtime_state.db")

            store_a = SQLiteExpiringKeyStore(
                db_path=db_path, namespace="ns_a", window_seconds=60
            )
            store_b = SQLiteExpiringKeyStore(
                db_path=db_path, namespace="ns_b", window_seconds=60
            )
            store_a.seen_recently("shared-key")
            store_a.close()
            store_b.close()

            # Restart
            store_a2 = SQLiteExpiringKeyStore(
                db_path=db_path, namespace="ns_a", window_seconds=60
            )
            store_b2 = SQLiteExpiringKeyStore(
                db_path=db_path, namespace="ns_b", window_seconds=60
            )
            # ns_a has the key; ns_b must not see it
            self.assertTrue(store_a2.seen_recently("shared-key"))
            self.assertFalse(store_b2.seen_recently("shared-key"))
            store_a2.close()
            store_b2.close()


class StoreCloseLifecycleTests(unittest.TestCase):
    """
    Story 7.9 — Store teardown lifecycle detectability tests.
    Asserts close() is idempotent and that _cleanup_extension_resources
    calls close() on all registered extensions.
    """

    def test_memory_store_close_is_idempotent(self):
        """Calling close() multiple times on ExpiringKeyStore must not raise."""
        store = ExpiringKeyStore(window_seconds=10)
        store.close()
        store.close()  # second call must be safe

    def test_sqlite_store_close_is_idempotent(self):
        """Calling close() multiple times on SQLiteExpiringKeyStore must not raise."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = os.path.join(tmp_dir, "lifecycle.db")
            store = SQLiteExpiringKeyStore(
                db_path=db_path,
                namespace="lifecycle_test",
                window_seconds=10,
            )
            store.close()
            store.close()  # second call must be safe

    def test_cleanup_teardown_calls_close_on_registered_extensions(self):
        """_cleanup_extension_resources teardown must call close() on registered extensions."""
        import os
        from unittest.mock import MagicMock

        _env = {
            "WHATSAPP_PROVIDER": "meta",
            "ACCESS_TOKEN": "x",
            "APP_SECRET": "x",
            "VERSION": "v18.0",
            "PHONE_NUMBER_ID": "1",
            "VERIFY_TOKEN": "x",
            "FLASK_SECRET_KEY": "test-secret",
        }
        with patch.dict(os.environ, _env, clear=False):
            from app import create_app

            app = create_app()

        mock_store = MagicMock()
        mock_store.close = MagicMock()

        with app.app_context():
            app.extensions["test_lifecycle_store"] = mock_store
            # Simulate teardown_appcontext by pushing/popping context
        # After context exits, teardown is called automatically

        mock_store.close.assert_called()

    def test_cleanup_teardown_continues_after_close_exception(self):
        """If one extension close() raises, remaining extensions must still be closed."""
        import os
        from unittest.mock import MagicMock

        _env = {
            "WHATSAPP_PROVIDER": "meta",
            "ACCESS_TOKEN": "x",
            "APP_SECRET": "x",
            "VERSION": "v18.0",
            "PHONE_NUMBER_ID": "1",
            "VERIFY_TOKEN": "x",
            "FLASK_SECRET_KEY": "test-secret",
        }
        with patch.dict(os.environ, _env, clear=False):
            from app import create_app

            app = create_app()

        bad_store = MagicMock()
        bad_store.close.side_effect = RuntimeError("close failed")
        good_store = MagicMock()
        good_store.close = MagicMock()

        with app.app_context():
            app.extensions["test_bad_store"] = bad_store
            app.extensions["test_good_store"] = good_store
        # After context exits, teardown fires for both; bad_store raises but good_store should also fire

        good_store.close.assert_called()


if __name__ == "__main__":
    unittest.main()
