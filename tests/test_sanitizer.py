"""Tests for the Redactor and Pseudonymizer."""

from logscope.sanitizer import Redactor


def test_sanitize_emails():
    redactor = Redactor(salt="test-salt")
    text = "User alert sent to alice@example.com and bob.smith@corp.co.uk"
    sanitized, tags = redactor.sanitize(text)
    assert "alice@example.com" not in sanitized
    assert "bob.smith@corp.co.uk" not in sanitized
    assert "<EMAIL:" in sanitized
    assert "EMAIL" in tags


def test_sanitize_ips():
    redactor = Redactor()
    text = "Inbound connection from 192.168.1.100 to port 8080"
    sanitized, tags = redactor.sanitize(text)
    assert "192.168.1.100" not in sanitized
    assert "<IP:" in sanitized
    assert "IPV4" in tags


def test_sanitize_secrets_and_bearer():
    redactor = Redactor()
    text = 'Failed auth: api_key="sk_live_secret12345" and Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeak'
    sanitized, tags = redactor.sanitize(text)
    assert "sk_live_secret12345" not in sanitized
    assert "eyJhbGciOiJIUzI1NiJ9" not in sanitized
    assert "<REDACTED_SECRET>" in sanitized
    assert "<BEARER_TOKEN>" in sanitized or "<JWT_TOKEN>" in sanitized


def test_sanitize_credit_card_and_uuid():
    redactor = Redactor()
    text = "Payment card 4111-2222-3333-4444 for account 123e4567-e89b-12d3-a456-426614174000"
    sanitized, tags = redactor.sanitize(text)
    assert "4111-2222-3333-4444" not in sanitized
    assert "123e4567-e89b-12d3-a456-426614174000" not in sanitized
    assert "<CARD_NUM>" in sanitized
    assert "<UUID>" in sanitized
