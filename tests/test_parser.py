"""Tests for Log Parser and Multiline Stack Trace Assembler."""

from logscope.models import SourceConfig, LogLevel
from logscope.ingestion.parser import LogParser, MultilineAssembler
from logscope.ingestion.tailer import FileTailer


def test_parse_json_log():
    cfg = SourceConfig(id="order-src", application="order-svc", environment="test", path="app.log", format="json")
    parser = LogParser(cfg)
    raw = '{"timestamp": "2026-08-10T14:10:00.000Z", "level": "ERROR", "message": "Failed charge", "code": 500}'
    event = parser.parse_record(raw, line_number=42)

    assert event.application == "order-svc"
    assert event.level == LogLevel.ERROR
    assert event.message == "Failed charge"
    assert event.timestamp is not None
    assert event.line_number == 42


def test_parse_standard_text_log():
    cfg = SourceConfig(id="auth-src", application="auth-svc", environment="test", path="auth.log")
    parser = LogParser(cfg)
    raw = '2026-08-10 14:00:01.120 [WARN] auth-svc: High memory usage threshold exceeded'
    event = parser.parse_record(raw, line_number=10)

    assert event.level == LogLevel.WARN
    assert "High memory usage" in event.message
    assert event.timestamp is not None


def test_multiline_assembler():
    assembler = MultilineAssembler()
    lines = [
        "2026-08-10 14:05:00 [ERROR] NullPointerException in payment service",
        "   at com.payment.service.Processor.execute(Processor.java:142)",
        "   at com.payment.service.PaymentHandler.handle(PaymentHandler.java:55)",
        "2026-08-10 14:05:05 [INFO] New request handled"
    ]

    res1 = assembler.add_line(lines[0], 1)
    assert res1 is None

    res2 = assembler.add_line(lines[1], 2)
    assert res2 is None

    res3 = assembler.add_line(lines[2], 3)
    assert res3 is None

    # Next timestamp line should flush previous multiline block
    res4 = assembler.add_line(lines[3], 4)
    assert res4 is not None
    assembled_text, start_line = res4
    assert "NullPointerException" in assembled_text
    assert "Processor.java:142" in assembled_text
    assert start_line == 1


def test_source_config_supports_documented_multiline_yaml_shape():
    cfg = SourceConfig(
        id="payment-src",
        application="payment",
        environment="production",
        path="payment.log",
        multiline={"pattern": r"^\\d{4}-\\d{2}-\\d{2}", "negate": True},
    )
    assert cfg.multiline_pattern == r"^\\d{4}-\\d{2}-\\d{2}"
    assert cfg.multiline_negate is True


def test_source_config_requires_application_and_environment():
    import pytest
    with pytest.raises(Exception):
        SourceConfig(id="missing-env", application="auth", path="auth.log")


def test_file_tailer_restores_checkpoint_state():
    cfg = SourceConfig(id="auth-src", application="auth", environment="test", path="auth.log")
    tailer = FileTailer(cfg)
    tailer.restore_checkpoint("auth.log", 64, 7)
    state = tailer.files_state[__import__("os").path.abspath("auth.log")]
    assert state.offset == 64
    assert state.line_number == 7
