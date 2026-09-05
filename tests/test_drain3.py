"""Tests for Drain3 Template Clustering Engine."""

from logscope.templates.engine import Drain3Engine


def test_drain3_clustering():
    engine = Drain3Engine()

    msg1 = "User login successful for account_id=10049 from IP <IP:1a2b3c4d>"
    tmpl_id1, pattern1, params1, is_new1 = engine.extract_template(msg1, "auth", "prod")

    assert is_new1 is True
    assert tmpl_id1.startswith("tmpl_")

    msg2 = "User login successful for account_id=10050 from IP <IP:9e8d7c6b>"
    tmpl_id2, pattern2, params2, is_new2 = engine.extract_template(msg2, "auth", "prod")

    # Should map to the same template cluster
    assert tmpl_id1 == tmpl_id2
    assert is_new2 is False


def test_drain3_timestamp_masking():
    engine = Drain3Engine()

    msg1 = "2026-09-04 12:34:56.789 [INFO] auth-service: User login successful for account_id=10049 from IP 192.168.1.1"
    _, pattern1, _, _ = engine.extract_template(msg1, "auth", "prod")

    assert "<TIMESTAMP>" in pattern1
    assert "<<NUM>>" not in pattern1
    assert "<NUM>" in pattern1
    assert "<IP>" in pattern1


def test_drain3_common_log_types_masking():
    """Verify Drain3 properly masks all common production log formats out of the box."""
    engine = Drain3Engine()

    # 1. Apache / Common Log Format with duration and bytes
    msg_clf = "[10/Oct/2000:13:55:36 -0700] GET /api/v1/orders/8849 HTTP/1.1 200 in 45.2ms bytes 1024KB"
    _, p_clf, _, _ = engine.extract_template(msg_clf, "web", "prod")
    assert "<TIMESTAMP>" in p_clf
    assert "<DURATION>" in p_clf
    assert "<BYTES>" in p_clf
    assert "<PATH>" in p_clf

    # 2. Syslog with network MAC address & IPv6
    msg_sys = "Sep  4 13:17:59 host-01 kernel: eth0: link up, MAC 00:1a:2b:3c:4d:5e to fe80::1ff:fe23:4567:890a"
    _, p_sys, _, _ = engine.extract_template(msg_sys, "kernel", "prod")
    assert "<TIMESTAMP>" in p_sys
    assert "<MAC>" in p_sys
    assert "<IP>" in p_sys

    # 3. URL, UUID, POSIX file path
    msg_url = "13:17:59.004 [ERROR] Request failed to https://api.stripe.com/v1/charges with uuid 550e8400-e29b-41d4-a716-446655440000 at /var/log/app.log"
    _, p_url, _, _ = engine.extract_template(msg_url, "billing", "prod")
    assert "<TIMESTAMP>" in p_url
    assert "<URL>" in p_url
    assert "<UUID>" in p_url
    assert "<PATH>" in p_url

    # 4. Hex memory address & cryptographic hash
    msg_hex = "Fault at address 0x7ffee4b2a890 with hash e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    _, p_hex, _, _ = engine.extract_template(msg_hex, "app", "prod")
    assert "<HEX>" in p_hex
    assert "<HASH>" in p_hex

    # 5. Sanitizer tokens
    msg_san = "audit user=<EMAIL:a1b2c3d4> ip=<IP:e5f6g7h8> jwt=<JWT_TOKEN> secret=<REDACTED_SECRET>"
    _, p_san, _, _ = engine.extract_template(msg_san, "audit", "prod")
    assert "<EMAIL>" in p_san
    assert "<IP>" in p_san
    assert "<JWT>" in p_san
    assert "<SECRET>" in p_san


