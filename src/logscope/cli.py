"""CLI runner and entrypoint for LogScope AI."""

import argparse
import sys
import uvicorn
from logscope.config import get_settings
from logscope.api.app import create_app


def main():
    parser = argparse.ArgumentParser(description="LogScope AI - Enterprise SRE Log Aggregator & Incident Triager")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--env", default="development", help="Environment (development/production)")
    parser.add_argument("--sources", default="sources.yaml", help="Path to sources configuration YAML")
    parser.add_argument("--generate-test-logs", action="store_true", help="Generate simulated log traffic for testing")

    args = parser.parse_args()

    settings = get_settings()
    settings.host = args.host
    settings.port = args.port

    app = create_app(settings)
    print(f"\n🚀 Starting LogScope AI POC v2.0 on http://{args.host}:{args.port}")
    print(f"📁 SQLite WAL database: {settings.db_path}")
    print(f"📊 Dashboard available at: http://{args.host}:{args.port}/\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
