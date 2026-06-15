"""
Configuration resolution for symfony-profiler-client.

Resolution order (highest priority first):
    1. CLI flags (--base, --cookies, --bearer, --src-prefix, --host-prefix, …)
    2. Environment variables (PROFILER_BASE, PROFILER_COOKIES, PROFILER_BEARER,
                              PROFILER_SRC_PREFIX, PROFILER_HOST_PREFIX,
                              PROFILER_INSECURE, PROFILER_TIMEOUT)
    3. TOML config file: $XDG_CONFIG_HOME/symfony-profiler-client/config.toml
                         (~/.config/symfony-profiler-client/config.toml)
                         Can also be overridden via --config /path/to/file.toml
                         or PROFILER_CONFIG=/path/to/file.toml.
    4. Auto-detection (host_prefix only — walks up from cwd looking for
                      a Symfony project, also tries `git rev-parse`).
    5. Safe defaults (no project-specific paths, no personal URLs).

The point of this hierarchy: zero hardcoded paths and zero project-specific
defaults leak into the public package. Every value is overridable; if a
value cannot be resolved the CLI surfaces a clear error pointing at the
right knob.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Try to use tomllib (3.11+), fall back to tomli. We never hard-fail:
# if neither is available, config files are silently ignored.
try:  # pragma: no cover - import guard
    import tomllib as _toml  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore[import-untyped,import-not-found]
    except ModuleNotFoundError:
        _toml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Defaults — keep these neutral. Never put personal paths or hosts here.
# ---------------------------------------------------------------------------

#: Default base URL for the Symfony app. The local dev server on Symfony CLI
#: (`symfony serve`) and on `php -S` both listen here by default; the user
#: can override via --base, PROFILER_BASE, or config.
DEFAULT_BASE = "http://127.0.0.1:8000"

#: Default request timeout in seconds.
DEFAULT_TIMEOUT = 600.0

#: Default User-Agent product token (version is appended at runtime).
DEFAULT_USER_AGENT = "symfony-profiler-client"

#: Framework/ORM class prefixes that should be considered "not first app
#: frame" in a backtrace. Configurable via config.toml under
#: ``[analyzer] skip_prefixes = [...]``.
DEFAULT_SKIP_PREFIXES: tuple[str, ...] = (
    "Doctrine\\",
    "Symfony\\",
    "PDO",
    "Propel",
)

#: Common in-container paths for Symfony apps. The auto-detector tries each
#: when normalising file:// backtrace URLs to host paths.
COMMON_CONTAINER_PATHS: tuple[str, ...] = (
    "/var/www/html",
    "/app",
    "/srv/app",
    "/var/www",
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def default_config_path() -> Path | None:
    """Return the default config file path, or None if XDG is unset."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "symfony-profiler-client" / "config.toml"


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

def detect_host_prefix(start: Path | None = None) -> str | None:
    """
    Try to find the local checkout of the Symfony project whose Profiler
    we are about to read.

    Strategy:
      1. Start at ``start`` (defaults to cwd) and walk up the tree.
      2. If a directory contains both ``vendor/`` and ``composer.json``
         (or ``symfony.lock``), it's a Symfony project — return it.
      3. If a directory contains ``.git``, try ``git rev-parse
         --show-toplevel`` and use that if it has a ``src/`` directory.

    Returns None if nothing plausible is found. Callers must handle None.
    """
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if _looks_like_symfony_root(candidate):
            return str(candidate)
        if (candidate / ".git").is_dir():
            toplevel = _git_toplevel(candidate)
            if toplevel and _looks_like_symfony_root(toplevel):
                return str(toplevel)
    return None


def _looks_like_symfony_root(path: Path) -> bool:
    """Heuristic: a directory is a Symfony project root if it has
    a src/ directory and either composer.json or symfony.lock."""
    if not (path / "src").is_dir():
        return False
    if (path / "composer.json").is_file():
        return True
    if (path / "symfony.lock").is_file():
        return True
    return False


def _git_toplevel(path: Path) -> str | None:
    """Return `git rev-parse --show-toplevel` output, or None if not a repo
    or git is not installed."""
    if shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    top = out.stdout.strip()
    return top or None


# ---------------------------------------------------------------------------
# Path normalisation
# ---------------------------------------------------------------------------

def normalise_container_path(
    file_path: str | None,
    *,
    src_prefix: str | None,
    host_prefix: str | None,
) -> str | None:
    """
    Map a file path that the Profiler reported from inside a container
    (e.g. ``/var/www/html/src/Service/Foo.php``) to the local checkout
    (``/home/me/project/src/Service/Foo.php``).

    Resolution:
      1. If the file is already under ``host_prefix``, return as-is.
      2. If ``src_prefix`` is set and the file starts with it, swap the
         prefix to ``host_prefix``.
      3. Otherwise, try each candidate in :data:`COMMON_CONTAINER_PATHS`
         and swap the first match.

    Returns the original path if no mapping applies. The mapping is best-
    effort: when in doubt, the caller gets the original string.
    """
    if not file_path:
        return None

    # Already in the host tree.
    if host_prefix and file_path.startswith(host_prefix.rstrip("/") + "/"):
        return file_path

    candidates: list[str] = []
    if src_prefix:
        candidates.append(src_prefix)
    candidates.extend(COMMON_CONTAINER_PATHS)

    for cand in candidates:
        cand = cand.rstrip("/")
        if file_path.startswith(cand + "/"):
            if host_prefix:
                return host_prefix.rstrip("/") + file_path[len(cand):]
            return file_path
        if file_path == cand and host_prefix:
            return host_prefix
    return file_path


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

@dataclass
class ProfilerConfig:
    """Resolved configuration. Always populated — ``None`` fields mean
    'not configured' and the caller decides what to do."""
    base: str | None = None
    cookies_file: str | None = None
    bearer: str | None = None
    src_prefix: str | None = None
    host_prefix: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    insecure: bool = False
    extra_headers: list[str] = field(default_factory=list)
    skip_prefixes: tuple[str, ...] = DEFAULT_SKIP_PREFIXES
    user_agent: str = DEFAULT_USER_AGENT
    config_file: Path | None = None

    @classmethod
    def from_sources(
        cls,
        *,
        cli: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        config_file: str | os.PathLike[str] | None = None,
        auto_detect_host: bool = True,
    ) -> "ProfilerConfig":
        """
        Build a config by layering CLI > env > TOML file > auto-detect.

        :param cli: dict of CLI flag values (``None`` means "not passed").
                    Only the keys that are explicitly set win; absent keys
                    defer to the lower layers.
        :param env: environment dict (defaults to :data:`os.environ`).
        :param config_file: explicit path to a TOML file. If ``None``, the
                            default XDG location is used.
        :param auto_detect_host: if True and no host_prefix was set by any
                                 other layer, run :func:`detect_host_prefix`.
        """
        cli = cli or {}
        env = env if env is not None else dict(os.environ)

        # ---- layer 1: file -------------------------------------------------
        file_cfg: dict[str, Any] = {}
        cfg_path: Path | None = None
        if config_file is not None:
            cfg_path = Path(config_file).expanduser()
            if not cfg_path.is_file():
                raise FileNotFoundError(f"config file not found: {cfg_path}")
        elif env.get("PROFILER_CONFIG"):
            cfg_path = Path(env["PROFILER_CONFIG"]).expanduser()
        else:
            default = default_config_path()
            if default and default.is_file():
                cfg_path = default

        if cfg_path and cfg_path.is_file():
            file_cfg = _load_toml(cfg_path)
            # also support a [profiler] table for cleanliness, fall back to root
            file_cfg = file_cfg.get("profiler", file_cfg)

        # ---- layer 2: env --------------------------------------------------
        env_cfg: dict[str, Any] = {
            k.removeprefix("PROFILER_").lower(): v
            for k, v in env.items()
            if k.startswith("PROFILER_") and k != "PROFILER_CONFIG"
        }
        # some env keys need renaming to match the dataclass field names
        if "src_prefix" in env_cfg:
            env_cfg["src_prefix"] = env_cfg["src_prefix"]
        if "host_prefix" in env_cfg:
            env_cfg["host_prefix"] = env_cfg["host_prefix"]
        if "cookies" in env_cfg:
            env_cfg["cookies_file"] = env_cfg.pop("cookies")
        if "bearer" in env_cfg:
            env_cfg["bearer"] = env_cfg["bearer"]
        if "insecure" in env_cfg:
            env_cfg["insecure"] = _truthy(env_cfg["insecure"])
        if "timeout" in env_cfg:
            try:
                env_cfg["timeout"] = float(env_cfg["timeout"])
            except ValueError:
                pass

        # ---- layer 3: cli --------------------------------------------------
        cli_cfg: dict[str, Any] = {k: v for k, v in cli.items() if v is not None}
        if "insecure" in cli_cfg:
            cli_cfg["insecure"] = bool(cli_cfg["insecure"])

        # ---- merge in priority order --------------------------------------
        merged: dict[str, Any] = {}
        merged.update(file_cfg)
        merged.update(env_cfg)
        merged.update(cli_cfg)

        # ---- auto-detect host_prefix if still unset -----------------------
        if auto_detect_host and not merged.get("host_prefix"):
            detected = detect_host_prefix()
            if detected:
                merged["host_prefix"] = detected

        # ---- finalise -----------------------------------------------------
        cfg = cls(
            base=merged.get("base", DEFAULT_BASE),
            cookies_file=_coerce_path(merged.get("cookies_file")),
            bearer=merged.get("bearer"),
            src_prefix=merged.get("src_prefix"),
            host_prefix=merged.get("host_prefix"),
            timeout=float(merged.get("timeout", DEFAULT_TIMEOUT)),
            insecure=bool(merged.get("insecure", False)),
            extra_headers=list(merged.get("extra_headers", []) or []),
            skip_prefixes=tuple(merged.get("skip_prefixes", DEFAULT_SKIP_PREFIXES)),
            user_agent=str(merged.get("user_agent", DEFAULT_USER_AGENT)),
            config_file=cfg_path,
        )
        return cfg

    def as_requests_kwargs(self) -> dict[str, Any]:
        """Subset of fields needed by requests."""
        return {
            "base": self.base,
            "cookies_file": self.cookies_file,
            "bearer": self.bearer,
            "timeout": self.timeout,
            "insecure": self.insecure,
            "extra_headers": list(self.extra_headers),
            "user_agent": self.user_agent,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truthy(s: str) -> bool:
    return s.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, os.PathLike)):
        return str(Path(value).expanduser())
    return str(value)


def _load_toml(path: Path) -> dict[str, Any]:
    if _toml is None:
        # Soft warning: keep working without a config file.
        return {}
    with path.open("rb") as f:
        return _toml.load(f)
