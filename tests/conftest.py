"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

from symfony_profiler_client import ProfilerConfig


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_panel_html() -> str:
    return (FIXTURES_DIR / "db_panel_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def default_config() -> ProfilerConfig:
    """A config with host_prefix pointing at a non-existent path,
    so path-translation tests are deterministic."""
    return ProfilerConfig(
        base="https://example.test",
        host_prefix="/home/me/myapp",
        src_prefix="/var/www/html",
        skip_prefixes=("Doctrine\\", "Symfony\\", "PDO", "Propel"),
    )
