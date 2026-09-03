"""to_markdown fence sizing, canonical-URL resolution, page chrome and
title removal."""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from medium_archive.convert import convert_post, to_markdown
from medium_archive.images import sniff_image_ext
from medium_archive.pages import collapse_br_pairs, extract_metadata, page_body
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


def test_captioned_figure_keeps_its_shell():
    # the caption stays associated with its picture: the shell tags go
    # out as blank-line-separated raw HTML blocks, so CommonMark
    # renderers still process the image and caption Markdown between
    # them -- and the caption carries no styling markup: like Medium,
    # the sites style figcaption with CSS
    md = md_of('<figure><img src="https://x.com/a.png"/>'
               '<figcaption>A robot in the browser</figcaption></figure>')
    assert md == ("<figure>\n\n![](https://x.com/a.png)\n\n"
                  "<figcaption>\n\nA robot in the browser\n\n"
                  "</figcaption>\n\n</figure>\n")


def test_uncaptioned_figure_gets_no_shell():
    md = md_of('<figure><img src="https://x.com/a.png"/></figure>')
    assert "figure" not in md


def test_caption_without_content_to_caption_stays_plain():
    # some captures never hydrate the figure's image element
    md = md_of("<figure><figcaption>Orphan caption</figcaption></figure>")
    assert md == "*Orphan caption*\n"


def test_captioned_embed_keeps_its_shell():
    md = md_of('<figure><iframe src="https://youtu.be/x"></iframe>'
               "<figcaption>Watch it</figcaption></figure>")
    assert md == ("<figure>\n\n[embed: https://youtu.be/x](https://youtu.be/x)"
                  "\n\n<figcaption>\n\nWatch it\n\n</figcaption>\n\n"
                  "</figure>\n")


def test_already_italic_figcaption_is_not_double_wrapped():
    md = md_of('<figure><img src="https://x.com/a.png"/>'
               '<figcaption><em>Already italic</em></figcaption></figure>')
    assert "*Already italic*" in md and "**" not in md


def test_iframe_embed_link_text_has_no_brackets():
    # the old "[embed: url]" text rendered as [[embed: url]](url)
    md = md_of('<iframe src="https://www.youtube.com/embed/x"></iframe>')
    assert md == ("[embed: https://www.youtube.com/embed/x]"
                  "(https://www.youtube.com/embed/x)\n")


YT = ("https://www.youtube-nocookie.com/embed/abcdefghijk", 'width="560" height="315" '
      'style="aspect-ratio: 560 / 315" loading="lazy" allow="accelerometer; '
      'clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
      'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen')


def test_youtube_video_recognizes_every_url_form():
    from medium_archive.convert import youtube_video
    for url in ("https://www.youtube.com/watch?v=abcdefghijk",
                "http://youtube.com/watch?v=abcdefghijk&feature=x",
                "https://m.youtube.com/watch?v=abcdefghijk",
                "https://www.youtube.com/embed/abcdefghijk?feature=oembed",
                "https://www.youtube-nocookie.com/embed/abcdefghijk",
                "https://youtu.be/abcdefghijk",
                "https://www.youtube.com/v/abcdefghijk",
                "https://www.youtube.com/shorts/abcdefghijk",
                "https://www.youtube.com/live/abcdefghijk"):
        assert youtube_video(url) == ("abcdefghijk", None), url
    assert youtube_video("https://youtu.be/abcdefghijk?t=4m15s") == ("abcdefghijk", 255)
    assert youtube_video("https://www.youtube.com/watch?v=abcdefghijk&t=90") == ("abcdefghijk", 90)
    assert youtube_video("https://www.youtube.com/watch?v=abcdefghijk&t=90s") == ("abcdefghijk", 90)
    assert youtube_video("https://www.youtube.com/embed/abcdefghijk?start=7") == ("abcdefghijk", 7)
    assert youtube_video("https://www.youtube.com/watch?v=abcdefghijk&t=0") == ("abcdefghijk", None)
    for url in ("https://vimeo.com/123", "https://www.youtube.com/",
                "https://www.youtube.com/embed/videoseries?list=PL1",
                "https://www.youtube.com/playlist?list=PL1",
                "https://www.youtube.com/watch?v=short",
                "https://twitter.com/youtube.com/status/1"):
        assert youtube_video(url) is None, url


def test_youtube_iframe_stays_a_player():
    # the archive has the video's URL, and the player is the content: one
    # canonical iframe line on the no-cookie host, lazily loaded, with a
    # title for assistive tech (the export iframe has none)
    md = md_of('<p>See:</p><iframe src="https://www.youtube.com/embed/abcdefghijk'
               '?feature=oembed" width="700" height="393" frameborder="0"></iframe>')
    assert md == (f'See:\n\n<iframe src="{YT[0]}" title="YouTube video" {YT[1]}>'
                  "</iframe>\n")
    # the state's title and a start time carry over; quotes are escaped
    md = md_of('<iframe src="https://youtu.be/abcdefghijk?t=1m" '
               'title="A &quot;talk&quot;"></iframe>')
    assert md == (f'<iframe src="{YT[0]}?start=60" title="A &quot;talk&quot;" '
                  f"{YT[1]}></iframe>\n")
    # any other iframe is still the link
    assert md_of('<iframe src="https://example.com/v/1"></iframe>') == (
        "[embed: https://example.com/v/1](https://example.com/v/1)\n")


def test_captioned_youtube_embed_keeps_its_shell():
    md = md_of('<figure><iframe src="https://youtu.be/abcdefghijk"></iframe>'
               "<figcaption>Watch it</figcaption></figure>")
    assert md == (f'<figure>\n\n<iframe src="{YT[0]}" title="YouTube video" '
                  f"{YT[1]}></iframe>\n\n<figcaption>\n\nWatch it\n\n"
                  "</figcaption>\n\n</figure>\n")


def test_iframe_without_a_source_becomes_a_missing_embed_placeholder():
    # a feed body renders a gist as <iframe src="" width="0" height="0">;
    # a link with no target would read as a dangling "embed:", so it gets
    # the placeholder the state conversion uses, which lint flags
    md = md_of('<p>Before.</p><iframe src="" width="0" height="0"></iframe>'
               "<p>After.</p>")
    assert md.replace("\\[", "[") == "Before.\n\n[missing embed]\n\nAfter.\n"


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


def test_bin_image_gets_sniffed_extension(tmp_path):
    # an image fetched from an extensionless URL is stored as .bin in
    # raw/; its derived copy carries the extension its bytes call for
    (tmp_path / "images").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "out2").mkdir()
    (tmp_path / "images" / "001-x.bin").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
    body = BeautifulSoup('<div><img src="https://miro.medium.com/x"></div>',
                         "html.parser")
    md, used = to_markdown(body, "https://blog.example.com",
                           {"https://miro.medium.com/x": "001-x.bin"},
                           tmp_path, tmp_path / "out")
    assert "images/001-x.png" in md
    assert used == ["images/001-x.png"]
    assert (tmp_path / "out" / "images" / "001-x.png").exists()
    # unrecognized bytes keep the .bin name rather than lying
    (tmp_path / "images" / "002-y.bin").write_bytes(b"not an image")
    body = BeautifulSoup('<div><img src="https://miro.medium.com/y"></div>',
                         "html.parser")
    md, used = to_markdown(body, "https://blog.example.com",
                           {"https://miro.medium.com/y": "002-y.bin"},
                           tmp_path, tmp_path / "out2")
    assert used == ["images/002-y.bin"]


@pytest.mark.parametrize("head", [
    b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">',
    b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg">',
    b'\xef\xbb\xbf<?xml version="1.0"?>\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"\n'
    b' "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<!-- badge -->\n<svg>',
])
def test_sniff_image_ext_recognizes_svg(tmp_path, head):
    # Medium re-hosts badge images (shields.io and the like) as SVG
    # under extensionless URLs; the text has no magic bytes to match
    (tmp_path / "x.bin").write_bytes(head + b"</svg>\n")
    assert sniff_image_ext(tmp_path / "x.bin") == ".svg"


def test_sniff_image_ext_rejects_other_xml(tmp_path):
    (tmp_path / "x.bin").write_bytes(b'<?xml version="1.0"?><html><svg/></html>')
    assert sniff_image_ext(tmp_path / "x.bin") is None
    (tmp_path / "y.bin").write_bytes(b"<svgfoo>")
    assert sniff_image_ext(tmp_path / "y.bin") is None

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


def medium_page(*, og_description=None, ld_description=None,
                meta_description=None, title="Widgets for everyone") -> str:
    """A Medium post page carrying the summary tags a test cares about."""
    tags = [f'<meta property="og:title" content="{title}" />']
    if og_description is not None:
        tags.append(f'<meta property="og:description" content="{og_description}" />')
    if meta_description is not None:
        tags.append(f'<meta name="description" content="{meta_description}" />')
    ld = {"@type": "NewsArticle", "headline": title,
          "datePublished": "2020-01-02T03:04:05.000Z"}
    if ld_description is not None:
        ld["description"] = ld_description
    tags.append('<script type="application/ld+json">'
                f"{json.dumps(ld)}</script>")
    return (f'<html><head><link rel="canonical" href="{URL}" />'
            + "".join(tags) + "</head><body><article>"
            "<h1>Widgets for everyone</h1><p>Real content.</p>"
            "</article></body></html>")


def test_truncated_headline_is_completed_from_the_title_heading():
    # the JSON-LD headline and og:title carry Medium's ellipsis-cut title;
    # the rendered <h1> has the whole of it
    full = ("Exploring Petabytes of the Night Sky: Notebooks at the "
            "Astro Data Lab Science Platform")
    cut = ("Exploring Petabytes of the Night Sky: Notebooks at the "
           "Astro Data Lab Science\u2026")
    html = medium_page(title=cut).replace(
        "<h1>Widgets for everyone</h1>",
        f'<h1 data-testid="storyTitle">{full}</h1>')
    soup = BeautifulSoup(html, "html.parser")
    assert extract_metadata(soup, URL)["title"] == full
    # an <h1> that isn't the headline's continuation leaves it alone
    soup = BeautifulSoup(medium_page(title=cut), "html.parser")
    assert extract_metadata(soup, URL)["title"] == cut


def test_page_body_drops_a_heading_repeating_a_truncated_title():
    soup = BeautifulSoup(
        "<article><h3>The whole title of the post</h3><p>Body.</p></article>",
        "html.parser")
    body = page_body(soup, title="The whole title of the\u2026")
    assert body.find("h3") is None
    assert body.get_text(strip=True) == "Body."


def described(**kwargs) -> str:
    soup = BeautifulSoup(medium_page(**kwargs), "html.parser")
    return extract_metadata(soup, URL)["description"]


def test_description_drops_the_title_medium_repeats():
    # Medium writes its summary as "<title> <excerpt>" and caps it; the
    # description is the excerpt alone, which og:description carries
    assert described(
        og_description="We shipped it, and here is what it does for you.",
        ld_description="Widgets for everyone We shipped it, and here is what it",
        meta_description="Widgets for everyone We shipped it, and here is what it",
    ) == "We shipped it, and here is what it does for you."


def test_title_is_dropped_from_whichever_summary_is_used():
    # no og:description: the JSON-LD text serves, minus the repeat
    assert described(
        ld_description="Widgets for everyone. We shipped it.",
        meta_description="Widgets for everyone. We shipped it.",
    ) == "We shipped it."


def test_title_leading_the_open_graph_summary_is_dropped_too():
    # older posts open with the title in the body, so it leads the
    # excerpt Medium built from that body
    assert described(
        og_description="Widgets for everyone We shipped it.",
    ) == "We shipped it."


def test_summary_that_is_only_the_title_falls_through():
    # a post titled with its own first sentence: og:description repeats
    # it exactly and would strip to nothing, so the next summary serves
    assert described(
        og_description="Widgets for everyone",
        meta_description="Widgets for everyone We shipped it.",
    ) == "We shipped it."


def test_summary_that_only_resembles_the_title_is_kept():
    # the shared opening words are not a repeat: the title is not a
    # prefix of this sentence, which takes its own turn after them
    assert described(
        title="Widgets for everyone 2016",
        og_description="Widgets for everyone is a one-day workshop.",
    ) == "Widgets for everyone is a one-day workshop."


def test_truncated_title_leaves_the_summary_alone():
    # there is no telling where an ellipsis-truncated title ended, so
    # cutting it would strand its tail at the front of the description
    soup = BeautifulSoup(medium_page(
        title="Widgets for everyone, and for every…",
        og_description="Widgets for everyone, and for every kind of work.",
    ), "html.parser")
    assert extract_metadata(soup, URL)["description"] \
        == "Widgets for everyone, and for every kind of work."


def test_converted_front_matter_description_has_no_title(tmp_path):
    raw = tmp_path / "0123456789ab"
    raw.mkdir()
    (raw / "page.html").write_text(medium_page(
        og_description="Widgets for everyone  We shipped it."))
    front = convert_post(URL, raw, tmp_path / "posts", prefer_page=True)
    assert front["title"] == "Widgets for everyone"
    assert front["description"] == "We shipped it."


def test_json_ld_authors_one_or_many():
    from medium_archive.pages import ld_authors
    # schema.org allows one Person or a list, each a dict or a bare name
    assert ld_authors({"author": {"name": "Ann", "url": "https://medium.com/@ann"}}) \
        == [{"name": "Ann", "url": "https://medium.com/@ann"}]
    assert ld_authors({"author": [{"name": "Ann"}, "Bo", {"url": "x"}]}) \
        == [{"name": "Ann", "url": None}, {"name": "Bo", "url": None}]
    assert ld_authors({}) == []
    # a page without JSON-LD falls back to the author meta tag
    soup = BeautifulSoup('<html><head><meta name="author" content="Cy">'
                         '</head><body></body></html>', "html.parser")
    assert extract_metadata(soup, URL)["authors"] == [{"name": "Cy", "url": None}]


def test_feed_item_authors_reads_the_old_single_author_form():
    from medium_archive.convert import feed_item_authors
    # raw/ is never rewritten: feed items saved before authors became a
    # list carry one name under `author`
    assert feed_item_authors({"author": "Ann"}) == [{"name": "Ann", "url": None}]
    assert feed_item_authors({"authors": [{"name": "Ann", "url": None}],
                              "author": "ignored"}) == [{"name": "Ann", "url": None}]
    assert feed_item_authors({"author": ""}) == []


GIPHY_GIF = "https://media.giphy.com/media/fWgAW7WZtPMBjmpa3V/giphy.gif"
GIPHY_MP4 = "https://media.giphy.com/media/Ri327iDKuC4pnExM4L/giphy.mp4"


def test_giphy_media_recognizes_files_and_pages():
    from medium_archive.images import giphy_media
    assert giphy_media(GIPHY_GIF) == GIPHY_GIF
    assert giphy_media(GIPHY_MP4) == GIPHY_MP4
    assert giphy_media(GIPHY_GIF + "?cid=abc#x") == GIPHY_GIF
    assert giphy_media("https://media2.giphy.com/media/v1.Y2lkPTc5/abc123/giphy.webp") \
        == "https://media2.giphy.com/media/v1.Y2lkPTc5/abc123/giphy.webp"
    assert giphy_media("https://giphy.com/embed/fWgAW7WZtPMBjmpa3V/twitter/iframe") == GIPHY_GIF
    assert giphy_media("https://giphy.com/gifs/cbc-see-ya-kiss-fWgAW7WZtPMBjmpa3V") == GIPHY_GIF
    for url in ("", "https://www.youtube.com/watch?v=abcdefghijk",
                "https://giphy.com/", "https://media.giphy.com/media/x/page.html"):
        assert giphy_media(url) is None, url


def test_giphy_embed_becomes_the_archived_file(tmp_path):
    # the fetch step maps the gif and the mp4 like any image; convert
    # serves the gif as an image and the mp4 as a looping clip, copied
    # beside the post, with Giphy's page-title noise trimmed from the alt
    raw = tmp_path / "raw"
    (raw / "images").mkdir(parents=True)
    (raw / "images" / "001-giphy.gif").write_bytes(b"GIF89a")
    (raw / "images" / "002-giphy.mp4").write_bytes(b"mp4")
    img_map = {GIPHY_GIF: "001-giphy.gif", GIPHY_MP4: "002-giphy.mp4"}
    out = tmp_path / "post"
    out.mkdir()
    html = (f'<iframe src="{GIPHY_GIF}" title="See Ya Kiss GIF by CBC - Find &amp; '
            f'Share on GIPHY"></iframe><figure><iframe src="{GIPHY_MP4}"></iframe>'
            "<figcaption>Robot arm</figcaption></figure>")
    body = BeautifulSoup(f"<article>{html}</article>", "html.parser")
    md, used = to_markdown(body, URL, img_map, raw, out)
    assert md == ("![See Ya Kiss GIF by CBC](images/001-giphy.gif)\n\n"
                  "<figure>\n\n<video src=\"images/002-giphy.mp4\" autoplay loop "
                  "muted playsinline></video>\n\n<figcaption>\n\nRobot arm\n\n"
                  "</figcaption>\n\n</figure>\n")
    assert used == ["images/002-giphy.mp4", "images/001-giphy.gif"]
    assert (out / "images" / "002-giphy.mp4").read_bytes() == b"mp4"
    # not fetched yet: the file is served from Giphy, which lint reports
    md, used = to_markdown(BeautifulSoup(f"<article>{html}</article>", "html.parser"),
                           URL, {}, raw, out)
    assert f"![See Ya Kiss GIF by CBC]({GIPHY_GIF})" in md
    assert f'<video src="{GIPHY_MP4}" autoplay' in md and used == []


TWEET = "https://twitter.com/ann/status/12345"
OEMBED = {
    "url": "https://twitter.com/ann/status/12345",
    "author_name": "Ann Author", "author_url": "https://twitter.com/ann",
    "html": "<blockquote class=\"twitter-tweet\"><p lang=\"en\" dir=\"ltr\">Hello "
            "<a href=\"https://e.com/x?ref_src=twsrc%5Etfw\">world</a><br>second line "
            "<a href=\"https://t.co/abc\">pic.twitter.com/abc</a></p>&mdash; Ann Author (@ann) "
            "<a href=\"https://twitter.com/ann/status/12345?ref_src=twsrc%5Etfw\">May 1, 2020</a>"
            "</blockquote>\n", "type": "rich", "version": "1.0"}
TWEET_MD = ("> Hello [world](https://e.com/x)  \n> second line [pic.twitter.com/abc]"
            "(https://t.co/abc)\n>\n> \u2014 [Ann Author (@ann)](https://twitter.com/ann), "
            "[May 1, 2020](https://twitter.com/ann/status/12345)\n")


def test_tweet_id_parses_twitter_and_x_urls():
    from medium_archive.urls import tweet_id
    for url in (TWEET, "https://x.com/ann/status/12345", "https://mobile.twitter.com/ann/statuses/12345",
                TWEET + "?ref_src=twsrc%5Etfw"):
        assert tweet_id(url) == ("12345", "ann"), url
    assert tweet_id("https://twitter.com/i/web/status/12345") == ("12345", None)
    for url in ("", "https://twitter.com/ann", "https://e.com/ann/status/1",
                "https://twitter.com/ann/likes"):
        assert tweet_id(url) is None, url


def test_archived_tweet_renders_as_a_quote():
    # the oEmbed payload's text, links (Twitter's ref_src tracking
    # dropped), line breaks, author and dated link, as Markdown
    media = {"tweet:12345": {"tweet": OEMBED}}
    body = BeautifulSoup(f'<article><iframe src="{TWEET}"></iframe></article>', "html.parser")
    md, _ = to_markdown(body, URL, {}, Path("/nonexistent"), media=media)
    assert md == TWEET_MD
    # the export's widget markup, a blockquote holding only the link,
    # takes the same path; without the archived tweet it is the link
    widget = (f'<blockquote class="twitter-tweet"><a href="{TWEET}"></a></blockquote>'
              '<script async src="https://platform.twitter.com/widgets.js"></script>')
    body = BeautifulSoup(f"<article>{widget}</article>", "html.parser")
    md, _ = to_markdown(body, URL, {}, Path("/nonexistent"), media=media)
    assert md == TWEET_MD
    assert md_of(widget) == f"[embed: {TWEET}]({TWEET})\n"
    # a quote that already carries the tweet's text is left alone
    assert md_of(f'<blockquote class="twitter-tweet"><p>Said.</p><a href="{TWEET}">x</a>'
                 "</blockquote>").startswith("> Said.")


def test_load_media_reads_archived_tweets(tmp_path):
    from medium_archive.convert import load_media
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "tweet-12345.json").write_text(json.dumps(OEMBED))
    assert load_media(tmp_path) == {"tweet:12345": {"tweet": OEMBED}}


def test_provider_embed_derives_the_players_url():
    from medium_archive.convert import provider_embed
    art = "https://art19.com/shows/living-corporate/episodes/ce2c3fe2-9eb5"
    assert provider_embed(art) == art + "/embed"
    assert provider_embed(art, art + "/embed?theme=x") == art + "/embed?theme=x"
    assert provider_embed("https://carbon.now.sh/PaDDn2ZszZUVmuhvRP52") == \
        "https://carbon.now.sh/embed/PaDDn2ZszZUVmuhvRP52"
    assert provider_embed("https://vimeo.com/76979871") == "https://player.vimeo.com/video/76979871"
    assert provider_embed("https://player.vimeo.com/video/1?h=2") == "https://player.vimeo.com/video/1?h=2"
    assert provider_embed("https://codepen.io/ann/pen/AbCdEf") == "https://codepen.io/ann/embed/AbCdEf"
    assert provider_embed("https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk") == \
        "https://open.spotify.com/embed/episode/4rOoJ6Egrf8K2IrywzwOMk"
    assert provider_embed("https://soundcloud.com/ann/a-track") == \
        "https://w.soundcloud.com/player/?url=https://soundcloud.com/ann/a-track"
    for url in ("https://twitter.com/a/status/1", "https://example.com/x",
                "https://art19.com/shows/living-corporate", "https://vimeo.com/about", ""):
        assert provider_embed(url) is None, url


def test_provider_player_stays_an_iframe_at_its_own_size():
    # the state's title, embed form and size carry over; an export iframe
    # on the provider's host is kept as it is; a stranger stays a link
    md = md_of('<iframe src="https://art19.com/shows/lc/episodes/ce2c" title="Ep. 248" '
               'data-embed="https://art19.com/shows/lc/episodes/ce2c/embed" '
               'width="720" height="200"></iframe>')
    assert md == ('<iframe src="https://art19.com/shows/lc/episodes/ce2c/embed" title="Ep. 248" '
                  'width="720" height="200" style="aspect-ratio: 720 / 200" loading="lazy" '
                  "allowfullscreen></iframe>\n")
    md = md_of('<iframe src="https://carbon.now.sh/embed/PaDDn2ZszZUVmuhvRP52?"></iframe>')
    assert md.startswith('<iframe src="https://carbon.now.sh/embed/PaDDn2ZszZUVmuhvRP52" '
                         'title="Embedded content from carbon.now.sh" width="560"')
    assert md_of('<iframe src="https://example.com/player/1"></iframe>') == (
        "[embed: https://example.com/player/1](https://example.com/player/1)\n")


def test_carbon_id_parses_page_and_embed_urls():
    from medium_archive.urls import carbon_id
    for url in ("https://carbon.now.sh/PaDDn2ZszZUVmuhvRP52",
                "https://carbon.now.sh/embed/PaDDn2ZszZUVmuhvRP52?",
                "https://carbon.now.sh/embed/PaDDn2ZszZUVmuhvRP52/"):
        assert carbon_id(url) == "PaDDn2ZszZUVmuhvRP52", url
    for url in ("", "https://carbon.now.sh/", "https://carbon.now.sh/about",
                "https://example.com/PaDDn2ZszZUVmuhvRP52"):
        assert carbon_id(url) is None, url


def test_archived_carbon_snippet_becomes_a_code_block():
    # the snippet's own code and language, in place of its screenshot;
    # Carbon's "auto" language stays a bare fence
    media = {"carbon:PaDDn2ZszZUVmuhvRP52": {"carbon": {
        "language": "python", "code": "class ExampleWidget(DOMWidget):\n    value = 1"}}}
    body = BeautifulSoup('<article><iframe src="https://carbon.now.sh/PaDDn2ZszZUVmuhvRP52" '
                         'data-embed="https://carbon.now.sh/embed/PaDDn2ZszZUVmuhvRP52?" '
                         'width="1024" height="480"></iframe></article>', "html.parser")
    md, _ = to_markdown(body, URL, {}, Path("/nonexistent"), media=media)
    assert md == "```python\nclass ExampleWidget(DOMWidget):\n    value = 1\n```\n"
    from medium_archive.convert import carbon_language
    assert carbon_language("text/typescript-jsx") == "tsx"
    assert carbon_language("text/x-java") == "java"
    assert carbon_language("text/x-rustsrc") == "rust"
    assert carbon_language("text/x-unknownsrc") == "unknownsrc"
    assert carbon_language("Python") == "python"
    assert carbon_language("auto") == "" and carbon_language(None) == ""
    media["carbon:PaDDn2ZszZUVmuhvRP52"]["carbon"]["language"] = "auto"
    body = BeautifulSoup('<article><iframe src="https://carbon.now.sh/PaDDn2ZszZUVmuhvRP52">'
                         "</iframe></article>", "html.parser")
    md, _ = to_markdown(body, URL, {}, Path("/nonexistent"), media=media)
    assert md.startswith("```\nclass ExampleWidget")


def test_load_media_reads_carbon_snippets(tmp_path):
    from medium_archive.convert import load_media
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "carbon-abc").with_suffix(".json").write_text(
        json.dumps({"language": "python", "code": "x = 1"}))
    assert load_media(tmp_path) == {"carbon:abc": {"carbon": {"language": "python", "code": "x = 1"}}}
