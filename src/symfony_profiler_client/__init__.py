"""
symfony-profiler-client
=======================

A small, dependency-light Python CLI and library for talking to the
Symfony WebProfilerBundle. Fetches tokens, lists panels, walks the DB
panel, parses SQL backtraces, and surfaces N+1 / slowest / caller
aggregations in a format that's easy to pipe to ``jq`` or feed to an
LLM.

Public surface:

    >>> from symfony_profiler_client import ProfilerConfig, ProfilerClient
    >>> cfg = ProfilerConfig.from_sources(cli={"base": "https://example.test"})
    >>> client = ProfilerClient(cfg)
    >>> html = client.fetch(client.url("bc65af", panel="db"))

There is also a CLI installed as the ``profiler`` console script:

    profiler info bc65af
    profiler db-analyze bc65af
"""
from __future__ import annotations

__version__ = "1.0.0"

__all__ = [
    "ProfilerClient",
    "ProfilerConfig",
    "ParsedProfiler",
    "DbPanel",
    "DbAnalysis",
    "analyze",
    "parse_ms",
    "normalise_sql",
    "normalise_container_path",
    "detect_host_prefix",
    "ProfilerError",
    "ProfilerConfigError",
    "ProfilerHTTPError",
    "ProfilerParseError",
    "__version__",
]


def __getattr__(name: str):  # PEP 562 lazy attribute access
    if name in {"ProfilerClient", "ParsedProfiler"}:
        from .client import ProfilerClient, ParsedProfiler
        return {"ProfilerClient": ProfilerClient, "ParsedProfiler": ParsedProfiler}[name]
    if name == "ProfilerConfig":
        from .config import ProfilerConfig
        return ProfilerConfig
    if name in {"normalise_container_path", "detect_host_prefix"}:
        from .config import normalise_container_path, detect_host_prefix
        return {"normalise_container_path": normalise_container_path,
                "detect_host_prefix": detect_host_prefix}[name]
    if name in {"DbPanel"}:
        from .parser import DbPanel
        return DbPanel
    if name in {"DbAnalysis", "analyze", "parse_ms", "normalise_sql"}:
        from .analyzer import DbAnalysis, analyze, parse_ms, normalise_sql
        return {"DbAnalysis": DbAnalysis, "analyze": analyze,
                "parse_ms": parse_ms, "normalise_sql": normalise_sql}[name]
    if name in {"ProfilerError", "ProfilerConfigError", "ProfilerHTTPError", "ProfilerParseError"}:
        from .exceptions import (
            ProfilerError, ProfilerConfigError, ProfilerHTTPError, ProfilerParseError,
        )
        return {
            "ProfilerError": ProfilerError,
            "ProfilerConfigError": ProfilerConfigError,
            "ProfilerHTTPError": ProfilerHTTPError,
            "ProfilerParseError": ProfilerParseError,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
