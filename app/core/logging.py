"""Logging setup with medical-data redaction.

Hard rule for this codebase: medical records, raw OCR text, document contents,
personal identifiers and secrets are never logged. The helpers here exist so
that accidental ``logger.info(..., extra=...)`` calls still get scrubbed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[redacted]"

_SENSITIVE_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|api[_-]?key|service[_-]?key|"
    r"ocr|raw[_-]?text|extracted[_-]?text|content|document[_-]?body|payload|"
    r"notes?|diagnos|medication|biomarker|lab[_-]?result|payload[_-]?json)",
    re.IGNORECASE,
)

_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(
    r"\b(password|secret|token|api[_-]?key)\s*[=:]\s*\S+", re.IGNORECASE
)


def redact_mapping(value: Any, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with sensitive values replaced.

    Used for both log extras and audit-log context, so that audit rows can be
    queried without ever storing clinical content.
    """
    if _depth > 6:
        return REDACTED
    if isinstance(value, dict):
        return {
            str(key): (REDACTED if _SENSITIVE_KEY_RE.search(str(key)) else redact_mapping(item, _depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_mapping(item, _depth + 1) for item in value]
    if isinstance(value, str) and len(value) > 512:
        # Long free text is almost certainly document/OCR content.
        return REDACTED
    return value


def redact_text(message: str) -> str:
    message = _BEARER_RE.sub(r"\1" + REDACTED, message)
    return _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", message)


class RedactingFilter(logging.Filter):
    """Scrubs bearer tokens and secret assignments out of log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = redact_text(rendered)
        record.args = ()
        if record.__dict__.get("extra_fields"):
            record.extra_fields = redact_mapping(record.extra_fields)
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(handler.filters[0], RedactingFilter) for handler in root.handlers if handler.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(RedactingFilter())
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Silence noisy libraries that can log request data at DEBUG level.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("python_multipart").setLevel(logging.WARNING)
