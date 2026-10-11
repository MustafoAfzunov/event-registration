"""Keep capability tokens out of logs (docs/REVIEW.md H2).

The manage token in /api/registrations/<token> and /r/<token> is a participant's credential
(view ticket, cancel). Uvicorn's access log prints the full path; this filter rewrites it to
/api/registrations/[redacted] so the access log stays useful without leaking the token."""

import logging
import re

_TOKEN_IN_PATH = re.compile(r"(/api/registrations/|/r/)[A-Za-z0-9_-]{16,}")


def redact(value: str) -> str:
    return _TOKEN_IN_PATH.sub(r"\1[redacted]", value)


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def install() -> None:
    """Idempotent. Called when the app is created, i.e. after uvicorn configured logging."""
    for name in ("uvicorn.access", "uvicorn.error"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokens) for f in logger.filters):
            logger.addFilter(RedactTokens())
