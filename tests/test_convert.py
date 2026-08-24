"""to_markdown fence sizing, canonical-URL resolution, page chrome removal."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from medium_archive.convert import convert_post, to_markdown
from medium_archive.pages import collapse_br_pairs, page_body
from medium_archive.urls import resolve_canonical, slug_of

URL = "https://blog.example.com/my-post-0123456789ab"


def md_of(html: str) -> str:
    body = BeautifulSoup(f"<article>{html}</article>", "html.parser")
    markdown, _ = to_markdown(body, URL, {}, Path("/nonexistent"))
    return markdown


def test_plain_pre_keeps_three_backtick_fence():
    assert md_of("<pre>a = 1</pre>") == "```\na = 1\n```\n"


def test_pre_containing_fences_gets_a_longer_fence():
    md = md_of("<pre>@@cell<br>```python<br>df.head()<br>```<br>@@output</pre>")
    assert md == "````\n@@cell\n```python\ndf.head()\n```\n@@output\n````\n"


def test_pre_fence_outgrows_longest_inner_run():
    md = md_of("<pre>````<br>nested<br>````</pre>")
    assert md.startswith("`````\n") and md.endswith("\n`````\n")


def test_inner_fence_at_pre_edges():
    # backticks as the first and last content must not be eaten by the fence
    md = md_of("<pre>```<br>x<br>```</pre>")
    assert md == "````\n```\nx\n```\n````\n"


def test_prose_after_fenced_pre_stays_prose():
    md = md_of("<pre>```<br>inner<br>```</pre><p>after the block.</p>")
    fence_lines = [l for l in md.splitlines() if l.startswith("`")]
    # outer pair of ```` plus the two inner ``` lines, all inside the block
    assert fence_lines == ["````", "```", "```", "````"]
    assert md.rstrip().endswith("after the block.")


def test_canonical_same_host_is_used():
    assert resolve_canonical(URL, "https://blog.example.com/my-post-0123456789ab?src=rss") \
        == ("https://blog.example.com/my-post-0123456789ab", None)


def test_canonical_bare_slug_is_provenance_not_identity():
    # Ghost-migrated posts declare their bare pre-migration slug; the
    # fetched URL is what inbound links use, so it keeps the identity
    assert resolve_canonical(URL, "old-ghost-slug") \
        == (URL, "https://blog.example.com/old-ghost-slug")


def test_canonical_may_upgrade_scheme():
    assert resolve_canonical("http://blog.example.com/a-post-0123456789ab",
                             "https://blog.example.com/a-post-0123456789ab") \
        == ("https://blog.example.com/a-post-0123456789ab", None)


def test_canonical_external_host_is_provenance_not_identity():
    post, external = resolve_canonical(URL, "https://gist.github.com/abcdef123456")
    assert post == URL
    assert external == "https://gist.github.com/abcdef123456"


def test_canonical_missing_falls_back_to_fetched():
    assert resolve_canonical(URL, None) == (URL, None)


def collapsed_md_of(html: str) -> str:
    body = BeautifulSoup(f"<article>{html}</article>", "html.parser")
    collapse_br_pairs(body)
    markdown, _ = to_markdown(body, URL, {}, Path("/nonexistent"))
    return markdown


def test_double_br_collapses_to_a_space_in_migrated_posts():
    # Medium's Ghost-migration importer renders each wrapped source line
    # as <br><br> mid-paragraph; the pair stands for a single space
    md = collapsed_md_of("<p>community of<br><br>Contributors, the project</p>")
    assert md == "community of Contributors, the project\n"


def test_lone_br_stays_a_soft_break():
    md = collapsed_md_of("<p>line one<br>line two</p>")
    assert md == "line one  \nline two\n"


def test_double_br_in_pre_stays_a_blank_line():
    md = collapsed_md_of("<pre>a = 1<br><br>b = 2</pre>")
    assert md == "```\na = 1\n\nb = 2\n```\n"


def test_double_br_kept_without_a_ghost_origin():
    # in posts authored in Medium's own editor, <br><br> is an
    # intentional paragraph break, not migration damage: the text stays
    # split (the whitespace-only middle line renders as a blank line)
    md = md_of("<p>But that is not all...<br><br>The SQLite support</p>")
    assert md == "But that is not all...  \n\nThe SQLite support\n"


def test_whitespace_only_lines_become_blank_outside_fences():
    # image grids separate entries with a <br>, which markdownify renders
    # as a line holding only a hard break (two spaces)
    md = md_of('<figure><img src="https://x.com/a.png"/></figure>'
               '<figure><img src="https://x.com/b.png"/></figure>')
    assert not any(l != "" and l.strip() == "" for l in md.split("\n"))


def test_whitespace_lines_inside_fences_are_kept():
    md = md_of("<pre>a = 1<br>  <br>b = 2</pre>")
    assert "\na = 1\n  \nb = 2\n" in md


def test_leading_divider_is_dropped():
    # the divider that followed the removed subtitle block; a body must
    # not open with ---, which also reads as front matter to some tools
    md = md_of("<hr/><p>First real paragraph.</p><hr/><p>Later.</p>")
    assert md == "First real paragraph.\n\n---\n\nLater.\n"


def test_medium_tracking_source_param_is_stripped():
    md = md_of('<a href="https://github.com/x/y?source=post_page-----1a2b'
               '---------------------------------------">repo</a>')
    assert md == "[repo](https://github.com/x/y)\n"


def test_non_medium_source_param_survives():
    md = md_of('<a href="https://example.com/?source=rss&x=1">link</a>')
    assert md == "[link](https://example.com/?source=rss&x=1)\n"


def test_figcaption_renders_italic():
    md = md_of('<figure><img src="https://x.com/a.png"/>'
               '<figcaption>A robot in the browser</figcaption></figure>')
    assert "*A robot in the browser*" in md


def test_already_italic_figcaption_is_not_double_wrapped():
    md = md_of('<figure><img src="https://x.com/a.png"/>'
               '<figcaption><em>Already italic</em></figcaption></figure>')
    assert "*Already italic*" in md and "**" not in md


def test_iframe_embed_link_text_has_no_brackets():
    # the old "[embed: url]" text rendered as [[embed: url]](url)
    md = md_of('<iframe src="https://www.youtube.com/embed/x"></iframe>')
    assert md == ("[embed: https://www.youtube.com/embed/x]"
                  "(https://www.youtube.com/embed/x)\n")


def test_slug_of_percent_decodes():
    # Medium percent-encodes non-ASCII slugs, but its sitemap serves some
    # of the same URLs decoded; one post must get one slug either way
    assert slug_of("https://blog.example.com/caf%C3%A9-menu-0123456789ab") \
        == slug_of("https://blog.example.com/café-menu-0123456789ab") == "café-menu"


def test_byline_avatar_on_custom_subdomain_is_stripped():
    # authors with a custom subdomain have no /@ in the byline href; the
    # source=post_page---byline tag is what marks it as chrome
    html = ('<article><div><div><a href="https://wolfv.medium.com/'
            '?source=post_page---byline--0123456789ab--------">'
            '<img src="https://miro.medium.com/v2/2*avatar.jpeg"/></a></div></div>'
            '<p>Real content.</p></article>')
    body = page_body(BeautifulSoup(html, "html.parser"))
    assert body.find("img") is None
    assert "Real content" in body.get_text()


def test_leading_heading_repeating_the_title_is_dropped():
    # some pages render the post title as a body <h3> instead of the
    # usual <h1>; the title lives in front matter, so drop the repeat
    html = ('<article><h3>My Great Post</h3>'
            '<p>Real content.</p><h3>My Great Post</h3></article>')
    body = page_body(BeautifulSoup(html, "html.parser"), title="My Great Post")
    headings = body.find_all("h3")
    assert len(headings) == 1          # a later repeat is authored content
    assert "Real content" in body.get_text()


def test_leading_heading_that_is_not_the_title_stays():
    html = '<article><h3>Introduction</h3><p>Real content.</p></article>'
    body = page_body(BeautifulSoup(html, "html.parser"), title="My Great Post")
    assert body.find("h3") is not None


def test_empty_app_shell_fails_instead_of_converting_chrome(tmp_path):
    # Medium serves some posts as a bare app shell: nav links, no article
    # markup, no JSON-LD, no title. Long enough to pass the short-body
    # warning, so it must fail outright rather than convert to nav chrome.
    raw = tmp_path / "0123456789ab"
    raw.mkdir()
    (raw / "page.html").write_text(
        "<html><head><title>Medium</title></head><body>"
        '<a href="https://medium.com/m/signin?operation=login">Sign in</a>'
        '<a href="https://medium.com/search">Search</a></body></html>')
    with pytest.raises(RuntimeError, match="empty app shell"):
        convert_post(URL, raw, tmp_path / "posts", prefer_page=False)


def test_external_canonical_does_not_leak_into_link_base():
    # relative body links must resolve against the publication, not the
    # declared canonical (the historical bug: gist.github.com/npmjs.com)
    body = BeautifulSoup('<article><a href="other-post-abcdef123456">x</a></article>',
                         "html.parser")
    post_url, _ = resolve_canonical(URL, "https://gist.github.com/abcdef123456")
    markdown, _ = to_markdown(body, post_url, {}, Path("/nonexistent"))
    assert "https://blog.example.com/other-post-abcdef123456" in markdown


GIST_SCRIPT = ('<figure><script src="https://gist.github.com/ann/'
               'abcdef0123456789abcdef0123456789.js"></script></figure>')


def test_gist_script_becomes_a_link_when_not_archived():
    # export/ghost bodies embed gists as script tags; a script converts
    # to nothing, so keep at least a link to the gist
    md = md_of(GIST_SCRIPT)
    assert md == ("[embed: https://gist.github.com/ann/"
                  "abcdef0123456789abcdef0123456789]"
                  "(https://gist.github.com/ann/"
                  "abcdef0123456789abcdef0123456789)\n")


def test_gist_script_inlines_archived_files():
    body = BeautifulSoup(f"<article>{GIST_SCRIPT}</article>", "html.parser")
    media = {"m1": {"value": {}, "gist": {
        "id": "abcdef0123456789abcdef0123456789",
        "files": {"a.py": {"language": "Python", "content": "x = 1"}}}}}
    markdown, _ = to_markdown(body, URL, {}, Path("/nonexistent"), media=media)
    assert "```python\nx = 1\n```" in markdown
    assert "gist.github.com" not in markdown
