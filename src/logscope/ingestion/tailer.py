"""Non-blocking File Tailer for LogScope AI."""

import asyncio
import glob
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, AsyncGenerator
from logscope.models import SourceConfig
from logscope.ingestion.parser import MultilineAssembler, LogParser


class FileTailState:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.offset = 0
        self.line_number = 0
        self.assembler = MultilineAssembler()
        self.file_identity: Optional[Tuple[int, int]] = None


class FileTailer:
    """Tails active and globbed log files non-blockingly."""

    def __init__(self, source_config: SourceConfig):
        self.config = source_config
        self.parser = LogParser(source_config)
        self.files_state: Dict[str, FileTailState] = {}
        self.is_running = False
        self.error_count = 0

    def restore_checkpoint(self, file_path: str, offset: int, line_number: int) -> None:
        """Restore a persisted position before the file is tailed again."""
        path = os.path.abspath(file_path)
        state = self.files_state.setdefault(path, self._new_state(path))
        state.offset = max(0, offset)
        state.line_number = max(0, line_number)

    def _new_state(self, path: str) -> FileTailState:
        state = FileTailState(path)
        state.assembler = MultilineAssembler(
            start_pattern=self.config.multiline_pattern,
            negate=self.config.multiline_negate,
        )
        return state

    @staticmethod
    def _identity(path: str) -> Tuple[int, int]:
        stat = os.stat(path)
        return stat.st_dev, stat.st_ino

    def discover_files(self) -> List[str]:
        """Expands glob pattern to discover existing matching files."""
        matched = glob.glob(self.config.path, recursive=True)
        return [os.path.abspath(p) for p in matched if os.path.isfile(p)]

    async def read_new_lines(self) -> AsyncGenerator[Tuple[str, int, str], None]:
        """Polls files for new lines and yields (assembled_line, start_line_num, file_path)."""
        active_files = self.discover_files()

        # Handle empty/missing path gracefully
        if not active_files and os.path.exists(self.config.path) and os.path.isfile(self.config.path):
            active_files = [os.path.abspath(self.config.path)]

        for path in active_files:
            if path not in self.files_state:
                self.files_state[path] = self._new_state(path)

            state = self.files_state[path]

            try:
                if not os.path.exists(path):
                    continue

                curr_size = os.path.getsize(path)
                identity = self._identity(path)
                # Detect replacement/rotation even if the replacement file is
                # larger than the previous file, then handle truncation.
                if state.file_identity is not None and identity != state.file_identity:
                    state.offset = 0
                    state.line_number = 0
                state.file_identity = identity
                if curr_size < state.offset:
                    # File was truncated/rotated
                    state.offset = 0
                    state.line_number = 0

                if curr_size == state.offset:
                    continue  # No new data

                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(state.offset)
                    while True:
                        line = f.readline()
                        if not line:
                            break
                        state.line_number += 1
                        # Remove trailing newline for assembler
                        line_stripped = line.rstrip("\r\n")
                        assembled = state.assembler.add_line(line_stripped, state.line_number)
                        if assembled:
                            yield assembled[0], assembled[1], path
                    state.offset = f.tell()

            except Exception:
                # Keep tailer resilient to file I/O locks on Windows. The
                # service records this as a parsing/source warning.
                self.error_count += 1
                continue
