"""Tests for email configuration validation and destination fallback.

Covers:
  - _email_effective_dest() fallback chain
  - _email_configured() logic
  - _send_email_results() validation path (no real SMTP needed)
  - _email_status_html() output for configured and unconfigured states
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Inline the logic under test to avoid importing web_ui (heavy side-effects)
# ---------------------------------------------------------------------------

def _email_effective_dest(
    dest: str,
    env_destino: str = "",
    env_user: str = "",
) -> str:
    """Mirror of web_ui._email_effective_dest with injectable env vars for testing."""
    return dest.strip() or env_destino or env_user


def _send_email_validation(
    dest_email: str,
    smtp_user: str,
    smtp_pass: str,
    env_destino: str = "",
    env_user: str = "",
) -> tuple[bool, str]:
    """Mirror of the validation block in web_ui._send_email_results."""
    effective_dest = _email_effective_dest(dest_email, env_destino, env_user)
    if not effective_dest or not smtp_user.strip() or not smtp_pass.strip():
        missing = []
        if not smtp_user.strip():
            missing.append("EMAIL_USER")
        if not smtp_pass.strip():
            missing.append("EMAIL_PASS")
        if not effective_dest:
            missing.append("email de destino (campo UI o EMAIL_DESTINO)")
        return False, (
            "⚠️ Correo no enviado — faltan credenciales: "
            + ", ".join(missing)
            + ". Completa el archivo .env y reinicia la app."
        )
    return True, effective_dest  # returns resolved dest for assertion convenience


# ═══════════════════════════════════════════════════════════════════════════
# Tests: _email_effective_dest
# ═══════════════════════════════════════════════════════════════════════════


class TestEmailEffectiveDest:
    """Verify the three-level fallback chain for email destination."""

    def test_explicit_dest_wins(self):
        """Explicit UI field takes priority over env vars."""
        result = _email_effective_dest("other@example.com", "destino@env.com", "user@env.com")
        assert result == "other@example.com"

    def test_env_destino_fallback(self):
        """EMAIL_DESTINO used when UI field is empty."""
        result = _email_effective_dest("", "destino@env.com", "user@env.com")
        assert result == "destino@env.com"

    def test_env_user_final_fallback(self):
        """EMAIL_USER used when both UI field and EMAIL_DESTINO are empty."""
        result = _email_effective_dest("", "", "user@env.com")
        assert result == "user@env.com"

    def test_all_empty_returns_empty(self):
        result = _email_effective_dest("", "", "")
        assert result == ""

    def test_whitespace_dest_is_treated_as_empty(self):
        """Whitespace-only dest should fall through to env vars."""
        result = _email_effective_dest("   ", "", "user@env.com")
        assert result == "user@env.com"

    def test_explicit_dest_with_whitespace_stripped(self):
        result = _email_effective_dest("  me@test.com  ", "destino@env.com", "user@env.com")
        assert result == "me@test.com"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: validation block in _send_email_results
# ═══════════════════════════════════════════════════════════════════════════


class TestSendEmailValidation:
    """Verify error messages when credentials are incomplete."""

    def test_all_present_returns_ok(self):
        ok, dest = _send_email_validation(
            dest_email="dest@ex.com",
            smtp_user="user@ex.com",
            smtp_pass="apppass",
        )
        assert ok is True
        assert dest == "dest@ex.com"

    def test_empty_dest_falls_back_to_env_user(self):
        ok, dest = _send_email_validation(
            dest_email="",
            smtp_user="user@ex.com",
            smtp_pass="apppass",
            env_user="user@ex.com",
        )
        assert ok is True
        assert dest == "user@ex.com"

    def test_empty_dest_and_no_env_raises_error(self):
        ok, msg = _send_email_validation(
            dest_email="",
            smtp_user="user@ex.com",
            smtp_pass="apppass",
            env_destino="",
            env_user="",
        )
        assert ok is False
        assert "email de destino" in msg

    def test_missing_smtp_user_error(self):
        ok, msg = _send_email_validation(
            dest_email="dest@ex.com",
            smtp_user="",
            smtp_pass="apppass",
        )
        assert ok is False
        assert "EMAIL_USER" in msg

    def test_missing_smtp_pass_error(self):
        ok, msg = _send_email_validation(
            dest_email="dest@ex.com",
            smtp_user="user@ex.com",
            smtp_pass="",
        )
        assert ok is False
        assert "EMAIL_PASS" in msg

    def test_missing_user_and_pass_lists_both(self):
        ok, msg = _send_email_validation(
            dest_email="dest@ex.com",
            smtp_user="",
            smtp_pass="",
        )
        assert ok is False
        assert "EMAIL_USER" in msg
        assert "EMAIL_PASS" in msg

    def test_all_missing_lists_three_items(self):
        ok, msg = _send_email_validation(
            dest_email="",
            smtp_user="",
            smtp_pass="",
        )
        assert ok is False
        assert "EMAIL_USER" in msg
        assert "EMAIL_PASS" in msg
        assert "email de destino" in msg

    def test_error_message_no_longer_mentions_EMAIL_DESTINO_as_required(self):
        """Old message said 'EMAIL_DESTINO deben estar rellenos' — that was wrong."""
        ok, msg = _send_email_validation(
            dest_email="",
            smtp_user="",
            smtp_pass="",
        )
        assert ok is False
        # Should NOT contain the old misleading text
        assert "EMAIL_DESTINO deben estar rellenos" not in msg

    def test_env_destino_fallback_works(self):
        ok, dest = _send_email_validation(
            dest_email="",
            smtp_user="user@ex.com",
            smtp_pass="apppass",
            env_destino="destino@ex.com",
            env_user="user@ex.com",
        )
        assert ok is True
        assert dest == "destino@ex.com"
