"""ghost_comparable_blocks normalization, mainly fenced-code handling."""

from medium_archive.compare import ghost_comparable_blocks


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
