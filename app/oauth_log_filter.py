"""Redact OAuth callback secrets from HTTP access logs."""

from __future__ import annotations

import logging
import re


_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:code|state|access_token|refresh_token|id_token|client_secret)=)[^&\s]+"
)


class OAuthQueryRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        redacted = _SENSITIVE_QUERY_VALUE.sub(r"\1[REDACTED]", rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True


def install_oauth_query_redaction_filter() -> None:
    logger = logging.getLogger("werkzeug")
    if not any(isinstance(item, OAuthQueryRedactionFilter) for item in logger.filters):
        logger.addFilter(OAuthQueryRedactionFilter())
