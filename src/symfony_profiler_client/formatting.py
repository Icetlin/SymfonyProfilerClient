"""
ANSI-coloured output and small table renderer.

Colours are only emitted when stdout is a TTY and the NO_COLOR env var
is not set. See https://no-color.org/.
"""
from __future__ import annotations

import os
import sys
from typing import Any


# ANSI escape codes
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
MAG = "\033[35m"


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def cprint(s: str, color: str = "") -> None:
    if _color_enabled() and color:
        print(f"{color}{s}{RESET}")
    else:
        print(s)


def fmt_table(
    rows: list[dict[str, Any]],
    columns: list[str],
    col_widths: dict[str, int] | None = None,
) -> str:
    """Render a list of dicts as a plain ASCII table.

    Long values are truncated with an ellipsis at ``col_widths[col]-1``.
    Column headers are bolded when colour is enabled.
    """
    if not rows:
        return "(empty)"

    col_widths = col_widths or {}
    widths: dict[str, int] = {col: len(col) for col in columns}
    for r in rows:
        for col in columns:
            val = str(r.get(col, ""))
            cap = col_widths.get(col)
            if cap is not None:
                widths[col] = max(widths[col], min(len(val), cap))
            else:
                widths[col] = max(widths[col], len(val))

    lines: list[str] = []
    bold = BOLD if _color_enabled() else ""
    rst = RESET if _color_enabled() else ""
    lines.append("  ".join(f"{bold}{col.upper():<{widths[col]}}{rst}" for col in columns))
    lines.append("  ".join("-" * widths[col] for col in columns))
    for r in rows:
        cells = []
        for col in columns:
            val = str(r.get(col, ""))
            if len(val) > widths[col]:
                val = val[: widths[col] - 1] + "…"
            cells.append(f"{val:<{widths[col]}}")
        lines.append("  ".join(cells))
    return "\n".join(lines)
