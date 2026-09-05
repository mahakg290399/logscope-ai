"""Log Parser and Multiline Stack Trace Assembler for LogScope AI."""

import json
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Generator, Tuple
from logscope.models import ParsedLogEvent, LogLevel, SourceConfig

# Common timestamp regexes
ISO8601_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?')
COMMON_LOG_DATE = re.compile(r'^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}')
BRACKET_DATE = re.compile(r'^\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]')

# Precompiled log level lookup map
LOG_LEVEL_ALIASES: Dict[str, LogLevel] = {
    "TRACE": LogLevel.TRACE,
    "DEBUG": LogLevel.DEBUG,
    "INFO": LogLevel.INFO,
    "WARN": LogLevel.WARN,
    "WARNING": LogLevel.WARN,
    "ERR": LogLevel.ERROR,
    "ERROR": LogLevel.ERROR,
    "CRIT": LogLevel.CRITICAL,
    "CRITICAL": LogLevel.CRITICAL,
    "FATAL": LogLevel.FATAL,
}

COMMON_TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
)

LOG_LEVEL_PATTERN = re.compile(r'\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\b', re.IGNORECASE)


class MultilineAssembler:
    """Buffers lines until a new record start is detected, assembling multiline logs."""


    def __init__(self, start_pattern: Optional[str] = None, negate: bool = True):
        self.pattern = re.compile(start_pattern) if start_pattern else None
        self.negate = negate  # If negate=True, lines that DON'T match start_pattern are continuation lines
        self.buffered_lines: list[str] = []
        self.start_line_num: Optional[int] = None

    def is_new_entry(self, line: str) -> bool:
        """Determines if the given line starts a new log entry."""
        if not self.pattern:
            # Default heuristic: begins with timestamp or JSON '{' or bracketed level
            trimmed = line.strip()
            if trimmed.startswith('{') and trimmed.endswith('}'):
                return True
            if ISO8601_PATTERN.match(line) or COMMON_LOG_DATE.match(line) or BRACKET_DATE.match(line):
                return True
            # Stack trace continuation lines usually start with 'at ', 'Caused by:', or leading whitespace
            if line.startswith(' ') or line.startswith('\t') or line.startswith('   at ') or line.startswith('Caused by:'):
                return False
            return True

        matches = bool(self.pattern.search(line))
        return matches if not self.negate else not matches

    def add_line(self, line: str, line_num: int) -> Optional[Tuple[str, int]]:
        """Add line to assembler.
        
        Returns:
            Optional[Tuple[str, int]]: Completed multiline payload and start line number if flushed.
        """
        if self.is_new_entry(line) and self.buffered_lines:
            # Flush existing buffer
            full_msg = "\n".join(self.buffered_lines)
            start_num = self.start_line_num or line_num
            self.buffered_lines = [line]
            self.start_line_num = line_num
            return full_msg, start_num

        if not self.buffered_lines:
            self.start_line_num = line_num
        self.buffered_lines.append(line)
        return None

    def flush(self) -> Optional[Tuple[str, int]]:
        """Flush remaining buffered lines at EOF."""
        if self.buffered_lines:
            full_msg = "\n".join(self.buffered_lines)
            start_num = self.start_line_num or 1
            self.buffered_lines = []
            self.start_line_num = None
            return full_msg, start_num
        return None


class LogParser:
    """Parses raw text or JSON log records into normalized ParsedLogEvent."""

    def __init__(self, source_config: Optional[SourceConfig] = None):
        self.config = source_config or SourceConfig(
            id="default",
            application="default",
            environment="default",
            path="auto",
        )

    def _parse_timestamp(self, raw_str: str) -> Optional[datetime]:
        """Tries fast fromisoformat first, falling back to common timestamp patterns."""
        if not raw_str:
            return None

        clean_str = raw_str.strip().strip("[]()")

        # Try fast native fromisoformat (Python 3.11+)
        try:
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass

        # Fallback to configured common formats
        for fmt in COMMON_TIMESTAMP_FORMATS:
            try:
                dt = datetime.strptime(clean_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        return None

    @staticmethod
    def _parse_level(level_str: Optional[str]) -> LogLevel:
        """Parses a log level using precomputed aliases lookup table."""
        if not level_str:
            return LogLevel.UNKNOWN
        return LOG_LEVEL_ALIASES.get(level_str.strip().upper(), LogLevel.UNKNOWN)


    def parse_record(self, raw_line: str, line_number: Optional[int] = None, file_path: Optional[str] = None) -> ParsedLogEvent:
        """Parses a log record into a structured ParsedLogEvent."""
        file_path = file_path or self.config.path
        raw_stripped = raw_line.strip()

        # 1. Try JSON parsing
        if self.config.format == "json" or (raw_stripped.startswith("{") and raw_stripped.endswith("}")):
            try:
                data = json.loads(raw_stripped)
                if isinstance(data, dict):
                    # Extract timestamp
                    ts_val = data.get("timestamp") or data.get("time") or data.get("@timestamp") or data.get("ts")
                    parsed_ts = self._parse_timestamp(str(ts_val)) if ts_val else None

                    # Extract level
                    lvl_val = data.get("level") or data.get("severity") or data.get("log_level") or data.get("lvl")
                    level = self._parse_level(str(lvl_val)) if lvl_val else LogLevel.UNKNOWN

                    # Extract message
                    msg = data.get("message") or data.get("msg") or data.get("error") or raw_stripped

                    return ParsedLogEvent(
                        raw_line=raw_line,
                        timestamp=parsed_ts,
                        level=level,
                        message=str(msg),
                        source_path=file_path,
                        line_number=line_number,
                        source_id=self.config.id,
                        application=self.config.application,
                        environment=self.config.environment,
                        attributes=data
                    )
            except Exception:
                pass  # Fallback to standard text parsing

        # 2. Standard unstructured / text parsing
        parsed_ts = None
        level = LogLevel.UNKNOWN
        msg = raw_line

        # Try to find timestamp at start of line
        match_iso = ISO8601_PATTERN.match(raw_line)
        if match_iso:
            parsed_ts = self._parse_timestamp(match_iso.group(0))
            remainder = raw_line[match_iso.end():].strip()
        else:
            match_bracket = BRACKET_DATE.match(raw_line)
            if match_bracket:
                parsed_ts = self._parse_timestamp(match_bracket.group(1))
                remainder = raw_line[match_bracket.end():].strip()
            else:
                remainder = raw_line

        # Try to extract log level
        level_match = LOG_LEVEL_PATTERN.search(remainder)
        if level_match:
            level = self._parse_level(level_match.group(1))

        return ParsedLogEvent(
            raw_line=raw_line,
            timestamp=parsed_ts,
            level=level,
            message=raw_line.strip(),
            source_path=file_path,
            line_number=line_number,
            source_id=self.config.id,
            application=self.config.application,
            environment=self.config.environment,
            attributes={}
        )
