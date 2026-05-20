"""UI contract tests for smooth-action loading states.

These tests lock the UX contract that high-frequency async actions expose
visible loading labels and are wired through busy-state helpers.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_setup_template_has_loading_labels_for_async_actions():
    content = _read("app/templates/setup.html")

    assert "data-setup-verify" in content
    assert "data-loading-label=\"Verifying...\"" in content

    assert "data-openai-key-form" in content
    assert "data-loading-label=\"Saving key...\"" in content


def test_onboarding_template_has_loading_labels_for_async_actions():
    content = _read("app/templates/onboarding.html")

    assert "id=\"retry-btn\"" in content
    assert "data-loading-label=\"Retrying...\"" in content

    assert "id=\"starter-pack-enable-btn\"" in content
    assert "data-loading-label=\"Enabling starter pack...\"" in content

    assert "id=\"starter-pack-replace-btn\"" in content
    assert "data-loading-label=\"Replacing drafts...\"" in content


def test_dashboard_template_has_loading_labels_for_reconnection_and_starter_pack_actions():
    content = _read("app/templates/dashboard.html")

    assert "[data-reconnection-open-flow]" in content
    assert "data-loading-label=\"Opening flow...\"" in content

    assert "[data-reconnection-escalate]" in content
    assert "data-loading-label=\"Escalating...\"" in content

    assert "[data-reconnection-abandon]" in content
    assert "data-loading-label=\"Marking abandoned...\"" in content

    assert "[data-starter-pack-enable]" in content
    assert "data-loading-label=\"Enabling starter pack...\"" in content

    assert "[data-starter-pack-replace]" in content
    assert "data-loading-label=\"Replacing drafts...\"" in content


def test_dashboard_js_uses_busy_state_helper_for_setup_actions():
    content = _read("app/static/js/dashboard.js")

    assert "function withBusy(button, callback)" in content
    assert "withBusy(setupVerifyButton" in content
    assert "withBusy(saveButton" in content
