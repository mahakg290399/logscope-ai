"""Redactor and pseudonymizer for sensitive data in log streams.

This runs before Drain3 and Kafka ingestion.
Raw logs never cross into Kafka or AI prompts.
"""

import re
import hashlib
from typing import Any, Dict, Tuple, List, Optional

# Precompiled regex patterns for common sensitive values and tokens
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
IPV4_REGEX = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
IPV6_REGEX = re.compile(r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b')
UUID_REGEX = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
CREDIT_CARD_REGEX = re.compile(r'\b(?:\d{4}[- ]?){3}\d{4}\b')
JWT_REGEX = re.compile(r'\beyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*\b')
BEARER_TOKEN_REGEX = re.compile(r'(?i)\bBearer\s+([A-Za-z0-9\-_.~+/]+=*)')
API_KEY_PATTERNS = [
    re.compile(r'(?i)(?:api[_-]?key|apikey|secret|access[_-]?token|password|auth[_-]?token)\s*[:=]\s*["\']?([^"\'\s,;]+)["\']?'),
]
HEX_HASH_REGEX = re.compile(r'\b[0-9a-fA-F]{32,64}\b')
CLIENT_ID_KEYS = {"client_id", "clientid", "customer_id", "customerid", "account_id", "accountid"}
SAFE_METADATA_KEYS = {"service", "host", "hostname", "container", "request_id", "trace_id", "http_status", "status", "error_code"}


class Redactor:
    """Sanitizes raw log messages to remove PII, secrets, and transient IDs."""

    def __init__(self, salt: str = "logscope-salt"):
        self.salt = salt.encode("utf-8")

    def _pseudo_hash(self, prefix: str, val: str) -> str:
        """Generate a short stable pseudonym for correlation without revealing raw data."""
        h = hashlib.sha256(self.salt + val.encode("utf-8")).hexdigest()[:8]
        return f"<{prefix}:{h}>"

    def sanitize(self, text: str) -> Tuple[str, List[str]]:
        """Sanitizes sensitive tokens in text.
        
        Returns:
            Tuple[str, List[str]]: (sanitized_text, list_of_redacted_types)
        """
        redactions = []

        # Redact JWTs first (long string tokens)
        if "eyJ" in text:
            if JWT_REGEX.search(text):
                text = JWT_REGEX.sub("<JWT_TOKEN>", text)
                redactions.append("JWT")

        # Bearer tokens
        if "Bearer " in text or "bearer " in text:
            text = BEARER_TOKEN_REGEX.sub("Bearer <BEARER_TOKEN>", text)
            redactions.append("BEARER_TOKEN")

        # Key-value secrets (passwords, tokens, api keys)
        for pattern in API_KEY_PATTERNS:
            def _mask_kv(match):
                redactions.append("SECRET_KEY")
                return match.group(0).replace(match.group(1), "<REDACTED_SECRET>")
            text = pattern.sub(_mask_kv, text)

        # Credit cards
        if CREDIT_CARD_REGEX.search(text):
            text = CREDIT_CARD_REGEX.sub("<CARD_NUM>", text)
            redactions.append("CREDIT_CARD")

        # Emails
        if "@" in text and EMAIL_REGEX.search(text):
            text = EMAIL_REGEX.sub(lambda m: self._pseudo_hash("EMAIL", m.group(0)), text)
            redactions.append("EMAIL")

        # UUIDs
        if UUID_REGEX.search(text):
            text = UUID_REGEX.sub("<UUID>", text)
            redactions.append("UUID")

        # IP Addresses
        if IPV4_REGEX.search(text):
            text = IPV4_REGEX.sub(lambda m: self._pseudo_hash("IP", m.group(0)), text)
            redactions.append("IPV4")

        if IPV6_REGEX.search(text):
            text = IPV6_REGEX.sub("<IPV6>", text)
            redactions.append("IPV6")

        # Long Hex hashes (like git commits or sha256)
        if HEX_HASH_REGEX.search(text):
            text = HEX_HASH_REGEX.sub("<HEX_HASH>", text)
            redactions.append("HEX_HASH")

        return text, list(set(redactions))

    def pseudonymize_client_id(self, value: Any) -> Optional[str]:
        """Return the documented deterministic POC hash without retaining the raw identifier."""
        if value is None or str(value).strip() == "":
            return None
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    def sanitize_attributes(self, attributes: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
        """Keep only useful, non-raw metadata for Kafka and AI context."""
        safe: Dict[str, Any] = {}
        client_hash: Optional[str] = None
        for key, value in (attributes or {}).items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in CLIENT_ID_KEYS:
                client_hash = self.pseudonymize_client_id(value)
                continue
            if normalized in SAFE_METADATA_KEYS and value is not None:
                sanitized, _ = self.sanitize(str(value))
                safe[normalized] = sanitized
        return safe, client_hash

    @staticmethod
    def compute_sample_hash(text: str) -> str:
        """Compute stable hash of sanitized sample for deduplication and bounding."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
