from app.channels.telegram import _strip_tags, _truncate, escape_html


def test_escape_html_escapes_lt_gt_amp():
    assert escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_escape_html_leaves_safe_chars_alone():
    src = "Steps: 12,345 (great!). Heart rate up 4%."
    assert escape_html(src) == src


def test_strip_tags_removes_html_and_unescapes_entities():
    src = "<b>Yesterday</b>: ran 5km &amp; slept 7h"
    assert _strip_tags(src) == "Yesterday: ran 5km & slept 7h"


def test_strip_tags_handles_no_tags():
    assert _strip_tags("just plain text") == "just plain text"


def test_truncate_short_text_unchanged():
    assert _truncate("short", limit=10) == "short"


def test_truncate_long_text_appends_ellipsis():
    out = _truncate("x" * 100, limit=10)
    assert len(out) == 10
    assert out.endswith("\u2026")
