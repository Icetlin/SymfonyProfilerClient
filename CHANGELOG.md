# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-15

### Added
- Initial public release.
- CLI commands: `info`, `panels`, `panel`, `db`, `db-queries`, `db-query`,
  `db-trace`, `db-traces`, `db-hotspots`, `db-analyze`, `search`, `fetch`.
- Configuration via CLI flags, environment variables, and TOML config file
  (`$XDG_CONFIG_HOME/symfony-profiler-client/config.toml`).
- Auto-detection of the local Symfony project root (walks up from cwd,
  also checks `git rev-parse --show-toplevel`).
- Auto-detection of in-container path prefix from a list of common
  candidates (`/var/www/html`, `/app`, `/srv/app`, `/var/www`).
- N+1 detection, slowest queries, top callers, first-app-frame analysis
  on the DB panel.
- `--json` output for every command that produces structured data.
- `--insecure` / `PROFILER_INSECURE=1` for self-signed dev certificates.
- Pluggable skip_prefixes list (configurable in `config.toml`).
- Python 3.9+ support; uses stdlib `tomllib` on 3.11+ and `tomli` below.
