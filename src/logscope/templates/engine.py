"""Drain3 Template Mining Engine wrapper for LogScope AI."""

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.masking import MaskingInstruction
from logscope.models import TemplateRecord


class Drain3Engine:
    """Extracts and clusters log messages into robust templates using Drain3."""

    def __init__(self, persistence_file: Optional[Path] = None):
        config = TemplateMinerConfig()
        config.profiling_enabled = False
        config.drain_sim_th = 0.5  # Similarity threshold
        config.drain_depth = 4     # Tree depth
        
        # Configure masking instructions for Drain3 covering all common production log types
        config.masking_instructions = [
            # Sanitizer redaction tokens (normalize to clean labels)
            MaskingInstruction(r'<EMAIL:[^>]+>', 'EMAIL'),
            MaskingInstruction(r'<IP:[^>]+>', 'IP'),
            MaskingInstruction(r'<CARD_NUM>', 'CARD'),
            MaskingInstruction(r'<JWT_TOKEN>', 'JWT'),
            MaskingInstruction(r'<BEARER_TOKEN>', 'TOKEN'),
            MaskingInstruction(r'<REDACTED_SECRET>', 'SECRET'),
            MaskingInstruction(r'<UUID>', 'UUID'),
            MaskingInstruction(r'<IPV6>', 'IP'),
            MaskingInstruction(r'<HEX_HASH>', 'HASH'),

            # Standard Timestamps & Dates
            # 1. ISO-8601, RFC-3339, Bracketed datetime with optional timezone/subseconds
            MaskingInstruction(r'\[?\d{4}[-\/\.]\d{1,2}[-\/\.]\d{1,2}[T ]\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\]?', 'TIMESTAMP'),
            # 2. Apache / Nginx Common / Combined Log Format dates: [10/Oct/2000:13:55:36 -0700]
            MaskingInstruction(r'\[?\d{1,2}\/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\/\d{4}:\d{2}:\d{2}:\d{2}(?:\s+[+\-]\d{4})?\]?', 'TIMESTAMP'),
            # 3. Syslog timestamps: Sep  4 13:17:59 or [Sep 04 13:17:59.123]
            MaskingInstruction(r'\[?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?\]?', 'TIMESTAMP'),
            # 4. Standalone date: 2026-09-04 or 2026/09/04
            MaskingInstruction(r'\[?\b\d{4}[-\/\.]\d{1,2}[-\/\.]\d{1,2}\b\]?', 'TIMESTAMP'),
            # 5. Standalone time: 13:17:59 or 13:17:59.123
            MaskingInstruction(r'\[?\b\d{2}:\d{2}:\d{2}(?:[\.,]\d+)?\b\]?', 'TIMESTAMP'),

            # URLs / URIs (HTTP, HTTPS)
            MaskingInstruction(r'https?://[^\s"\'<>]+', 'URL'),

            # Network & Hardware Identifiers
            # MAC addresses: 00:1A:2B:3C:4D:5E or 00-1A-2B-3C-4D-5E
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)((?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})((?=[^A-Za-z0-9])|$)', 'MAC'),
            # IPv4 addresses (with optional port)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d{1,5})?)((?=[^A-Za-z0-9])|$)', 'IP'),
            # IPv6 addresses (full, compressed ::, and loopback ::1)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)((?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{1,4}|::1)((?=[^A-Za-z0-9])|$)', 'IP'),

            # System & Cryptographic Identifiers
            # Hex pointers / memory addresses: 0x7ffee4b2a890
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(0x[a-f0-9A-F]+)((?=[^A-Za-z0-9])|$)', 'HEX'),
            # UUID / GUID
            MaskingInstruction(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', 'UUID'),
            # Long hex hashes (git commit SHA, MD5, SHA-256)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)([0-9a-fA-F]{32,64})((?=[^A-Za-z0-9])|$)', 'HASH'),

            # Latency & Durations (e.g. 150ms, 2.5s, 30µs, 500ns, 12m)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(\d+(?:\.\d+)?\s*(?:µs|us|ns|ms|s|sec|min|m))((?=[^A-Za-z0-9])|$)', 'DURATION'),
            # Data Sizes / Bytes (e.g. 1024B, 4.5MB, 100KB, 2GB)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|TB|bytes|kb|mb|gb))((?=[^A-Za-z0-9])|$)', 'BYTES'),

            # File Paths (POSIX /var/log/... and Windows C:\...)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)(?:/(?:[a-zA-Z0-9_\.\-]+/)*[a-zA-Z0-9_\.\-]+|[a-zA-Z]:(?:\\[a-zA-Z0-9_\.\-]+)+)((?=[^A-Za-z0-9])|$)', 'PATH'),

            # Generic Numbers (floating point and integers)
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)([\-\+]?\d+\.\d+)((?=[^A-Za-z0-9])|$)', 'NUM'),
            MaskingInstruction(r'((?<=[^A-Za-z0-9])|^)([\-\+]?\d+)((?=[^A-Za-z0-9])|$)', 'NUM'),
        ]

        self.miner = TemplateMiner(config=config)
        self.persistence_file = persistence_file
        self._template_cache: Dict[str, str] = {}  # cluster_id -> template_id

    @staticmethod
    def generate_template_id(template_pattern: str, application: str = "", environment: str = "") -> str:
        """Generates a stable SHA-256 derived template ID."""
        key = f"{application}:{environment}:{template_pattern.strip()}"
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        return f"tmpl_{h}"

    def extract_template(self, sanitized_message: str, application: str = "", environment: str = "") -> Tuple[str, str, List[str], bool]:
        """Processes a sanitized message and returns (template_id, template_pattern, parameters, is_new).
        
        Returns:
            Tuple[str, str, List[str], bool]:
                - template_id: stable template hash
                - template_pattern: generalized template with wildcards
                - parameters: dynamic variable tokens extracted from message
                - is_new: whether this template was newly formed
        """
        # Drain3 processes single-line patterns best, so strip extra internal newlines
        first_line = sanitized_message.split("\n")[0].strip()
        result = self.miner.add_log_message(first_line)
        
        template_pattern = result.get("template_mined", first_line)
        cluster_id = result.get("cluster_id", 0)
        change_type = result.get("change_type", "none")
        is_new = change_type == "cluster_created"

        template_id = self.generate_template_id(template_pattern, application, environment)

        # Extract parameters using miner with non-backtracking parameter extraction
        params = []
        try:
            matched_template = self.miner.match(first_line)
            if matched_template:
                params = self.miner.extract_parameters(template_pattern, first_line, exact_matching=False) or []
        except Exception:
            params = []

        return template_id, template_pattern, [str(p) for p in params], is_new

