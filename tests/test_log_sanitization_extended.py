"""Expanded log-sanitization tests for evolving secret/token patterns (Epic 5 Retro Action Item 3).

Verifies that sanitize_text() and SafeObservabilityFilter handle:
- Current and anticipated OpenAI API key formats (sk-, sk-proj-, sk-org-, sk-ant-, etc.)
- Authorization / Bearer header variants
- Key=value pairs with various separators and casing
- Nested containers: list, dict, tuple, set, frozenset
- Filter integration: record.msg, record.args (tuple and dict forms)
- Sanitization is idempotent (re-sanitizing already-redacted output is safe)
- Legitimate content (non-secret strings) is not over-redacted
"""

from __future__ import annotations

import logging
import unittest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize(text: str) -> str:
    from app.services.observability import sanitize_text
    return sanitize_text(text)


def _sanitize_arg(value):
    from app.services.observability import _sanitize_arg
    return _sanitize_arg(value)


# ---------------------------------------------------------------------------
# OpenAI key pattern coverage
# ---------------------------------------------------------------------------

class OpenAIKeyPatternTests(unittest.TestCase):
    """sanitize_text redacts all plausible OpenAI-style bearer key variants."""

    # Each tuple is (description, raw_text, must_not_contain, must_contain)
    # Note: _KEY_VALUE_PATTERN fires first on recognized key=value pairs,
    # so sk-proj/sk-ant under OPENAI_API_KEY= produce "[REDACTED]" not "sk-[REDACTED]"
    _CASES = [
        (
            "classic sk- key",
            "key=sk-abcDEF1234567890",
            ["sk-abcDEF1234567890"],
            ["sk-[REDACTED]"],
        ),
        (
            "sk-proj- prefix under recognized key (key-value pattern fires)",
            "OPENAI_API_KEY=sk-proj-Abc123_longersegment",
            ["sk-proj-Abc123_longersegment"],
            ["[REDACTED]"],
        ),
        (
            "sk-org- bare token (openai pattern fires)",
            "token: sk-org-XYZ987abcdefghij",
            ["sk-org-XYZ987abcdefghij"],
            ["sk-[REDACTED]"],
        ),
        (
            "sk-ant- prefix under recognized key (key-value pattern fires)",
            "OPENAI_API_KEY=sk-ant-api03-Abcdef1234567890",
            ["sk-ant-api03-Abcdef1234567890"],
            ["[REDACTED]"],
        ),
        (
            "sk-live_ variant with underscores (backup not recognized key)",
            "backup=sk-live_ABC-12345678",
            ["sk-live_ABC-12345678"],
            ["sk-[REDACTED]"],
        ),
        (
            "key embedded mid-sentence",
            "Using key sk-embed-1234567890abcdef for request",
            ["sk-embed-1234567890abcdef"],
            ["sk-[REDACTED]"],
        ),
        (
            "multiple bare keys in one string",
            "primary=sk-first-0123456789 secondary=sk-second-abcdefghij",
            ["sk-first-0123456789", "sk-second-abcdefghij"],
            ["sk-[REDACTED]"],
        ),
        (
            "key with uppercase hex segment",
            "apikey=sk-UPPER-ABCDEF1234567890",
            ["sk-UPPER-ABCDEF1234567890"],
            ["sk-[REDACTED]"],
        ),
    ]

    def test_openai_key_variants(self):
        for desc, raw, must_not, must_have in self._CASES:
            with self.subTest(desc=desc):
                result = _sanitize(raw)
                for token in must_not:
                    self.assertNotIn(token, result, f"[{desc}] token '{token}' not redacted")
                for token in must_have:
                    self.assertIn(token, result, f"[{desc}] expected '{token}' in output")

    def test_app_secret_key_value(self):
        result = _sanitize("app_secret=mysecretappvalue")
        self.assertNotIn("mysecretappvalue", result)

    def test_verify_token_key_value(self):
        result = _sanitize("verify_token=myverifytoken")
        self.assertNotIn("myverifytoken", result)

    def test_non_secret_label_not_redacted(self):
        """Normal text that does not contain secret patterns is preserved."""
        result = _sanitize("hello world, status=ok, count=42")
        self.assertEqual(result, "hello world, status=ok, count=42")

    def test_bearer_standalone_pattern(self):
        """'Bearer <token>' appearing anywhere is redacted."""
        result = _sanitize("Sending: Bearer abc123tokenvalue")
        self.assertNotIn("abc123tokenvalue", result)
        self.assertIn("Bearer [REDACTED]", result)

    def test_telegram_bot_url_path_is_redacted(self):
        raw = (
            "POST https://api.telegram.org/"
            "bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11/sendMessage failed"
        )
        result = _sanitize(raw)
        self.assertNotIn("ABC-DEF1234ghIkl-zyx57W2v1u123ew11", result)
        self.assertIn("/bot[REDACTED]/sendMessage", result)


# ---------------------------------------------------------------------------
# Nested container sanitization
# ---------------------------------------------------------------------------

class NestedContainerSanitizationTests(unittest.TestCase):
    """_sanitize_arg recursively sanitizes nested structures."""

    def test_list_of_strings(self):
        raw = ["normal", "access_token=secret123", "sk-key-0123456789abcdef"]
        result = _sanitize_arg(raw)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "normal")
        self.assertNotIn("secret123", result[1])
        self.assertNotIn("sk-key-0123456789abcdef", result[2])

    def test_dict_of_strings(self):
        raw = {"status": "ok", "openai_api_key": "sk-dict-0123456789abcdef"}
        result = _sanitize_arg(raw)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("sk-dict-0123456789abcdef", str(result["openai_api_key"]))

    def test_tuple_of_strings(self):
        raw = ("safe value", "access-token=tok123abc")
        result = _sanitize_arg(raw)
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], "safe value")
        self.assertNotIn("tok123abc", result[1])

    def test_set_of_strings(self):
        raw = {"openai_api_key=sk-set-0123456789ab", "hello"}
        result = _sanitize_arg(raw)
        self.assertIsInstance(result, set)
        self.assertFalse(
            any("sk-set-0123456789ab" in str(item) for item in result),
            "Secret not redacted inside set",
        )

    def test_frozenset_of_strings(self):
        raw = frozenset({"verify_token=frozentoken123", "public"})
        result = _sanitize_arg(raw)
        self.assertIsInstance(result, frozenset)
        self.assertFalse(
            any("frozentoken123" in str(item) for item in result),
            "Secret not redacted inside frozenset",
        )

    def test_list_of_dicts(self):
        raw = [
            {"info": "access_token=nested_secret_val"},
            {"name": "alice"},
        ]
        result = _sanitize_arg(raw)
        combined = str(result)
        self.assertNotIn("nested_secret_val", combined)
        self.assertIn("alice", combined)

    def test_dict_with_list_value(self):
        raw = {"tokens": ["sk-nested-0123456789ab", "sk-nested2-0123456789ab"]}
        result = _sanitize_arg(raw)
        combined = str(result["tokens"])
        self.assertNotIn("sk-nested-0123456789ab", combined)
        self.assertNotIn("sk-nested2-0123456789ab", combined)

    def test_deeply_nested_structure(self):
        raw = {"a": {"b": ["openai_api_key=sk-deep-0123456789ab"]}}
        result = _sanitize_arg(raw)
        combined = str(result)
        self.assertNotIn("sk-deep-0123456789ab", combined)

    def test_non_string_scalars_pass_through(self):
        """Integers, floats, None, and booleans must not be altered."""
        self.assertEqual(_sanitize_arg(42), 42)
        self.assertIsNone(_sanitize_arg(None))
        self.assertEqual(_sanitize_arg(3.14), 3.14)
        self.assertTrue(_sanitize_arg(True))


# ---------------------------------------------------------------------------
# SafeObservabilityFilter integration
# ---------------------------------------------------------------------------

class SafeObservabilityFilterTests(unittest.TestCase):
    """SafeObservabilityFilter sanitizes record.msg and record.args before emit."""

    def _make_record(self, msg: str, args=None) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg=msg,
            args=args, exc_info=None,
        )
        return record

    def _apply_filter(self, record: logging.LogRecord) -> logging.LogRecord:
        from app.services.observability import SafeObservabilityFilter
        f = SafeObservabilityFilter()
        f.filter(record)
        return record

    def test_filter_sanitizes_record_msg(self):
        record = self._make_record("access_token=supersecret123 logged")
        filtered = self._apply_filter(record)
        self.assertNotIn("supersecret123", str(filtered.msg))
        self.assertIn("[REDACTED]", str(filtered.msg))

    def test_filter_sanitizes_record_args_tuple(self):
        record = self._make_record("key=%s", args=("sk-tuple-0123456789ab",))
        filtered = self._apply_filter(record)
        self.assertNotIn("sk-tuple-0123456789ab", str(filtered.args))

    def test_filter_sanitizes_record_args_dict(self):
        # Construct the record without args, then set args directly to avoid
        # LogRecord constructor probing dict[0] in Python 3.13+.
        record = self._make_record("data")
        record.args = {"key": "access_token=dictval123"}
        filtered = self._apply_filter(record)
        self.assertNotIn("dictval123", str(filtered.args))

    def test_filter_adds_correlation_id_attribute(self):
        """Filter always sets correlation_id on the record."""
        record = self._make_record("ordinary message")
        filtered = self._apply_filter(record)
        self.assertTrue(hasattr(filtered, "correlation_id"))
        self.assertIsNotNone(filtered.correlation_id)

    def test_filter_returns_true(self):
        """filter() must return True so the log record is emitted."""
        from app.services.observability import SafeObservabilityFilter
        f = SafeObservabilityFilter()
        record = self._make_record("some log message")
        result = f.filter(record)
        self.assertTrue(result)

    def test_filter_with_no_secrets_does_not_alter_msg(self):
        """Messages without secrets are unchanged by the filter."""
        original = "status=ok count=42 provider=meta"
        record = self._make_record(original)
        filtered = self._apply_filter(record)
        self.assertEqual(filtered.msg, original)

    def test_filter_idempotent_on_already_redacted_args(self):
        """Filtering a record that was already sanitized produces the same output."""
        record = self._make_record("key=%s", args=("sk-[REDACTED]",))
        first = self._apply_filter(record)
        # Re-apply (simulates double-filter in unusual logging configurations)
        second = self._apply_filter(first)
        self.assertEqual(str(first.args), str(second.args))


# ---------------------------------------------------------------------------
# Phone number masking
# ---------------------------------------------------------------------------

class PhoneNumberMaskingTests(unittest.TestCase):
    """Phone numbers in log strings are partially masked."""

    def test_e164_phone_masked(self):
        result = _sanitize("from=+15551234567")
        self.assertNotIn("15551234567", result)
        self.assertRegex(result, r"\+?\d{1,4}\.\.\.4567")

    def test_phone_without_plus_masked(self):
        result = _sanitize("wa_id=15551234567 logged")
        self.assertNotIn("15551234567", result)

    def test_short_number_not_over_masked(self):
        """A 4-digit number like a PIN or year should not be mangled."""
        result = _sanitize("year=2024 count=42")
        self.assertIn("2024", result)
        self.assertIn("42", result)


if __name__ == "__main__":
    unittest.main()
