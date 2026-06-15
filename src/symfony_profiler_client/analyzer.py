"""
Aggregated analysis of a DB panel.

Given a :class:`DbPanel`, produce:

    * ``groups``  - every unique normalised SQL with count and total time
    * ``n_plus_one`` - groups with count > 1, sorted by total time desc
    * ``callers`` - top call sites by query count
    * ``slowest`` - top-10 individual queries by execution time
    * ``first_app_frames`` - first non-framework frame per query

All times are in milliseconds (floats). The input ``time`` strings are
parsed with a permissive regex that handles "1.2 ms", "345 micros", "0.005 s".
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .parser import DbPanel


_TIME_RE = re.compile(r"([\d.]+)\s*(ms|s|µs|us)?", re.I)


def parse_ms(t: str) -> float:
    """Parse a Profiler-style time string into milliseconds."""
    if not t:
        return 0.0
    m = _TIME_RE.match(t.strip())
    if not m:
        return 0.0
    v = float(m.group(1))
    u = (m.group(2) or "ms").lower()
    if u == "s":
        return v * 1000
    if u in ("µs", "us"):
        return v / 1000
    return v


def normalise_sql(sql: str) -> str:
    """
    Strip literals and numbers from a query so structurally identical
    queries (the N+1 hallmark) collapse into a single key.
    """
    s = re.sub(r"'[^']*'", "''", sql)
    s = re.sub(r"\b\d+\b", "N", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass
class DbAnalysis:
    """Aggregated analysis of a DB panel - produced by :func:`analyze`."""
    url: str
    token: str | None
    total: int
    total_ms: float
    groups: list[dict[str, Any]] = field(default_factory=list)
    n_plus_one: list[dict[str, Any]] = field(default_factory=list)
    callers: list[dict[str, Any]] = field(default_factory=list)
    slowest: list[dict[str, Any]] = field(default_factory=list)
    first_app_frames: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # Rename `queries` -> `query_numbers` for cleaner JSON output.
        groups = []
        for g in self.groups:
            g2 = dict(g)
            if "queries" in g2:
                g2["query_numbers"] = g2.pop("queries")
            groups.append(g2)
        return {
            "url": self.url,
            "token": self.token,
            "total": self.total,
            "total_ms": self.total_ms,
            "groups": groups,
            "n_plus_one": self.n_plus_one,
            "callers": self.callers,
            "slowest": self.slowest,
            "first_app_frames": self.first_app_frames,
        }


def analyze(panel: DbPanel) -> DbAnalysis:
    """Run the full analysis pipeline on a parsed DB panel."""
    queries = panel.queries

    # --- groups (with N+1 baked in) -----------------------------------
    groups: dict[str, dict[str, Any]] = {}
    for q in queries:
        key = normalise_sql(q["sql"])
        g = groups.setdefault(key, {
            "count": 0,
            "total_ms": 0.0,
            "queries": [],
            "sample_sql": q["sql"],
        })
        g["count"] += 1
        g["total_ms"] += parse_ms(q["time"])
        g["queries"].append(q["n"])
    groups_list = sorted(groups.values(), key=lambda g: -g["total_ms"])
    n_plus_one = [g for g in groups_list if g["count"] > 1]

    # --- callers ------------------------------------------------------
    callers: Counter[str] = Counter()
    caller_groups: dict[str, list[int]] = {}
    for q in queries:
        f = panel.first_app_frame(q)
        if f and f.get("class"):
            call = f"{f['class']}->{f.get('method', '?')}"
            callers[call] += 1
            caller_groups.setdefault(call, []).append(q["n"])

    # --- slowest ------------------------------------------------------
    slowest = sorted(queries, key=lambda q: -parse_ms(q["time"]))[:10]
    slowest_view = [
        {"n": q["n"], "time": q["time"], "sql": q["sql"]}
        for q in slowest
    ]

    # --- first app frames --------------------------------------------
    first_app: list[dict[str, Any]] = []
    for q in queries:
        f = panel.first_app_frame(q)
        if f:
            first_app.append({
                "n": q["n"],
                "time": q["time"],
                "class": f.get("class"),
                "method": f.get("method"),
                "file": f.get("file"),
                "host_path": f.get("host_path"),
                "line": f.get("line"),
            })
    first_app.sort(key=lambda x: -parse_ms(x["time"]))

    # --- token --------------------------------------------------------
    m = re.search(r"/_profiler/([0-9a-f]+)", panel.url)
    token = m.group(1) if m else None

    return DbAnalysis(
        url=panel.url,
        token=token,
        total=len(queries),
        total_ms=sum(parse_ms(q["time"]) for q in queries),
        groups=groups_list,
        n_plus_one=n_plus_one,
        callers=[
            {"call": c, "count": n, "queries": caller_groups[c]}
            for c, n in callers.most_common()
        ],
        slowest=slowest_view,
        first_app_frames=first_app,
    )
