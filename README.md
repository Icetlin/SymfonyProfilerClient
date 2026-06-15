# symfony-profiler-client

A small, dependency-light Python CLI and library for talking to the
[Symfony WebProfilerBundle](https://symfony.com/doc/current/profiler.html).

It fetches a profile token, lists panels, walks the DB panel, parses SQL
backtraces, and surfaces **N+1**, **slowest queries**, and **top callers**
in a format that pipes cleanly to `jq` or feeds straight into an LLM.

```text
$ profiler db-analyze bc65af --json | jq '.n_plus_one[:3]'
```

> Originally extracted from internal tooling and stripped of every
> project-specific hardcode. There are **no hardcoded paths, hostnames,
> or vendor prefixes** in this package — everything is configurable.

## Features

- 🔎 **DB panel** — full query list, params, Explain links, per-query
  backtraces with in-container → local path translation.
- 🚨 **N+1 detector** — groups identical SQL, sorted by `count × time`.
- 🐢 **Slowest queries** — top-N by execution time, with first app frame.
- 🧭 **Caller aggregation** — which method on which class is responsible
  for the most queries.
- 🔐 **Auth that fits your dev setup** — Netscape cookie jar, bearer
  token, raw extra headers, `--insecure` for self-signed certs.
- 🛠 **Zero-config auto-detect** — picks up the local project root from
  `cwd` / `git rev-parse --show-toplevel`.
- 📦 **Pip-installable** — adds a `profiler` console script and a
  `python -m symfony_profiler_client` entry point.

## Installation

```bash
pip install symfony-profiler-client
```

Or, for the latest development version:

```bash
pip install git+https://github.com/Icetlin/SymfonyProfilerClient.git
```

Verify:

```bash
profiler --help
```

## Quick start

The fastest way to use the tool against a local Symfony app:

```bash
profiler info bc65af
profiler panels bc65af
profiler db bc65af
profiler db-analyze bc65af
profiler db-trace bc65af 17
```

For an app that lives behind a non-default host:

```bash
profiler --base https://my-app.test info bc65af
```

For an app with self-signed TLS (typical for `symfony serve`):

```bash
profiler --insecure info bc65af
# or
PROFILER_INSECURE=1 profiler info bc65af
```

## Configuration

Configuration is resolved from four layers, in this priority order:

1. **CLI flags** (highest priority)
2. **Environment variables** (`PROFILER_*`)
3. **TOML config file** at
   `$XDG_CONFIG_HOME/symfony-profiler-client/config.toml`
   (or `~/.config/symfony-profiler-client/config.toml`).
   Override the path with `--config /path/to/file.toml` or
   `PROFILER_CONFIG=/path/to/file.toml`.
4. **Auto-detection** — `host_prefix` walks up from `cwd` looking for a
   Symfony project, also tries `git rev-parse --show-toplevel`. `src_prefix`
   tries a list of common container paths (see below).

### Environment variables

| Variable                | Effect                                                |
|-------------------------|-------------------------------------------------------|
| `PROFILER_BASE`         | Base URL of the Symfony app.                          |
| `PROFILER_COOKIES`      | Path to a Netscape cookie jar.                        |
| `PROFILER_BEARER`       | Bearer token (`Authorization: Bearer …`).             |
| `PROFILER_SRC_PREFIX`   | In-container path prefix (e.g. `/var/www/html`).      |
| `PROFILER_HOST_PREFIX`  | Local path prefix (e.g. `/home/me/myapp`).            |
| `PROFILER_INSECURE`     | `1` / `true` to skip TLS verification.                |
| `PROFILER_TIMEOUT`      | Request timeout in seconds (default `600`).           |
| `PROFILER_CONFIG`       | Path to an explicit config file.                      |

### Config file (TOML)

```toml
# ~/.config/symfony-profiler-client/config.toml

# A [profiler] table is preferred; root keys also work.
[profiler]
base = "https://my-app.test"
cookies_file = "/home/me/.cookies/my-app.txt"
bearer = "eyJhbGciOi..."

# Path translation: in-container path -> local path.
src_prefix = "/var/www/html"
host_prefix = "/home/me/projects/myapp"

# Behaviour
insecure = true
timeout = 30
extra_headers = ["X-Debug: 1", "X-Forwarded-User: dev"]

[analyzer]
# Framework class prefixes that are skipped when picking the
# "first app frame" of a backtrace. Add your own vendor packages here.
skip_prefixes = [
    "Doctrine\\",
    "Symfony\\",
    "PDO",
    "Propel",
    "Sentry\\",
]
```

### Common in-container paths

When `src_prefix` is not set explicitly, the tool tries these candidates
in order and uses the first one that matches the file's path:

- `/var/www/html`
- `/app`
- `/srv/app`
- `/var/www`

If none match, the in-container path is left as-is (it is still a valid
file path, just not a local one). You can always force a specific
prefix with `--src-prefix` or `PROFILER_SRC_PREFIX`.

## Commands

| Command         | Purpose                                                              |
|-----------------|----------------------------------------------------------------------|
| `info`          | Summary: HTTP status, method, URL, time, …                           |
| `panels`        | List panels available for a token.                                   |
| `panel`         | Open a specific panel; raw HTML by default, summary with `--json`.  |
| `db`            | List DB queries in a table.                                          |
| `db-queries`    | Same as `db --json`.                                                 |
| `db-query N`    | SQL + params + backtrace of query N.                                 |
| `db-trace N`    | Full backtrace of query N with local paths.                          |
| `db-traces`     | All backtraces for all queries in a single JSON object.              |
| `db-hotspots`   | Aggregated N+1 + callers + slowest, JSON only.                       |
| `db-analyze`    | Same data as `db-hotspots` with a human-readable table.             |
| `search`        | Grep a regex across every panel of a token.                          |
| `fetch`         | Fetch a Profiler URL and (optionally) save it to disk.               |

Every command accepts `--json` where it makes sense.

## Library usage

The CLI is a thin shell around the library. You can use the same
primitives from Python:

```python
from symfony_profiler_client import (
    ProfilerConfig,
    ProfilerClient,
    DbPanel,
    analyze,
)

cfg = ProfilerConfig.from_sources(
    cli={"base": "https://my-app.test", "bearer": "..."},
)
client = ProfilerClient(cfg)

# Fetch and parse a DB panel
url = client.url("bc65af", panel="db")
html = client.fetch(url)
from bs4 import BeautifulSoup
panel = DbPanel.from_soup(url, BeautifulSoup(html, "lxml"), cfg)

# Run analysis
result = analyze(panel)
print(f"{result.total} queries, {result.total_ms:.1f} ms, "
      f"{len(result.n_plus_one)} N+1 groups")

for g in result.n_plus_one[:5]:
    print(f"  ×{g['count']:>4}  {g['total_ms']:>7.1f} ms  {g['sample_sql'][:60]}")
```

## Development

```bash
git clone https://github.com/Icetlin/SymfonyProfilerClient.git
cd SymfonyProfilerClient

# Editable install with dev extras
pip install -e ".[dev,toml]"

# Run tests
pytest

# Lint
ruff check .
```

### Project layout

```
src/symfony_profiler_client/
  __init__.py        # public surface, lazy imports
  __main__.py        # python -m symfony_profiler_client
  cli.py             # argparse + subcommand dispatch
  client.py          # HTTP client (cookies, bearer, insecure)
  parser.py          # DB panel HTML parser
  analyzer.py        # N+1 / slowest / callers aggregation
  backtrace.py       # backtrace table / ol parsing
  config.py          # config resolution (CLI > env > file > auto-detect)
  formatting.py      # ANSI colour + small table renderer
  exceptions.py
  py.typed
tests/
  fixtures/          # sample profiler HTML
  test_config.py
  test_parser.py
  test_backtrace.py
  test_analyzer.py
```

## FAQ

**`Could not auto-detect host_prefix — pass --host-prefix or set PROFILER_HOST_PREFIX`.**

You ran the tool from a directory that is not inside (or under) a Symfony
project, and there is no `composer.json` / `symfony.lock` / `vendor/`
anywhere up the tree. Either `cd` into your project, or set the variable
explicitly.

**`HTTP 401 Unauthorized`.**

Your Symfony app requires authentication. Use one of:

- `--cookies /path/to/cookies.txt` (export a cookie jar from your
  browser with an extension like *cookies.txt*),
- `--bearer YOUR_TOKEN` for a JWT / API token,
- `-H "Cookie: PHPSESSID=abc..."` for an ad-hoc header.

**My `vendor/` paths in backtraces don't get translated.**

The tool already detects `vendor/` and labels those frames as
⚪ in `db-trace`. They are deliberately **not** translated to local paths
because that would require mapping the entire Composer install — which
isn't meaningful for diagnostics anyway. App frames (in `src/`) **are**
translated; configure `--host-prefix` if the auto-detect is wrong.

**The tool only sees the first page of DB queries.**

The Profiler paginates large DB panels. The tool does not paginate yet —
if you hit this, please open an issue with a `profiler db --json` dump
of the affected token and we'll add it.

## License

MIT — see [LICENSE](LICENSE).
