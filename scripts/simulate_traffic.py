"""Log Simulator for LogScope AI demo and testing.

Generates steady baseline traffic with intermittent spikes, new templates, and errors.
"""

import os
import time
import random
from pathlib import Path
from datetime import datetime, timezone

LOGS_DIR = Path("./logs")
AUTH_DIR = LOGS_DIR / "auth-service"
PAYMENT_DIR = LOGS_DIR / "payment-api"
ORDER_DIR = LOGS_DIR / "order-service"


def ensure_dirs():
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    PAYMENT_DIR.mkdir(parents=True, exist_ok=True)
    ORDER_DIR.mkdir(parents=True, exist_ok=True)


def simulate():
    ensure_dirs()
    auth_file = AUTH_DIR / "auth.log"
    payment_file = PAYMENT_DIR / "app.log"
    order_file = ORDER_DIR / "order.log"

    print("🚀 Simulating realistic log streams into ./logs/...")
    print("Press Ctrl+C to stop simulation.")

    step = 0
    while True:
        step += 1
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # 1. Normal Auth traffic
        account_id = random.randint(1000, 9999)
        ip = f"192.168.{random.randint(1, 10)}.{random.randint(2, 254)}"
        with open(auth_file, "a", encoding="utf-8") as f:
            f.write(f"{now_str} [INFO] auth-service: User login successful for account_id={account_id} from IP {ip}\n")
            f.write(f"{now_str} [DEBUG] auth-service: Session token refreshed for session_id=sess_{random.randint(10000, 99999)}\n")

        # 2. Order service JSON logs
        with open(order_file, "a", encoding="utf-8") as f:
            f.write(f'{{"timestamp": "{now_str}Z", "level": "INFO", "service": "order-service", "message": "Order processed", "order_id": "ord_{random.randint(1000, 9999)}", "amount": {random.randint(20, 500)}}}\n')

        # 3. Simulate intermittent anomalies every 10 steps
        if step % 8 == 0:
            print(f"[{now_str}] ⚠️ Injecting anomalous error burst into payment-api and auth-service...")
            with open(payment_file, "a", encoding="utf-8") as f:
                for _ in range(6):
                    f.write(f"{now_str} [ERROR] payment-api: Database connection pool exhausted for customer_id={random.randint(1000, 9999)}\n")
                    f.write("   at com.payment.service.Processor.connect(Processor.java:142)\n")
                    f.write("   at com.payment.service.PaymentHandler.handle(PaymentHandler.java:55)\n")
            
            with open(auth_file, "a", encoding="utf-8") as f:
                f.write(f"{now_str} [FATAL] auth-service: Outage: Primary token validator unreachable with secret api_key=\"sk_live_private_test\"\n")

        time.sleep(1.0)


if __name__ == "__main__":
    simulate()
