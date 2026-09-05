"""Unit tests for AWS CloudWatch Lambda forwarder (Interface 3)."""

import base64
import gzip
import json
import unittest.mock
import pytest

from deploy.cloudwatch.lambda_function import lambda_handler


def _build_mock_cloudwatch_event(log_group: str, log_stream: str, messages: list[str]) -> dict:
    """Builds a realistic AWS CloudWatch Subscription Filter event."""
    log_events = [
        {"id": f"evt-{idx}", "timestamp": 1700000000000 + idx, "message": msg}
        for idx, msg in enumerate(messages)
    ]
    raw_payload = {
        "messageType": "DATA_MESSAGE",
        "owner": "123456789012",
        "logGroup": log_group,
        "logStream": log_stream,
        "subscriptionFilters": ["LogScopeFilter"],
        "logEvents": log_events,
    }
    json_bytes = json.dumps(raw_payload).encode("utf-8")
    compressed = gzip.compress(json_bytes)
    b64_data = base64.b64encode(compressed).decode("utf-8")
    return {"awslogs": {"data": b64_data}}


def test_cloudwatch_lambda_forwarding():
    """Verify Lambda handler decompresses and formats CloudWatch logs properly."""
    event = _build_mock_cloudwatch_event(
        log_group="/aws/eks/cart-service",
        log_stream="cart-pod-abc",
        messages=[
            "2026-09-05 12:00:00 [ERROR] Out of memory error in checkout",
            "2026-09-05 12:00:01 [INFO] Worker restarting",
        ],
    )

    with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = unittest.mock.MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b'{"status":"accepted","ingested":2}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = lambda_handler(event, None)

        assert result["status"] == "success"
        assert result["ingested"] == 2
        assert result["log_group"] == "/aws/eks/cart-service"

        # Check urllib request payload
        assert mock_urlopen.call_count == 1
        req_obj = mock_urlopen.call_args[0][0]
        posted_data = json.loads(req_obj.data.decode("utf-8"))
        assert posted_data["application"] == "aws-eks-cart-service"
        assert posted_data["environment"] == "production"
        assert len(posted_data["logs"]) == 2
        assert posted_data["logs"][0]["message"] == "2026-09-05 12:00:00 [ERROR] Out of memory error in checkout"
