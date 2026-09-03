"""ghost_comparable_blocks normalization, mainly fenced-code handling."""

from medium_archive.compare import comparable_lines, ghost_comparable_blocks


def test_fence_hard_breaks_equal_plain_newlines():
    # export <pre> lines used to end "  " (hard breaks); ghost's don't
    a = "intro:\n\n```\nline one  \nline two  \n    indented\n```\n\nafter\n"
    b = "intro:\n\n```\nline one\nline two\n    indented\n```\n\nafter\n"
    assert ghost_comparable_blocks(a) == ghost_comparable_blocks(b)
    assert len(ghost_comparable_blocks(a)) == 3


def test_fence_with_blank_lines_is_one_block():
    assert len(ghost_comparable_blocks("```\na = 1\n\nb = 2\n```\n")) == 1


def test_code_is_not_url_decoded():
    (block,) = ghost_comparable_blocks('```\n"\\b" + name + "="\n```\n')
    assert "+" in block


def test_prose_urls_are_decoded():
    a = "[x](https://e.com/a%20b)\n"
    b = "[x](https://e.com/a+b)\n"
    assert ghost_comparable_blocks(a) == ghost_comparable_blocks(b)


def test_hero_image_stripped():
    assert ghost_comparable_blocks("![](img.png)\n\ntext\n") == ["text"]


def test_hard_break_splits_prose():
    assert ghost_comparable_blocks("one  \ntwo\n") == ["one", "two"]


def test_unterminated_fence_reaches_end():
    assert ghost_comparable_blocks("text\n\n```\ncode\n") == ["text", "``` code"]


def test_fence_language_is_not_a_page_export_difference():
    # only the state conversion knows fence languages (codeBlockMetadata)
    assert comparable_lines("```python\nx = 1\n```\n") == \
        comparable_lines("```\nx = 1\n```\n")


def test_fence_language_is_not_a_ghost_difference():
    assert ghost_comparable_blocks("```js\ncode\n```\n") == \
        ghost_comparable_blocks("```\ncode\n```\n")


def test_comparable_lines_drop_player_titles():
    # only the state conversion knows a video's title; the player line
    # agrees between sources once the title is set aside
    from medium_archive.compare import comparable_lines
    a = '<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk" title="A talk" width="560"></iframe>'
    b = a.replace('title="A talk"', 'title="YouTube video"')
    assert comparable_lines(a) == comparable_lines(b)
    assert comparable_lines(a)[0].startswith('<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk" title=""')
