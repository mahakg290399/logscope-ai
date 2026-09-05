"""Small realistic workload that continuously emits application logs for the demo."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.getenv("DEMO_LOG_DIR", "/var/log/demo"))
SERVICES = ("auth-service", "payment-api", "order-service")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()


def emit(step: int) -> None:
    now = timestamp()
    user_id = f"usr_{random.randint(1000, 9999)}"
    order_id = f"ord_{random.randint(10000, 99999)}"
    amount = random.randint(20, 500)

    write_line(
        LOG_DIR / "auth-service" / "auth.log",
        f"{now} [INFO] auth-service: login succeeded user_id={user_id} ip=10.0.4.{random.randint(2, 240)}",
    )
    write_line(
        LOG_DIR / "payment-api" / "app.log",
        f"{now} [INFO] payment-api: payment authorized order_id={order_id} amount={amount} currency=USD",
    )
    write_line(
        LOG_DIR / "order-service" / "order.log",
        json.dumps({"timestamp": now, "level": "INFO", "service": "order-service", "message": "Order processed", "order_id": order_id, "amount": amount}),
    )

    # Periodic failures create useful anomaly and AI-triage events without random gibberish.
    if step % 15 == 0:
        write_line(LOG_DIR / "payment-api" / "app.log", f"{now} [ERROR] payment-api: upstream gateway timeout order_id={order_id} retry_in_ms=500")
    if step % 31 == 0:
        write_line(LOG_DIR / "auth-service" / "auth.log", f"{now} [WARN] auth-service: elevated login failures region=us-east-1 failure_rate=0.27")
    if step % 47 == 0:
        write_line(LOG_DIR / "order-service" / "order.log", json.dumps({"timestamp": now, "level": "ERROR", "service": "order-service", "message": "database connection pool exhausted", "retryable": True}))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.info("demo workload started; writing logs to %s", LOG_DIR)
    step = 0
    while True:
        step += 1
        emit(step)
        time.sleep(2)


if __name__ == "__main__":
    main()
