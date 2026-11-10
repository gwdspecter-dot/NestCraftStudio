"""Парсер CHANGELOG.md → список версий для окна «Что нового»."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.logging_setup import get_logger

_log = get_logger("changelog")

# ## [0.0.18] - 2026-10-31  или  ## \[0.0.18\] - 2026-10-31
_VERSION_RE = re.compile(
    r"^##\s+\\?\[([0-9]+(?:\.[0-9]+)*)\\?\]\s*(?:-\s*(.+))?\s*$"
)


@dataclass
class ChangelogEntry:
    version: str
    date: str = ""
    body: str = ""


def changelog_path() -> Path | None:
    """Ищет CHANGELOG.md рядом с приложением / в корне проекта."""
    candidates: list[Path] = []
    try:
        # core/changelog.py → parents[1] = project root
        root = Path(__file__).resolve().parents[1]
        candidates.append(root / "CHANGELOG.md")
    except Exception as exc:
        _log.debug("Не удалось определить корень проекта для CHANGELOG.md: %s", exc)
    try:
        import sys
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "CHANGELOG.md")
        candidates.append(Path(sys.argv[0]).resolve().parent / "CHANGELOG.md")
    except Exception as exc:
        _log.debug("Не удалось определить путь запуска для CHANGELOG.md: %s", exc)
    candidates.append(Path.cwd() / "CHANGELOG.md")
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def parse_changelog(text: str) -> list[ChangelogEntry]:
    """Разбирает markdown Keep a Changelog. Новые версии первыми."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    entries: list[ChangelogEntry] = []
    current: ChangelogEntry | None = None
    body_lines: list[str] = []

    def flush() -> None:
        nonlocal current, body_lines
        if current is not None:
            current.body = "\n".join(body_lines).strip()
            entries.append(current)
        current = None
        body_lines = []

    for line in lines:
        m = _VERSION_RE.match(line.strip())
        if m:
            flush()
            current = ChangelogEntry(
                version=m.group(1).strip(),
                date=(m.group(2) or "").strip(),
            )
            body_lines = []
            continue
        if current is not None:
            body_lines.append(line)
    flush()
    return entries


def load_changelog(path: Path | None = None) -> list[ChangelogEntry]:
    p = path or changelog_path()
    if p is None:
        _log.warning("CHANGELOG.md not found")
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        _log.exception("Failed to read CHANGELOG %s", p)
        return []
    return parse_changelog(text)


def markdown_to_html(body: str) -> str:
    """Простой markdown → HTML для QTextBrowser (заголовки, списки, code)."""
    if not body.strip():
        return "<p><i>Нет описания для этой версии.</i></p>"

    out: list[str] = []
    in_ul = False

    def close_ul() -> None:
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    for raw in body.split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            close_ul()
            continue
        if s.startswith("### "):
            close_ul()
            out.append(f"<h3>{_inline(s[4:])}</h3>")
            continue
        if s.startswith("## "):
            close_ul()
            out.append(f"<h2>{_inline(s[3:])}</h2>")
            continue
        if s.startswith("# "):
            close_ul()
            out.append(f"<h2>{_inline(s[2:])}</h2>")
            continue
        if s.startswith("- ") or s.startswith("* "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(s[2:])}</li>")
            continue
        close_ul()
        out.append(f"<p>{_inline(s)}</p>")
    close_ul()
    return "\n".join(out)


def _inline(text: str) -> str:
    """Экранирование + **bold** + `code`."""
    import html as html_mod

    t = html_mod.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t
