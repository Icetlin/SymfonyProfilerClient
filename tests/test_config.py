"""Tests for config resolution and path normalisation."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from symfony_profiler_client.config import (
    DEFAULT_BASE,
    DEFAULT_TIMEOUT,
    ProfilerConfig,
    detect_host_prefix,
    normalise_container_path,
)


# ---- normalise_container_path ------------------------------------------------

def test_normalise_under_src_prefix():
    out = normalise_container_path(
        "/var/www/html/src/Service/Foo.php",
        src_prefix="/var/www/html",
        host_prefix="/home/me/myapp",
    )
    assert out == "/home/me/myapp/src/Service/Foo.php"


def test_normalise_already_local():
    out = normalise_container_path(
        "/home/me/myapp/src/Service/Foo.php",
        src_prefix="/var/www/html",
        host_prefix="/home/me/myapp",
    )
    assert out == "/home/me/myapp/src/Service/Foo.php"


def test_normalise_falls_back_to_common_paths():
    out = normalise_container_path(
        "/app/src/Service/Foo.php",
        src_prefix=None,
        host_prefix="/home/me/myapp",
    )
    assert out == "/home/me/myapp/src/Service/Foo.php"


def test_normalise_returns_original_when_nothing_matches():
    out = normalise_container_path(
        "/some/random/path/Foo.php",
        src_prefix=None,
        host_prefix="/home/me/myapp",
    )
    assert out == "/some/random/path/Foo.php"


def test_normalise_handles_none():
    assert normalise_container_path(None, src_prefix="/x", host_prefix="/y") is None


# ---- ProfilerConfig.from_sources: priority order ----------------------------

def test_config_cli_overrides_defaults():
    cfg = ProfilerConfig.from_sources(
        cli={"base": "https://cli.test"},
        env={},
    )
    assert cfg.base == "https://cli.test"


def test_config_env_overrides_defaults():
    cfg = ProfilerConfig.from_sources(
        cli={},
        env={"PROFILER_BASE": "https://env.test"},
    )
    assert cfg.base == "https://env.test"


def test_config_cli_overrides_env():
    cfg = ProfilerConfig.from_sources(
        cli={"base": "https://cli.test"},
        env={"PROFILER_BASE": "https://env.test"},
    )
    assert cfg.base == "https://cli.test"


def test_config_insecure_truthy_variants():
    for val in ("1", "true", "yes", "on", "TRUE"):
        cfg = ProfilerConfig.from_sources(cli={}, env={"PROFILER_INSECURE": val})
        assert cfg.insecure is True, val


def test_config_timeout_is_float():
    cfg = ProfilerConfig.from_sources(cli={}, env={"PROFILER_TIMEOUT": "12.5"})
    assert cfg.timeout == 12.5


def test_config_cookies_renamed_to_cookies_file():
    cfg = ProfilerConfig.from_sources(cli={}, env={"PROFILER_COOKIES": "/tmp/jar"})
    assert cfg.cookies_file == "/tmp/jar"


def test_config_default_timeout():
    cfg = ProfilerConfig.from_sources(cli={}, env={})
    assert cfg.timeout == DEFAULT_TIMEOUT


def test_config_default_base_is_local_dev():
    cfg = ProfilerConfig.from_sources(cli={}, env={}, auto_detect_host=False)
    assert cfg.base == DEFAULT_BASE
    assert cfg.base == "http://127.0.0.1:8000"


def test_config_explicit_config_file(tmp_path: Path):
    p = tmp_path / "myconfig.toml"
    p.write_text(
        "[profiler]\n"
        "base = 'https://file.test'\n"
        "host_prefix = '/host/myapp'\n",
        encoding="utf-8",
    )
    cfg = ProfilerConfig.from_sources(cli={}, env={}, config_file=p)
    assert cfg.base == "https://file.test"
    assert cfg.host_prefix == "/host/myapp"


def test_config_missing_explicit_file_raises(tmp_path: Path):
    p = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError):
        ProfilerConfig.from_sources(cli={}, env={}, config_file=p)


def test_config_file_via_env(tmp_path: Path, monkeypatch):
    p = tmp_path / "fromenv.toml"
    p.write_text("[profiler]\nbase = 'https://envfile.test'\n", encoding="utf-8")
    monkeypatch.setenv("PROFILER_CONFIG", str(p))
    cfg = ProfilerConfig.from_sources(cli={}, env=os.environ.copy())
    assert cfg.base == "https://envfile.test"


# ---- detect_host_prefix ------------------------------------------------------

def test_detect_finds_composer_in_parents(tmp_path: Path, monkeypatch):
    # Create a fake Symfony project: src/ + composer.json
    project = tmp_path / "myapp"
    (project / "src").mkdir(parents=True)
    (project / "composer.json").write_text("{}", encoding="utf-8")
    nested = project / "src" / "Service"
    nested.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(nested)
    found = detect_host_prefix()
    assert found == str(project.resolve())


def test_detect_returns_none_outside_project(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert detect_host_prefix() is None
