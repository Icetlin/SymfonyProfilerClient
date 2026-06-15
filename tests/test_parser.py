"""Tests for the DB panel parser."""
from __future__ import annotations

from bs4 import BeautifulSoup

from symfony_profiler_client import DbPanel


def test_db_panel_parses_three_queries(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup(
        "https://example.test/_profiler/abc?panel=db",
        soup,
        default_config,
    )
    assert len(panel.queries) == 3


def test_db_panel_extracts_sql(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    assert "SELECT * FROM users" in panel.queries[0]["sql"]
    assert "UPDATE sessions" in panel.queries[2]["sql"]


def test_db_panel_extracts_params(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    assert panel.queries[0]["params"] == ["42"]
    assert panel.queries[2]["params"] == ["2026-06-15 12:00:00", "sess-abc"]


def test_db_panel_extracts_explain_url(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    assert panel.queries[0]["explain_url"] is not None
    assert "page=explain" in panel.queries[0]["explain_url"]
    assert panel.queries[1]["explain_url"] is None


def test_db_panel_parses_backtraces(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    for q in panel.queries:
        assert len(q["backtrace"]) == 2


def test_db_panel_first_app_frame_skips_doctrine(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    f = panel.first_app_frame(panel.queries[0])
    assert f is not None
    assert f["class"] == "App\\Service\\UserService"
    assert f["method"] == "getUser"
    assert f["line"] == 54
    # host_path should be the local path, not the in-container one
    assert f["host_path"] == "/home/me/myapp/src/Service/UserService.php"
    assert "/var/www/html" not in (f["host_path"] or "")


def test_db_panel_first_app_frame_different_caller(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    f = panel.first_app_frame(panel.queries[2])
    assert f["class"] == "App\\Service\\SessionService"


def test_db_panel_by_number(db_panel_html, default_config):
    soup = BeautifulSoup(db_panel_html, "lxml")
    panel = DbPanel.from_soup("u", soup, default_config)
    assert panel.by_number(2) is not None
    assert panel.by_number(99) is None
