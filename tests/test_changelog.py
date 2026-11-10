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
    html = markdown_to_html("### Title\n- item `code`\n- **bold**")
    assert "<h3>" in html
    assert "<li>" in html
    assert "<code>code</code>" in html
    assert "<b>bold</b>" in html

def test_load_real_changelog():
    from core.changelog import load_changelog
    entries = load_changelog()
    assert entries
    assert entries[0].version == "0.0.19"
