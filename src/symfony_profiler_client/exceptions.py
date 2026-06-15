"""Exceptions for symfony-profiler-client."""
from __future__ import annotations


class ProfilerError(Exception):
    """Base class for all profiler-client errors."""


class ProfilerConfigError(ProfilerError):
    """Configuration is missing or invalid (e.g. base URL not set)."""


class ProfilerHTTPError(ProfilerError):
    """Wraps a transport-level failure (DNS, TLS, HTTP status)."""
    def __init__(self, message: str, *, status: int | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.url = url


class ProfilerParseError(ProfilerError):
    """The HTML response was not a Profiler page we could parse."""
