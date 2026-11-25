from core.changelog import parse_changelog, markdown_to_html

SAMPLE = """# Changelog

## [0.0.18] - 2026-10-31

### Fixed — something
- first item
- second **bold**

## [0.0.17] - 2026-10-20

### Added
- feature `x`
"""

def test_parse_versions_newest_first():
    entries = parse_changelog(SAMPLE)
    assert len(entries) == 2
    assert entries[0].version == "0.0.18"
    assert entries[0].date == "2026-10-31"
    assert "first item" in entries[0].body
    assert entries[1].version == "0.0.17"

def test_parse_escaped_brackets():
    text = "## \\[0.0.18\\] - 2026-10-31\n\n### Fix\n- a\n"
    entries = parse_changelog(text)
    assert entries and entries[0].version == "0.0.18"

def test_markdown_to_html():
    html = markdown_to_html("### Title\n- item `code`\n  - nested *italic*\n- **bold**")
    assert "<h3>" in html
    assert "<li>" in html
    assert "<code>code</code>" in html
    assert "<i>italic</i>" in html
    assert "<b>bold</b>" in html
    assert html.count("<ul>") == 2
    assert html.count("</ul>") == 2


def test_load_real_changelog():
    from core.changelog import load_changelog
    entries = load_changelog()
    assert entries
    assert entries[0].version == "0.0.23"


def test_load_real_release_notes_and_merge():
    from core.changelog import load_release_notes, load_whats_new

    rel = load_release_notes()
    merged, tech = load_whats_new()
    assert rel and merged and tech
    assert [e.version for e in rel] == [e.version for e in tech]
    assert [e.version for e in merged] == [e.version for e in tech]
    for entry, rel_entry in zip(merged, rel):
        assert entry.body == rel_entry.body
        assert ".py" not in rel_entry.body
        assert "tests/" not in rel_entry.body
