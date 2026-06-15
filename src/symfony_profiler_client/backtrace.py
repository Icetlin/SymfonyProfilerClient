"""
Backtrace parsing.

The Symfony Profiler DB panel renders each query's call stack as a hidden
HTML block. There are two layouts we support:

    A) <table> with <thead># / File/Call</thead> — modern profiler
    B) <ol><li>... — older profiler versions

Each frame is normalised to a small dict with ``class``, ``method``, ``line``,
``file`` (in-container path), ``file_url`` (file://…#L42), and convenience
flags ``is_vendor`` and ``is_src``.

The parser never raises on individual rows — bad rows are skipped, the
rest of the backtrace is returned.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import Tag

# Recognise cell text like "Vendor\\Ns\\Foo->bar (line 42)".
_FRAME_RE = re.compile(
    r"^(?P<cls>.+?)->\s*(?P<meth>\w+)\s*\(line\s+(?P<ln>\d+)\)\s*$"
)


def _normalise_frame(n: int, cell: Tag) -> dict[str, Any]:
    """Parse one row of the modern table layout."""
    anchor = cell.find("a")
    file_url = anchor.get("href") if anchor else None
    file_path: str | None = None
    if file_url and file_url.startswith("file://"):
        # file:///var/www/html/vendor/foo/File.php#L36 → /var/www/.../File.php
        file_path = file_url[7:].split("#", 1)[0]

    cell_text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
    m = _FRAME_RE.match(cell_text)
    if m:
        cls_name = m.group("cls")
        method = m.group("meth")
        line_no = int(m.group("ln"))
    else:
        cls_name = method = None
        line_no = None

    return {
        "n": n,
        "class": cls_name,
        "method": method,
        "call": f"{cls_name}->{method}" if cls_name and method else cell_text,
        "line": line_no,
        "file": file_path,
        "file_url": file_url,
        "is_vendor": bool(file_path and "vendor/" in file_path),
        "is_src": bool(file_path and "/src/" in file_path),
    }


def _parse_modern_table(tbl: Tag) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    body = tbl.find("tbody") or tbl
    for tr in body.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        try:
            n = int(tds[0].get_text(strip=True))
        except ValueError:
            n = 0
        frames.append(_normalise_frame(n, tds[1]))
    return frames


def _parse_legacy_ol(ol: Tag) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for li in ol.find_all("li", recursive=False):
        n = 0
        for a in li.find_all("a", recursive=False):
            txt = a.get_text(strip=True)
            if txt.isdigit():
                n = int(txt)
                break
        pre = li.find("pre")
        call_text = pre.get_text("\n", strip=False) if pre else ""
        call_text = re.sub(r"->\s*\n\s*", "->", call_text)
        call_text = re.sub(r"\s+", " ", call_text).strip()
        m = re.match(r"^(.+?)->(\w+)\s*\(line\s+(\d+)\)\s*$", call_text)
        cls_name = method = None
        line_no = None
        if m:
            cls_name, method, line_no = m.group(1), m.group(2), int(m.group(3))
        frames.append({
            "n": n,
            "class": cls_name,
            "method": method,
            "call": call_text,
            "line": line_no,
            "file": None,
            "file_url": None,
            "is_vendor": False,
            "is_src": False,
        })
    return frames


def parse_hidden_block(hidden: Tag) -> list[dict[str, Any]]:
    """Parse a single ``<div class="hidden">`` containing a backtrace."""
    tbl = hidden.find("table")
    if tbl:
        head_text = (
            tbl.find("thead").get_text(" ", strip=True)
            if tbl.find("thead")
            else tbl.get_text(" ", strip=True)[:50]
        )
        if "File/Call" in head_text or "File / Call" in head_text:
            return _parse_modern_table(tbl)
    ol = hidden.find("ol")
    if ol:
        return _parse_legacy_ol(ol)
    return []


# Expose for tests without breaking encapsulation.
_FRAME_RE_FOR_TESTS = _FRAME_RE
