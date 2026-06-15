"""Tests for the DB panel aggregator (N+1, slowest, callers)."""
from __future__ import annotations

from bs4 import BeautifulSoup

from symfony_profiler_client import DbPanel, analyze
from symfony_profiler_client.analyzer import normalise_sql, parse_ms


def test_parse_ms_handles_units():
    assert parse_ms("1.2 ms") == 1.2
    assert parse_ms("345 µs") == pytest_approx(0.345)
    assert parse_ms("2 s") == 2000
    assert parse_ms("") == 0.0
    assert parse_ms("nope") == 0.0


def pytest_approx(value):
    """Tiny local helper to avoid importing pytest for one assertion."""
    class _Approx:
        def __init__(self, v): self.v = v
        def __eq__(self, other): return abs(self.v - other) < 1e-6
        def __repr__(self): return f"~{self.v}"
    return _Approx(value)


def test_normalise_sql_strips_literals_and_numbers():
    a = normalise_sql("SELECT * FROM users WHERE id = 42 AND name = 'Ada'")
    b = normalise_sql("SELECT * FROM users WHERE id = 99 AND name = 'Bob'")
    assert a == b


def test_analyze_detects_n_plus_one(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    result = analyze(panel)
    # Two SELECTs of the same shape => 1 N+1 group with count=2
    assert len(result.n_plus_one) == 1
    assert result.n_plus_one[0]["count"] == 2
    assert result.n_plus_one[0]["total_ms"] > 0


def test_analyze_groups_sorted_by_total_time(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    result = analyze(panel)
    # groups are sorted by total_ms desc
    times = [g["total_ms"] for g in result.groups]
    assert times == sorted(times, reverse=True)


def test_analyze_callers_aggregate(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    result = analyze(panel)
    call_map = {c["call"]: c["count"] for c in result.callers}
    assert call_map["App\\Service\\UserService->getUser"] == 2
    assert call_map["App\\Service\\SessionService->touch"] == 1


def test_analyze_slowest_returns_top_10(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    result = analyze(panel)
    # 3 queries total — all 3 should appear, sorted by time desc
    assert len(result.slowest) == 3
    assert result.slowest[0]["n"] == 1  # 1.2 ms is the largest


def test_analyze_first_app_frames_have_host_paths(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    result = analyze(panel)
    assert len(result.first_app_frames) == 3
    for f in result.first_app_frames:
        assert f["host_path"] is not None
        assert f["host_path"].startswith("/home/me/myapp/")


def test_analyze_totals(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    result = analyze(panel)
    assert result.total == 3
    assert result.total_ms > 0
    assert result.token is None  # URL was "u" — no token in it
