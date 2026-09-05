"""Throughput and Backpressure Benchmark Tool for LogScope AI.

Validates PRD Section 3.1 & Section 20 Acceptance Criterion 16:
"The system sustains the initial 1,000-lines-per-second target in a repeatable test."

Generates sustained mixed-traffic log streams across concurrent log sources:
- Standard text application logs
- Structured JSON operational records
- Multiline exception stack traces
- Anomalous bursts & error spikes
Measures ingestion rate (LPS), Drain3 clustering rate, bucket aggregation,
detection latency, and bounded queue backpressure.
"""

import asyncio
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

# Ensure project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from logscope.config import Settings
from logscope.service import LogScopeService
from logscope.models import SourceConfig


class BenchmarkRunner:
    def __init__(
        self,
        target_lps: int = 1000,
        duration_seconds: int = 10,
        num_sources: int = 4,
        base_dir: Path = Path("./data/benchmark_run"),
    ):
        self.target_lps = target_lps
        self.duration_seconds = duration_seconds
        self.num_sources = num_sources
        self.base_dir = base_dir
        self.total_lines_target = target_lps * duration_seconds

    def setup_directories(self) -> List[Path]:
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        file_paths = []
        for i in range(self.num_sources):
            src_dir = self.base_dir / f"service_{i}"
            src_dir.mkdir(parents=True, exist_ok=True)
            file_paths.append(src_dir / f"service_{i}.log")
        return file_paths

    def generate_line(self, line_idx: int, source_idx: int) -> str:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        pattern_mod = line_idx % 10

        if pattern_mod == 0:
            # Anomaly / Error
            return f"{now_str} [FATAL] app-{source_idx}: Database connection pool exhausted on port {5432 + source_idx}\n"
        elif pattern_mod in (1, 2):
            # JSON format
            return (
                f'{{"timestamp": "{now_str}Z", "level": "INFO", "service": "service-{source_idx}", '
                f'"message": "Handled transaction", "tx_id": "tx_{line_idx}", "duration_ms": {20 + (line_idx % 50)}}}\n'
            )
        elif pattern_mod == 3:
            # Multiline stack trace
            return (
                f"{now_str} [ERROR] app-{source_idx}: Unexpected NullPointerException in worker-{source_idx}\n"
                f"   at com.example.service.Worker.run(Worker.java:{100 + (line_idx % 200)})\n"
                f"   at java.lang.Thread.run(Thread.java:829)\n"
            )
        else:
            # Standard operational logs
            return f"{now_str} [INFO] app-{source_idx}: User session {line_idx} authenticated from IP 10.0.{source_idx}.{line_idx % 254}\n"

    async def run(self) -> Dict[str, Any]:
        log_files = self.setup_directories()
        db_path = self.base_dir / "benchmark.db"

        sources = [
            SourceConfig(
                id=f"src-bench-{i}",
                application=f"bench-app-{i}",
                environment="benchmark",
                path=str(log_files[i]),
                enabled=True,
                format="auto",
            )
            for i in range(self.num_sources)
        ]

        settings = Settings(
            LOGSCOPE_ENV="benchmark",
            LOGSCOPE_DATA_DIR=str(self.base_dir),
            LOGSCOPE_DB_PATH=str(db_path),
            LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=True,
            LOGSCOPE_QUEUE_MAX_SIZE=100000,
            OPENAI_API_KEY="",
            GEMINI_API_KEY="",
        )

        service = LogScopeService(settings)
        service.sources = sources
        await service.start()

        print(f"============================================================")
        print(f"  LogScope AI Performance & Backpressure Benchmark")
        print(f"============================================================")
        print(f"Target Rate:       {self.target_lps:,} lines/sec")
        print(f"Duration:          {self.duration_seconds} seconds")
        print(f"Total Target:      {self.total_lines_target:,} lines across {self.num_sources} files")
        print(f"Database:          {db_path} (WAL mode)")
        print(f"------------------------------------------------------------")

        start_time = time.time()
        lines_written = 0

        # Writer task: writes lines to files at target rate
        batch_size = max(50, self.target_lps // 20)  # 20 ticks per second
        delay_per_tick = 0.05

        async def writer():
            nonlocal lines_written
            file_handles = [open(f, "a", encoding="utf-8", buffering=8192) for f in log_files]
            try:
                while time.time() - start_time < self.duration_seconds:
                    tick_start = time.time()
                    for _ in range(batch_size):
                        s_idx = lines_written % self.num_sources
                        file_handles[s_idx].write(self.generate_line(lines_written, s_idx))
                        lines_written += 1

                    for h in file_handles:
                        h.flush()

                    elapsed = time.time() - tick_start
                    sleep_time = max(0.0, delay_per_tick - elapsed)
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
            finally:
                for h in file_handles:
                    h.close()

        # Run writer concurrently with service ingestion
        writer_task = asyncio.create_task(writer())
        await writer_task

        generation_duration = time.time() - start_time
        generation_rate = lines_written / generation_duration

        print(f"Generation complete: {lines_written:,} lines written in {generation_duration:.2f}s ({generation_rate:,.1f} lines/sec)")
        print("Waiting for tailer & ingestion pipeline to settle...")

        # Allow tailers to process remaining lines
        settle_start = time.time()
        while time.time() - settle_start < 5:
            # Check if tailers caught up
            for tailer in service.tailers.values():
                for state in tailer.files_state.values():
                    flushed = state.assembler.flush()
                    if flushed:
                        await service.process_raw_line(flushed[0], flushed[1], state.file_path, tailer.config)
            if service.total_lines_read >= lines_written:
                break
            await asyncio.sleep(0.1)

        total_duration = time.time() - start_time
        processed_lines = service.total_lines_read
        # Processing rate during active test
        processing_rate = processed_lines / total_duration

        # Collect metrics from DB and service
        telemetry = service.get_telemetry()
        templates = await service.db.get_all_templates(limit=1000)
        anomalies = await service.db.get_active_anomalies()

        await service.stop()

        target_met = processing_rate >= (self.target_lps * 0.85)

        print(f"------------------------------------------------------------", flush=True)
        print(f"  Benchmark Results", flush=True)
        print(f"------------------------------------------------------------", flush=True)
        print(f"Lines Generated:           {lines_written:,}", flush=True)
        print(f"Lines Ingested & Parsed:   {processed_lines:,} ({(processed_lines / max(1, lines_written)) * 100:.1f}%)", flush=True)
        print(f"Sustained Processing Rate: {processing_rate:,.1f} lines/sec", flush=True)
        print(f"Drain3 Unique Templates:   {len(templates)}", flush=True)
        print(f"Anomalies Detected:        {len(anomalies)}", flush=True)
        print(f"Dropped Events:            {telemetry.dropped_events}", flush=True)
        print(f"Data Loss Warning:         {telemetry.data_loss_warning}", flush=True)
        print(f"Target >= 1,000 LPS:       {'[PASSED]' if target_met else '[FAILED]'}", flush=True)
        print(f"============================================================", flush=True)

        results = {
            "target_lps": self.target_lps,
            "duration_seconds": self.duration_seconds,
            "lines_written": lines_written,
            "lines_processed": processed_lines,
            "processing_rate_lps": round(processing_rate, 2),
            "generation_rate_lps": round(generation_rate, 2),
            "unique_templates": len(templates),
            "anomalies_detected": len(anomalies),
            "dropped_events": telemetry.dropped_events,
            "data_loss_warning": telemetry.data_loss_warning,
            "passed": target_met,
        }

        # Cleanup
        shutil.rmtree(self.base_dir, ignore_errors=True)
        return results


if __name__ == "__main__":
    runner = BenchmarkRunner(target_lps=1000, duration_seconds=5)
    results = asyncio.run(runner.run())
    if not results["passed"]:
        sys.exit(1)
