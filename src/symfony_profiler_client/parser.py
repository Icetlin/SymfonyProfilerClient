"""
HTML parsing for the Profiler DB panel.

The DB panel renders one ``<tr id="queryNo-CONN-N">`` per query with three
cells: display number, time, and (SQL + Parameters + hidden backtrace).

We extract:

    - normalised SQL
    - execution time as a string (e.g. "1.2 ms", "345 micros")
    - bound parameters
    - Explain link (if present)
    - backtrace as a list of frames (see :mod:`backtrace`)

The :class:`DbPanel` class bundles the results and adds derived views:
first-app-frame, slowest, callers, N+1 groups.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .backtrace import parse_hidden_block
from .config import ProfilerConfig, normalise_container_path
from .exceptions import ProfilerParseError

_QUERY_ROW_RE = re.compile(r"^queryNo-")
_PARAMS_RE = re.compile(r"Parameters\s*[:：]\s*\[(.+?)\]\s*$", re.S)


def _parse_params(cell_text: str) -> list[str]:
    m = _PARAMS_RE.search(cell_text.strip())
    if not m:
        return []
    raw = m.group(1)
    # Naive split - values can contain commas, but the Profiler escapes
    # them with quotes; for diagnostics this is "good enough" and matches
    # the original behaviour.
    return [p.strip() for p in raw.split(",") if p.strip()]


def _parse_query_row(tr: Any) -> dict[str, Any] | None:
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 3:
        return None

    try:
        n = int(tds[0].get_text(" ", strip=True))
    except ValueError:
        return None

    time_text = tds[1].get_text(" ", strip=True)
    sql_cell = tds[2]

    sql_pre = sql_cell.find("pre", class_=re.compile(r"highlight.*sql", re.I))
    sql = sql_pre.get_text(" ", strip=True) if sql_pre else sql_cell.get_text(" ", strip=True)[:300]

    # Parameters may sit in a <div> next to the <pre>. Pull from the cell text.
    params: list[str] = []
    for div in sql_cell.find_all("div"):
        txt = div.get_text(" ", strip=True)
        if txt.startswith("Parameters") or txt.startswith("Parameters :"):
            params = _parse_params(txt)
            break

    # Explain link
    explain_url: str | None = None
    for a in sql_cell.find_all("a", href=True):
        if "page=explain" in a["href"]:
            explain_url = a["href"]
            break

    # Backtrace: pick the hidden div that actually contains one
    backtrace: list[dict[str, Any]] = []
    for hd in sql_cell.find_all("div", class_="hidden"):
        bt = parse_hidden_block(hd)
        if bt:
            backtrace = bt
            break

    return {
        "n": n,
        "id": tr.get("id"),
        "sql": sql,
        "time": time_text,
        "params": params,
        "explain_url": explain_url,
        "backtrace": backtrace,
    }


@dataclass
class DbPanel:
    """Parsed DB panel - list of queries plus derived analysis."""
    url: str
    config: ProfilerConfig
    queries: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_soup(cls, url: str, soup: Any, config: ProfilerConfig) -> "DbPanel":
        queries: list[dict[str, Any]] = []
        for tr in soup.find_all("tr", id=_QUERY_ROW_RE):
            parsed = _parse_query_row(tr)
            if parsed is not None:
                queries.append(parsed)
        return cls(url=url, config=config, queries=queries)

    # ----- derived views -----------------------------------------------

    def first_app_frame(self, q: dict[str, Any]) -> dict[str, Any] | None:
        """First frame that isn't a framework / vendor frame."""
        skip = self.config.skip_prefixes
        for f in q.get("backtrace", []):
            cls = f.get("class") or ""
            file = f.get("file") or ""
            if not cls or not file:
                continue
            if any(cls.startswith(p) for p in skip):
                continue
            if "vendor/" in file:
                continue
            return {**f, "host_path": self._host_path(file)}
        # Fallback: first frame that has class+file even if it is vendor.
        for f in q.get("backtrace", []):
            if f.get("class") and f.get("file"):
                return {**f, "host_path": self._host_path(f["file"])}
        return None

    def _host_path(self, file_path: str | None) -> str | None:
        return normalise_container_path(
            file_path,
            src_prefix=self.config.src_prefix,
            host_prefix=self.config.host_prefix,
        )

    # ----- raw accessors used by the CLI / analysis --------------------

    def by_number(self, n: int) -> dict[str, Any] | None:
        return next((q for q in self.queries if q["n"] == n), None)
