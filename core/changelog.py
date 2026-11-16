"""Парсер RELEASE_NOTES.md и CHANGELOG.md → список версий для окна «Что нового»."""

from __future__ import annotations

import html as html_mod
import re
import sys
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


def _find_doc_file(filename: str) -> Path | None:
    """Ищет markdown-файл рядом с приложением / в корне проекта."""
    candidates: list[Path] = []
    try:
        # core/changelog.py → parents[1] = project root
        root = Path(__file__).resolve().parents[1]
        candidates.append(root / filename)
    except Exception as exc:  # noqa: BLE001 — граница путей / frozen
        _log.debug("Не удалось определить корень проекта для %s: %s", filename, exc)
    try:
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / filename)
        candidates.append(Path(sys.argv[0]).resolve().parent / filename)
    except Exception as exc:  # noqa: BLE001 — граница путей / frozen
        _log.debug("Не удалось определить путь запуска для %s: %s", filename, exc)
    candidates.append(Path.cwd() / filename)
    for p in candidates:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def changelog_path() -> Path | None:
    """Ищет CHANGELOG.md рядом с приложением / в корне проекта."""
    return _find_doc_file("CHANGELOG.md")


def release_notes_path() -> Path | None:
    """Ищет RELEASE_NOTES.md рядом с приложением / в корне проекта."""
    return _find_doc_file("RELEASE_NOTES.md")


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


def _load_entries_from(path: Path | None, label: str) -> list[ChangelogEntry]:
    if path is None:
        _log.warning("%s not found", label)
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        _log.exception("Failed to read %s %s", label, path)
        return []
    return parse_changelog(text)


def load_changelog(path: Path | None = None) -> list[ChangelogEntry]:
    return _load_entries_from(path or changelog_path(), "CHANGELOG.md")


def load_release_notes(path: Path | None = None) -> list[ChangelogEntry]:
    return _load_entries_from(path or release_notes_path(), "RELEASE_NOTES.md")


def load_whats_new(
    release_path: Path | None = None,
    changelog_file: Path | None = None,
) -> tuple[list[ChangelogEntry], list[ChangelogEntry]]:
    """Возвращает (пользовательский список, полный технический CHANGELOG).

    Для версий, описанных в RELEASE_NOTES.md, используется понятный пользователю текст;
    остальные версии автоматически подтягиваются из CHANGELOG.md.
    """
    release_entries = load_release_notes(release_path)
    tech_entries = load_changelog(changelog_file)
    if not release_entries:
        return list(tech_entries), tech_entries
    if not tech_entries:
        return release_entries, []

    release_by_ver = {e.version: e for e in release_entries}
    tech_versions = {e.version for e in tech_entries}

    merged: list[ChangelogEntry] = [
        e for e in release_entries if e.version not in tech_versions
    ]
    for tech in tech_entries:
        merged.append(release_by_ver.get(tech.version, tech))
    return merged, tech_entries


def markdown_to_html(body: str) -> str:
    """Простой markdown → HTML для QTextBrowser (заголовки, списки, **bold**, *italic*, `code`)."""
    if not body.strip():
        return "<p><i>Нет описания для этой версии.</i></p>"

    out: list[str] = []
    ul_depth = 0

    def set_ul_depth(target: int) -> None:
        nonlocal ul_depth
        while ul_depth < target:
            out.append("<ul>")
            ul_depth += 1
        while ul_depth > target:
            out.append("</ul>")
            ul_depth -= 1

    for raw in body.split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            set_ul_depth(0)
            continue
        if s.startswith("### "):
            set_ul_depth(0)
            out.append(f"<h3>{_inline(s[4:])}</h3>")
            continue
        if s.startswith("## "):
            set_ul_depth(0)
            out.append(f"<h2>{_inline(s[3:])}</h2>")
            continue
        if s.startswith("# "):
            set_ul_depth(0)
            out.append(f"<h2>{_inline(s[2:])}</h2>")
            continue
        if s.startswith("- ") or s.startswith("* "):
            indent = len(line) - len(line.lstrip(" \t"))
            target_depth = 2 if (indent >= 2 and ul_depth >= 1) else 1
            set_ul_depth(target_depth)
            out.append(f"<li>{_inline(s[2:])}</li>")
            continue
        set_ul_depth(0)
        out.append(f"<p>{_inline(s)}</p>")
    set_ul_depth(0)
    return "\n".join(out)


def _inline(text: str) -> str:
    """Экранирование + **bold** + *italic* + `code`."""
    t = html_mod.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t
