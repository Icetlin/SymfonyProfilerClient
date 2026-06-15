"""
Command-line interface for symfony-profiler-client.

Subcommands (all take a Profiler token as the first positional argument
unless noted):

    info      - summary: status, method, url, time, ...
    panels    - list panels available for a token
    panel     - open a specific panel (raw HTML by default)
    db        - DB panel: list of queries
    db-queries
              - same as 'db --json'
    db-query  - open query N (sql + params + backtrace)
    db-trace  - full backtrace for one query N (with local paths)
    db-traces - all backtraces for all queries (single JSON; LLM-friendly)
    db-hotspots
              - aggregated N+1 + callers + slowest (JSON)
    db-analyze
              - full DB panel analysis (N+1 + callers + slowest + frames)
    search    - grep across panels
    fetch     - fetch arbitrary URL (token + panel + type + query), save to file
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from typing import Any

import requests
from bs4 import BeautifulSoup

from .analyzer import analyze
from .client import ParsedProfiler, ProfilerClient
from .config import (
    DEFAULT_BASE,
    DEFAULT_TIMEOUT,
    ProfilerConfig,
    default_config_path,
)
from .exceptions import ProfilerError
from .formatting import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW, cprint, fmt_table
from .parser import DbPanel


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser with all subcommands."""
    p = argparse.ArgumentParser(
        prog="profiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(__doc__ or ""),
    )
    p.add_argument(
        "-u", "--base",
        help=(
            f"Base URL of the Symfony app (default: {DEFAULT_BASE} — "
            "overridden by PROFILER_BASE env or config.toml)"
        ),
    )
    p.add_argument(
        "-c", "--cookies",
        help="Path to a Netscape cookie jar (curl --cookie-jar style)",
    )
    p.add_argument(
        "-H", "--header",
        action="append",
        default=None,
        help="Extra header 'K: V' (repeatable)",
    )
    p.add_argument("--bearer", help="Bearer token (Authorization header)")
    p.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS verification (also: PROFILER_INSECURE=1)",
    )
    p.add_argument(
        "--src-prefix",
        help="In-container path prefix; auto-detected via common paths if unset",
    )
    p.add_argument(
        "--host-prefix",
        help="Local path prefix for file:// URLs in backtraces "
             "(auto-detected from cwd/git toplevel if unset)",
    )
    p.add_argument(
        "--config",
        help="Path to a TOML config file (default: "
             f"{default_config_path() or '$XDG_CONFIG_HOME/.../config.toml'})",
    )
    p.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    p.add_argument(
        "--json", action="store_true",
        help="JSON output where applicable",
    )

    sub = p.add_subparsers(dest="cmd", required=True, metavar="CMD")

    def add_token_cmd(name: str, help_: str, **extra: Any) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_, **extra)
        sp.add_argument("token", help="Profiler token (the part after /_profiler/)")
        return sp

    sp = add_token_cmd("info", "summary: status, method, url, time, ...")
    sp.set_defaults(func=cmd_info)

    sp = add_token_cmd("panels", "list panels for a token")
    sp.set_defaults(func=cmd_panels)

    sp = sub.add_parser("panel", help="open a specific panel (raw HTML by default)")
    sp.add_argument("token")
    sp.add_argument("name", help="panel name, e.g. db, request, time, twig")
    sp.add_argument("--type", help="subtype filter (e.g. request/insert/update for db)")
    sp.add_argument("--query", type=int, help="query N (db panel)")
    sp.add_argument("--save", help="write HTML to file instead of stdout")
    sp.set_defaults(func=cmd_panel)

    sp = sub.add_parser("db", help="DB panel: list of queries")
    sp.add_argument("token")
    sp.add_argument("--type", help="filter: request/insert/update/remove")
    sp.set_defaults(func=cmd_db)

    sp = sub.add_parser("db-queries", help="same as 'db --json'")
    sp.add_argument("token")
    sp.add_argument("--type")
    sp.set_defaults(func=cmd_db_queries)

    sp = sub.add_parser("db-query", help="DB panel: open query N (sql + backtrace)")
    sp.add_argument("token")
    sp.add_argument("n", type=int, help="query number (1-based)")
    sp.add_argument("--max-frames", type=int, default=30)
    sp.add_argument("--type", help="filter by query type")
    sp.set_defaults(func=cmd_db_query)

    sp = sub.add_parser("db-trace", help="full backtrace for one query N (with local paths)")
    sp.add_argument("token")
    sp.add_argument("n", type=int, help="query number")
    sp.add_argument("--max-frames", type=int, default=50)
    sp.set_defaults(func=cmd_db_trace)

    sp = sub.add_parser("db-traces", help="all backtraces for all queries in one JSON")
    sp.add_argument("token")
    sp.add_argument("--type", help="filter by query type")
    sp.add_argument("--only-with-trace", action="store_true")
    sp.set_defaults(func=cmd_db_traces)

    sp = sub.add_parser("db-hotspots", help="aggregated N+1 + callers + slowest (JSON)")
    sp.add_argument("token")
    sp.set_defaults(func=cmd_db_hotspots)

    sp = sub.add_parser("db-analyze", help="full DB panel analysis (N+1 + callers + slowest + frames)")
    sp.add_argument("token")
    sp.add_argument("--type", help="filter by query type")
    sp.add_argument("--top", type=int, default=10)
    sp.set_defaults(func=cmd_db_analyze)

    sp = sub.add_parser("search", help="grep across panels")
    sp.add_argument("token")
    sp.add_argument("pattern", help="regex (case-insensitive)")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="fetch arbitrary URL (token + panel + type + query)")
    sp.add_argument("token")
    sp.add_argument("--panel")
    sp.add_argument("--type")
    sp.add_argument("--query", type=int)
    sp.add_argument("--save", help="save HTML to file")
    sp.set_defaults(func=cmd_fetch)

    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_config(args: argparse.Namespace) -> ProfilerConfig:
    """Build a ProfilerConfig from CLI args, env, config file, auto-detect."""
    cli: dict[str, Any] = {
        "base": args.base,
        "cookies_file": args.cookies,
        "bearer": args.bearer,
        "src_prefix": args.src_prefix,
        "host_prefix": args.host_prefix,
        "insecure": args.insecure if getattr(args, "insecure", False) else None,
        "timeout": args.timeout if args.timeout != DEFAULT_TIMEOUT else None,
    }
    if getattr(args, "header", None):
        cli["extra_headers"] = args.header

    return ProfilerConfig.from_sources(
        cli=cli,
        config_file=args.config,
        auto_detect_host=True,
    )


def _make_client(cfg: ProfilerConfig) -> ProfilerClient:
    return ProfilerClient(cfg)


def _fetch_soup(client: ProfilerClient, token: str, **kwargs: Any) -> ParsedProfiler:
    url = client.url(token, **kwargs)
    html = client.fetch(url)
    return ParsedProfiler(url=url, html=html, soup=BeautifulSoup(html, "lxml"), config=client.config)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_info(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    client = _make_client(cfg)
    parsed = _fetch_soup(client, args.token)
    summary = parsed.summary_dict()
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    cprint(f"{BOLD}Profiler token:{RESET} {parsed.token()}", CYAN)
    cprint(f"{BOLD}URL:{RESET}           {parsed.url}")
    for k, v in summary.items():
        if k in ("url", "token"):
            continue
        cprint(f"{BOLD}{k}:{RESET}        {v}")
    return 0


def cmd_panels(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    client = _make_client(cfg)
    parsed = _fetch_soup(client, args.token)
    nav = parsed.panel_nav()
    if args.json:
        print(json.dumps(nav, indent=2, ensure_ascii=False))
        return 0
    if not nav:
        cprint(f"{YELLOW}No panels found (page is not a profile summary?). URL: {parsed.url}{RESET}")
        return 1
    cprint(f"{BOLD}Panels on token {parsed.token()}:{RESET}", CYAN)
    for p in nav:
        marker = f" ({p['count']})" if p.get("count") is not None else ""
        cprint(f"  • {BOLD}{p['panel']:<14}{RESET} {p['label']}{DIM}{marker}{RESET}")
    return 0


def cmd_panel(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    client = _make_client(cfg)
    parsed = _fetch_soup(client, args.token, panel=args.name, type_=args.type, query=args.query)
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(parsed.html)
        cprint(f"saved → {args.save}", GREEN)
        return 0
    if args.json:
        print(json.dumps({
            "url": parsed.url,
            "title": (parsed.soup.title.string if parsed.soup.title else None),
            "header_rows": parsed.header_rows(),
            "links_count": len(parsed.soup.find_all("a")),
            "panels": parsed.panel_nav(),
        }, indent=2, ensure_ascii=False))
        return 0
    cprint(
        f"{BOLD}Panel {args.name}"
        f"{f' / {args.type}' if args.type else ''}"
        f"{f' / query {args.query}' if args.query is not None else ''}{RESET}",
        CYAN,
    )
    cprint(f"URL: {parsed.url}")
    rows = parsed.header_rows()
    if rows:
        cprint(f"\n{BOLD}Header rows:{RESET}")
        for r in rows[:30]:
            cprint(f"  {r['key']:<22} {r['value']}")
    return 0


def _load_db_panel(args: argparse.Namespace) -> DbPanel:
    cfg = _resolve_config(args)
    client = _make_client(cfg)
    type_ = getattr(args, "type", None)
    parsed = _fetch_soup(client, args.token, panel="db", type_=type_)
    return DbPanel.from_soup(parsed.url, parsed.soup, cfg)


def cmd_db(args: argparse.Namespace) -> int:
    panel = _load_db_panel(args)
    if args.json:
        print(json.dumps(
            {"url": panel.url, "queries": panel.queries, "count": len(panel.queries)},
            indent=2, ensure_ascii=False,
        ))
        return 0
    cprint(f"{BOLD}DB panel — {len(panel.queries)} queries{RESET}  (URL: {panel.url})", CYAN)
    if not panel.queries:
        cprint(f"{YELLOW}No queries parsed. Try: profiler panel {args.token} db --save /tmp/db.html{RESET}")
        return 1
    rows = [
        {
            "n": q["n"],
            "time": q["time"] or "",
            "frames": len(q["backtrace"]),
            "sql": q["sql"][:90],
        }
        for q in panel.queries
    ]
    print(fmt_table(rows, ["n", "time", "frames", "sql"], {"n": 4, "time": 10, "frames": 6, "sql": 100}))
    cprint(f"\n{DIM}Tip: 'profiler db-traces {args.token}' — all backtraces in one JSON{RESET}")
    return 0


def cmd_db_queries(args: argparse.Namespace) -> int:
    # Force json=True
    args.json = True
    return cmd_db(args)


def cmd_db_query(args: argparse.Namespace) -> int:
    panel = _load_db_panel(args)
    target = panel.by_number(args.n)
    if not target:
        cprint(f"{RED}Query #{args.n} not found (loaded {len(panel.queries)} queries){RESET}")
        return 1
    if args.json:
        print(json.dumps(target, indent=2, ensure_ascii=False))
        return 0
    cprint(f"{BOLD}DB query #{args.n}{RESET}  ({target['time']})  frames={len(target['backtrace'])}", CYAN)
    cprint(f"{BOLD}SQL:{RESET}")
    for line in target["sql"].splitlines()[:50]:
        print(f"  {line}")
    if target["params"]:
        cprint(f"\n{BOLD}Parameters:{RESET}")
        for i, p in enumerate(target["params"], 1):
            print(f"  [{i}] {p[:200]}")
    if target["backtrace"]:
        cprint(f"\n{BOLD}Backtrace ({len(target['backtrace'])} frames):{RESET}")
        for f in target["backtrace"][:args.max_frames]:
            n = f.get("n", "?")
            call = f.get("call", "?")
            line = f.get("line", "")
            if line:
                print(f"  {n:>3}  {call:<80} (line {line})")
            else:
                print(f"  {n:>3}  {call}")
    if target.get("explain_url"):
        cprint(f"\n{DIM}Explain: {target['explain_url']}{RESET}")
    return 0


def cmd_db_trace(args: argparse.Namespace) -> int:
    panel = _load_db_panel(args)
    target = panel.by_number(args.n)
    if not target:
        cprint(f"{RED}Query #{args.n} not found (loaded {len(panel.queries)} queries){RESET}")
        return 1
    frames: list[dict[str, Any]] = []
    for f in target["backtrace"]:
        frames.append({**f, "host_path": panel._host_path(f.get("file"))})
    out = {
        "url": panel.url,
        "n": args.n,
        "time": target["time"],
        "sql": target["sql"],
        "params": target["params"],
        "frames": frames,
        "first_app_frame": panel.first_app_frame(target),
    }
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    cprint(f"{BOLD}Query #{args.n}{RESET}  ({target['time']})", CYAN)
    cprint(f"{BOLD}SQL:{RESET}")
    for line in target["sql"].splitlines()[:50]:
        print(f"  {line}")
    if target["params"]:
        cprint(f"\n{BOLD}Parameters:{RESET}")
        for i, p in enumerate(target["params"], 1):
            print(f"  [{i}] {p[:200]}")
    cprint(f"\n{BOLD}Backtrace ({len(frames)} frames):{RESET}")
    for f in frames[:args.max_frames]:
        kind = "🟢" if f.get("is_src") else ("⚪" if f.get("is_vendor") else "🟡")
        host = f.get("host_path") or "?"
        n = f.get("n", "?")
        call = f.get("call") or "?"
        line = f.get("line", "")
        line_info = f":{line}" if line else ""
        print(f"  {kind} {n:>3}  {call[:80]:<80}  {host}{line_info}")
    return 0


def cmd_db_traces(args: argparse.Namespace) -> int:
    panel = _load_db_panel(args)
    queries = panel.queries
    if args.only_with_trace:
        queries = [q for q in queries if q["backtrace"]]
    out = {
        "url": panel.url,
        "count": len(queries),
        "queries": queries,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_db_hotspots(args: argparse.Namespace) -> int:
    panel = _load_db_panel(args)
    a = analyze(panel)
    print(json.dumps(a.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_db_analyze(args: argparse.Namespace) -> int:
    panel = _load_db_panel(args)
    a = analyze(panel)
    if args.json:
        print(json.dumps(a.to_dict(), indent=2, ensure_ascii=False))
        return 0
    cprint(f"{BOLD}DB panel analysis — token {a.token}{RESET}", CYAN)
    cprint(f"URL: {a.url}")
    cprint(f"\n  total queries:  {BOLD}{a.total}{RESET}")
    cprint(f"  total time:     {BOLD}{a.total_ms:.1f} ms{RESET}")
    cprint(f"  unique SQL:     {len(a.groups)}")
    cprint(f"  N+1 groups:     {len(a.n_plus_one)}  {DIM}(count>1){RESET}")
    cprint("")

    cprint(f"{BOLD}Top N+1 groups:{RESET}")
    print(fmt_table(
        [
            {
                "count": g["count"],
                "time_ms": f"{g['total_ms']:.1f}",
                "avg_ms": f"{g['total_ms']/g['count']:.1f}",
                "sql": g["sample_sql"][:90],
            }
            for g in a.n_plus_one[:args.top]
        ],
        ["count", "time_ms", "avg_ms", "sql"],
        {"count": 5, "time_ms": 10, "avg_ms": 8, "sql": 90},
    ))

    cprint(f"\n{BOLD}Top callers:{RESET}")
    print(fmt_table(
        [
            {
                "count": c["count"],
                "queries": ",".join(str(x) for x in c["queries"][:6]) + ("…" if len(c["queries"]) > 6 else ""),
                "call": c["call"][:80],
            }
            for c in a.callers[:args.top]
        ],
        ["count", "queries", "call"],
        {"count": 5, "queries": 30, "call": 90},
    ))

    cprint(f"\n{BOLD}Top {min(args.top, len(a.slowest))} slowest queries:{RESET}")
    for q in a.slowest[:args.top]:
        af = next((f for f in a.first_app_frames if f["n"] == q["n"]), None)
        loc = f"{af['host_path']}:{af['line']}" if af and af.get("host_path") else "?"
        cls = f"{af['class']}->{af['method']}" if af and af.get("class") else "?"
        print(f"  #{q['n']:>3}  {q['time']:>10}  {cls[:60]:<60}  {DIM}{loc}{RESET}")

    cprint(f"\n{DIM}Hint: 'profiler db-analyze {args.token} --json' — for jq{RESET}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    client = _make_client(cfg)
    needle = re.compile(args.pattern, re.IGNORECASE)
    nav_html = client.fetch(client.url(args.token))
    soup = BeautifulSoup(nav_html, "lxml")
    panels = [
        m.group(1)
        for m in (
            re.search(r"[?&]panel=([a-z0-9_-]+)", a.get("href", ""))
            for a in soup.find_all("a", href=True)
        )
        if m
    ]
    panels = list(dict.fromkeys(panels)) or ["db", "request", "time", "twig", "logger", "events", "router"]

    seen: list[str] = []
    for name in panels:
        try:
            sub = _fetch_soup(client, args.token, panel=name)
        except ProfilerError:
            continue
        if needle.search(sub.html):
            cprint(f"{GREEN}match:{RESET} panel={BOLD}{name}{RESET}  ({len(sub.html)} bytes)  -> {sub.url}")
            seen.append(name)
    if not seen:
        cprint(f"{RED}no match for /{args.pattern}/ across panels{RESET}")
        return 1
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = _resolve_config(args)
    client = _make_client(cfg)
    parsed = _fetch_soup(client, args.token, panel=args.panel, type_=args.type, query=args.query)
    if args.save:
        with open(args.save, "w", encoding="utf-8") as f:
            f.write(parsed.html)
        cprint(f"saved -> {args.save}  ({len(parsed.html)} bytes)", GREEN)
    else:
        sys.stdout.write(parsed.html)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except requests.HTTPError as e:
        sys.stderr.write(f"http error: {e.response.status_code} {e.response.reason} for {e.request.url}\n")
        return 1
    except requests.RequestException as e:
        sys.stderr.write(f"request error: {e}\n")
        return 1
    except KeyboardInterrupt:
        return 130
    except ProfilerError as e:
        sys.stderr.write(f"profiler error: {e}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
