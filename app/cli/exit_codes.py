"""Stable exit codes for openVC CLI.

Agents can rely on these codes to decide how to handle failures without
parsing error messages.  Mirror the pattern used by gogcli.

Usage:
    import sys
    from app.cli.exit_codes import EXIT_AUTH, OpenVCError, AuthError
    raise AuthError("API key is invalid or missing")
"""

# ── Exit code constants ────────────────────────────────────────────────────────

EXIT_OK          = 0    # Success
EXIT_ERROR       = 1    # Generic / unclassified error
EXIT_USAGE       = 2    # Bad CLI usage / argparse parse error
EXIT_EMPTY       = 3    # Operation succeeded but produced no output (0 segments, 0 clips)
EXIT_AUTH        = 4    # Authentication failure (invalid/missing API key)
EXIT_NOT_FOUND   = 5    # Input file, URL, or resource not found
EXIT_PERMISSION  = 6    # Permission denied (OS or API 403)
EXIT_RATE_LIMIT  = 7    # API rate limited / quota exceeded (429)
EXIT_RETRYABLE   = 8    # Transient error — network timeout, 5xx — safe to retry
EXIT_CONFIG      = 10   # Configuration error (bad config.json, missing required field)
EXIT_CANCELLED   = 130  # Cancelled by Ctrl-C (SIGINT)

# Human-readable descriptions (used by `openvc agent exit-codes`)
EXIT_CODE_TABLE = [
    (EXIT_OK,         "success",       "Operation completed successfully"),
    (EXIT_ERROR,      "error",         "Generic / unclassified error"),
    (EXIT_USAGE,      "usage_error",   "Bad CLI arguments or flag usage"),
    (EXIT_EMPTY,      "empty_results", "Succeeded but no output produced (0 segments, 0 clips)"),
    (EXIT_AUTH,       "auth_error",    "API key invalid, missing, or expired"),
    (EXIT_NOT_FOUND,  "not_found",     "Input file, URL, or resource does not exist"),
    (EXIT_PERMISSION, "permission",    "Permission denied (OS or API 403)"),
    (EXIT_RATE_LIMIT, "rate_limited",  "API rate limit or quota exceeded — back off and retry"),
    (EXIT_RETRYABLE,  "retryable",     "Transient error (timeout, 5xx) — safe to retry with backoff"),
    (EXIT_CONFIG,     "config_error",  "Configuration error in ~/.openvc/config.json"),
    (EXIT_CANCELLED,  "cancelled",     "Cancelled by keyboard interrupt (Ctrl-C)"),
]

# Lookup: slug → code
EXIT_CODE_BY_TYPE: dict = {slug: code for code, slug, _ in EXIT_CODE_TABLE}


# ── Typed exception hierarchy ─────────────────────────────────────────────────

class OpenVCError(Exception):
    """Base class for all openVC CLI errors.  Carries a stable exit code."""
    exit_code: int = EXIT_ERROR
    error_type: str = "error"

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause

    def to_dict(self) -> dict:
        return {
            "error": str(self),
            "exit_code": self.exit_code,
            "type": self.error_type,
        }


class UsageError(OpenVCError):
    exit_code = EXIT_USAGE
    error_type = "usage_error"


class EmptyResultsError(OpenVCError):
    exit_code = EXIT_EMPTY
    error_type = "empty_results"


class AuthError(OpenVCError):
    exit_code = EXIT_AUTH
    error_type = "auth_error"


class NotFoundError(OpenVCError):
    exit_code = EXIT_NOT_FOUND
    error_type = "not_found"


class PermissionError_(OpenVCError):  # avoids shadowing built-in
    exit_code = EXIT_PERMISSION
    error_type = "permission"


class RateLimitError(OpenVCError):
    exit_code = EXIT_RATE_LIMIT
    error_type = "rate_limited"


class RetryableError(OpenVCError):
    exit_code = EXIT_RETRYABLE
    error_type = "retryable"


class ConfigError(OpenVCError):
    exit_code = EXIT_CONFIG
    error_type = "config_error"


# ── Error classifier ──────────────────────────────────────────────────────────

def classify_exception(exc: Exception) -> OpenVCError:
    """Wrap an arbitrary exception in the most specific OpenVCError subclass.

    Inspects the message string for known API error patterns so that agents
    receive the correct exit code without special-casing individual libraries.
    """
    if isinstance(exc, OpenVCError):
        return exc

    msg = str(exc).lower()

    # Authentication / API key errors
    if any(k in msg for k in (
        "authentication", "invalid api key", "invalid_request_error",
        "401", "api key", "auth fail",
    )):
        return AuthError(str(exc), cause=exc)

    # Rate limiting
    if any(k in msg for k in (
        "rate limit", "ratelimit", "quota", "429", "too many requests",
        "resource_exhausted",
    )):
        return RateLimitError(str(exc), cause=exc)

    # Permission
    if any(k in msg for k in ("permission denied", "403", "forbidden")):
        return PermissionError_(str(exc), cause=exc)

    # Not found
    if any(k in msg for k in ("not found", "404", "no such file", "no matches")):
        return NotFoundError(str(exc), cause=exc)

    # Config
    if any(k in msg for k in ("config", "configuration", "missing required")):
        return ConfigError(str(exc), cause=exc)

    # Retryable network / server errors
    if any(k in msg for k in (
        "timeout", "timed out", "connection", "502", "503", "504",
        "server error", "temporary",
    )):
        return RetryableError(str(exc), cause=exc)

    return OpenVCError(str(exc), cause=exc)
