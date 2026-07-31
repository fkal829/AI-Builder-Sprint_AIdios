import logging
import re
from typing import Any

PUBLIC_TOKEN_REDACTION = "[REDACTED]"

_PUBLIC_TOKEN_PATH_PATTERN = re.compile(
    r"(?P<prefix>/(?:[^/?#\s]+/)*(?:"
    r"public/(?:adjustment-requests|obligations)|_mock/storage"
    r")/)"
    r"(?P<token>[^/?#\s]+)"
)
_FILTER_MARKER = "_ansim_public_token_path_filter"


def redact_public_token_paths(value: str) -> str:
    """Redact public and mock-storage tokens embedded in API paths."""

    return _PUBLIC_TOKEN_PATH_PATTERN.sub(
        rf"\g<prefix>{PUBLIC_TOKEN_REDACTION}",
        value,
    )


class PublicTokenPathFilter(logging.Filter):
    """Remove public tokens before Uvicorn formats an access-log record."""

    _ansim_public_token_path_filter = True

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_public_token_paths(record.msg)
        record.args = _redact_log_value(record.args)
        return True


def install_uvicorn_access_log_filter() -> None:
    """Install the public-token filter once on Uvicorn's access logger."""

    access_logger = logging.getLogger("uvicorn.access")
    if any(getattr(item, _FILTER_MARKER, False) for item in access_logger.filters):
        return
    access_logger.addFilter(PublicTokenPathFilter())


def _redact_log_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_public_token_paths(value)
    if isinstance(value, tuple):
        return tuple(_redact_log_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_log_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_log_value(item) for key, item in value.items()}
    return value
