"""to_markdown fence sizing and canonical-URL resolution."""

from pathlib import Path

from bs4 import BeautifulSoup

from medium_archive.convert import to_markdown
from medium_archive.urls import resolve_canonical

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


def test_external_canonical_does_not_leak_into_link_base():
    # relative body links must resolve against the publication, not the
    # declared canonical (the historical bug: gist.github.com/npmjs.com)
    body = BeautifulSoup('<article><a href="other-post-abcdef123456">x</a></article>',
                         "html.parser")
    post_url, _ = resolve_canonical(URL, "https://gist.github.com/abcdef123456")
    markdown, _ = to_markdown(body, post_url, {}, Path("/nonexistent"))
    assert "https://blog.example.com/other-post-abcdef123456" in markdown
