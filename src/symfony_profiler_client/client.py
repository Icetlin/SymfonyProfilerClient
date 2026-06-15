"""
Thin HTTP client for the Symfony WebProfilerBundle.

Responsibilities:
    - build Profiler URLs (``/_profiler/<token>?panel=...&type=...&query=...``)
    - run requests with cookies, bearer, and extra headers
    - handle self-signed dev certs (PROFILER_INSECURE / --insecure)
    - return a :class:`ParsedProfiler` with both raw HTML and a BeautifulSoup
"""
from __future__ import annotations

import http.cookiejar
import os
import sys
import warnings
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import re

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

from .config import ProfilerConfig, normalise_container_path
from .exceptions import ProfilerHTTPError

#: Match "HTTP Status" / "Status Code" header in the summary table.
_STATUS_RE = re.compile(r"HTTP\s*Status|Status\s*Code", re.I)
#: Fallback: a span whose class contains "status" and whose text starts with a 3-digit code.
_STATUS_SPAN_RE = re.compile(
    r"<span[^>]*class=\"[^\"]*status[^\"]*\"[^>]*>\s*(\d{3})"
)


@dataclass
class ProfilerClient:
    """HTTP client for a Symfony app exposing the WebProfilerBundle."""
    config: ProfilerConfig
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        ua = f"{self.config.user_agent}/1.0"
        self.session.headers.setdefault("User-Agent", ua)
        self.session.headers.setdefault(
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        )

        if self.config.cookies_file and os.path.exists(self.config.cookies_file):
            self._load_netscape_cookies(self.config.cookies_file)

        for h in self.config.extra_headers:
            if ":" in h:
                k, v = h.split(":", 1)
                self.session.headers[k.strip()] = v.strip()

        if self.config.bearer:
            self.session.headers["Authorization"] = f"Bearer {self.config.bearer}"

        if self.config.insecure:
            self.session.verify = False
            warnings.simplefilter("ignore", InsecureRequestWarning)

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def url(
        self,
        token: str,
        *,
        panel: str | None = None,
        type_: str | None = None,
        query: int | None = None,
        page: str | None = None,
        **extra: str,
    ) -> str:
        if not self.config.base:
            raise ValueError(
                "base URL is not configured: pass --base, set PROFILER_BASE, "
                "or add 'base' to ~/.config/symfony-profiler-client/config.toml"
            )
        path = f"/_profiler/{token}"
        params: list[tuple[str, str]] = []
        if panel:
            params.append(("panel", panel))
        if type_:
            params.append(("type", type_))
        if query is not None:
            params.append(("query", str(query)))
        if page:
            params.append(("page", page))
        for k, v in extra.items():
            if v is not None:
                params.append((k, str(v)))
        qs = urlencode(params)
        return f"{self.config.base.rstrip('/')}{path}{('?' + qs) if qs else ''}"

    def fetch(self, url: str) -> str:
        try:
            r = self.session.get(url, timeout=self.config.timeout)
        except requests.RequestException as e:
            raise ProfilerHTTPError(f"transport error: {e}", url=url) from e
        if r.status_code >= 400:
            raise ProfilerHTTPError(
                f"HTTP {r.status_code} for {url}",
                status=r.status_code,
                url=url,
            )
        return r.text

    def fetch_file(self, path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    def _load_netscape_cookies(self, path: str) -> None:
        cj = http.cookiejar.MozillaCookieJar(path)
        try:
            cj.load(ignore_discard=True, ignore_expires=True)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"warning: failed to load cookies file: {exc}\n")
            return
        for c in cj:
            self.session.cookies.set_cookie(c)


# ---------------------------------------------------------------------------
# Parsed page
# ---------------------------------------------------------------------------

@dataclass
class ParsedProfiler:
    """A Profiler page that has been fetched and parsed."""
    url: str
    html: str
    soup: BeautifulSoup
    config: ProfilerConfig

    def host_path(self, file_path: str | None) -> str | None:
        """Map an in-container file path to the local checkout."""
        return normalise_container_path(
            file_path,
            src_prefix=self.config.src_prefix,
            host_prefix=self.config.host_prefix,
        )

    # ----- meta --------------------------------------------------------

    def token(self) -> str | None:
        m = re.search(r"/_profiler/([0-9a-f]+)", self.url)
        return m.group(1) if m else None

    def status_code(self) -> str | None:
        th = self.soup.find("th", string=_STATUS_RE)
        if th:
            sib = th.find_next_sibling("td")
            if sib:
                return sib.get_text(" ", strip=True)
        m = _STATUS_SPAN_RE.search(self.html)
        return m.group(1) if m else None

    def header_rows(self) -> list[dict[str, str]]:
        """Pairs of ``(th, td)`` from the top summary table."""
        rows: list[dict[str, str]] = []
        for table in self.soup.find_all("table"):
            for tr in table.find_all("tr"):
                th = tr.find("th")
                tds = tr.find_all("td")
                if th and tds:
                    rows.append({
                        "key": th.get_text(" ", strip=True).rstrip(":"),
                        "value": " ".join(td.get_text(" ", strip=True) for td in tds),
                    })
        return rows

    def summary_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"url": self.url, "token": self.token()}
        for row in self.header_rows():
            k = re.sub(r"\W+", "_", row["key"].lower()).strip("_")
            if k and k not in out:
                out[k] = row["value"]
        sc = self.status_code()
        if sc:
            out["status_code"] = sc
        return out

    # ----- panels ------------------------------------------------------

    def panel_nav(self) -> list[dict[str, Any]]:
        """List of panels from the side-nav with optional count."""
        out: list[dict[str, Any]] = []
        for a in self.soup.select("a[href*='panel=']"):
            href = a.get("href", "")
            m = re.search(r"[?&]panel=([a-z0-9_-]+)", href)
            if not m:
                continue
            name = m.group(1)
            status_el = a.find(["span", "small"], class_=re.compile(r"label|status|count|badge", re.I))
            count: int | None = None
            text = a.get_text(" ", strip=True)
            cm = re.search(r"(\d+)\s*$", text)
            if cm:
                count = int(cm.group(1))
            elif status_el:
                cm2 = re.search(r"\d+", status_el.get_text(" ", strip=True))
                if cm2:
                    count = int(cm2.group(0))
            out.append({"panel": name, "label": text, "count": count, "href": href})
        return out

    def panel_main_html(self) -> str:
        """Main content area HTML, with sidebar/header stripped if possible."""
        for sel in ["#panel-content", ".panel-content", "#main .panel",
                    "div#content .sf-toolbarreset", "main", "#main"]:
            el = self.soup.select_one(sel)
            if el:
                return str(el)
        return self.html
