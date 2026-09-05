"""AWS Lambda Forwarder for LogScope AI.

Subscribes to AWS CloudWatch Logs subscription filters, decompresses
the base64 gzip payload, and streams batches to LogScope AI's HTTP ingestion endpoint.

Zero external dependencies required (uses standard library urllib, gzip, base64).
"""

import base64
import gzip
import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration from Environment Variables
LOGSCOPE_ENDPOINT = os.getenv("LOGSCOPE_ENDPOINT", "http://localhost:8000/api/logs/ingest")
LOGSCOPE_API_KEY = os.getenv("LOGSCOPE_API_KEY", "")
LOGSCOPE_APP_NAME = os.getenv("LOGSCOPE_APP_NAME", "")  # Defaults to logGroup if empty
LOGSCOPE_ENV = os.getenv("LOGSCOPE_ENV", "production")
BATCH_TIMEOUT_SEC = int(os.getenv("BATCH_TIMEOUT_SEC", "10"))


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Processes CloudWatch logs subscription event."""
    try:
        raw_data = event.get("awslogs", {}).get("data")
        if not raw_data:
            logger.warning("Event did not contain awslogs.data payload")
            return {"status": "skipped", "reason": "empty_payload"}

        # 1. Base64 decode and gunzip CloudWatch log payload
        compressed_payload = base64.b64decode(raw_data)
        uncompressed_payload = gzip.decompress(compressed_payload)
        log_data = json.loads(uncompressed_payload.decode("utf-8"))

        log_group = log_data.get("logGroup", "unknown-loggroup")
        log_stream = log_data.get("logStream", "unknown-stream")
        log_events = log_data.get("logEvents", [])

        if not log_events:
            return {"status": "ok", "ingested": 0}

        # 2. Extract raw lines and timestamps
        app_name = LOGSCOPE_APP_NAME or log_group.replace("/", "-").strip("-")
        lines = []
        for item in log_events:
            msg = item.get("message", "")
            ts = item.get("timestamp")
            if msg:
                lines.append({"message": msg, "timestamp_ms": ts, "stream": log_stream})

        # 3. Construct payload for LogScope AI
        payload = {
            "application": app_name,
            "environment": LOGSCOPE_ENV,
            "source_name": f"cloudwatch:{log_group}",
            "logs": lines,
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            LOGSCOPE_ENDPOINT,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "LogScope-CloudWatch-Forwarder/1.0",
                **({"Authorization": f"Bearer {LOGSCOPE_API_KEY}"} if LOGSCOPE_API_KEY else {}),
            },
            method="POST",
        )

        ctx = ssl.create_default_context()
        if os.getenv("VERIFY_SSL", "true").lower() in ("false", "0"):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(req, timeout=BATCH_TIMEOUT_SEC, context=ctx) as resp:
            resp_code = resp.getcode()
            resp_body = resp.read().decode("utf-8")
            logger.info("Forwarded %d logs from %s to LogScope (status: %d)", len(lines), log_group, resp_code)
            return {
                "status": "success",
                "ingested": len(lines),
                "log_group": log_group,
                "remote_response": resp_body,
            }

    except urllib.error.HTTPError as e:
        err_msg = f"HTTP Error {e.code} posting to LogScope: {e.read().decode('utf-8', errors='ignore')}"
        logger.error(err_msg)
        raise RuntimeError(err_msg) from e
    except Exception as e:
        logger.error("Failed to forward CloudWatch logs: %s", str(e), exc_info=True)
        raise
