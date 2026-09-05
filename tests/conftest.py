"""Pytest configuration and shared fixtures."""

import os
import sys
from pathlib import Path
import pytest
import pytest_asyncio

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from logscope.config import Settings
from logscope.storage.db import Database
from logscope.storage.vector_index import LocalVectorIndex
from logscope.kafka.streaming import KafkaStreamManager


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        LOGSCOPE_ENV="test",
        LOGSCOPE_DATA_DIR=str(tmp_path),
        LOGSCOPE_DB_PATH=str(tmp_path / "test_logscope.db"),
        LOGSCOPE_KAFKA_EMBEDDED_FALLBACK=True,
        OPENAI_API_KEY=""  # Test with heuristic fallback
    )
    return settings


@pytest_asyncio.fixture
async def test_db(test_settings: Settings):
    db = Database(test_settings.db_path)
    await db.initialize()
    return db
