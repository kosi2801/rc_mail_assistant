"""Structlog JSON logging configuration with secret redaction."""
import logging
import structlog

_REDACTED_KEYS = frozenset({"token", "secret", "password", "key", "credential", "auth"})


def _redact_secrets(logger, method, event_dict: dict) -> dict:
    """Remove any field whose name contains a sensitive keyword."""
    redacted = {
        k: "[REDACTED]" if any(s in k.lower() for s in _REDACTED_KEYS) else v
        for k, v in event_dict.items()
    }
    return redacted


def configure(service_name: str = "rc-mail-assistant") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
