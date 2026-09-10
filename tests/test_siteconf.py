"""The site's own data as TOML: the writer that documents each key."""

import tomllib

import pytest

from medium_archive.siteconf import (SITE_KEYS, documented_toml, toml_document,
                                     toml_value)


def test_every_documented_key_round_trips_as_its_own_example():
    """The examples are what a reader is shown of a key it has not set,
    so each has to be the thing the key holds -- valid TOML, and read
    back as itself."""
    values = {name: example for name, _, example in SITE_KEYS}
    assert tomllib.loads(documented_toml(values)) == values


def test_an_unset_key_keeps_its_documentation_and_holds_nothing():
    """TOML has no null, so a key the site does not set is written
    commented out: still under its documentation, still showing what it
    would look like set, and read back as absent rather than empty."""
    text = documented_toml({"title": "T", "logo": None})
    assert 'title = "T"' in text
    assert '# logo = "theme/img/logo.svg"' in text
    # the documentation is there whether or not the key is
    assert "a masthead logo that stands in for the site's name" in text
    config = tomllib.loads(text)
    assert config == {"title": "T"}


def test_a_table_is_written_whole_whether_set_or_not():
    """A key whose value is a table (the masthead link, the newsletter
    band) is documented once, above the header, and commented out
    entry by entry when unset -- the header included, which is what
    keeps the rest of the file from being read as part of it."""
    set_text = documented_toml({"title": "T", "newsletter": {"heading": "Hi"}})
    assert "[newsletter]\nheading = \"Hi\"" in set_text
    assert tomllib.loads(set_text)["newsletter"] == {"heading": "Hi"}

    unset = documented_toml({"title": "T"})
    assert "# [newsletter]" in unset and "[newsletter]" not in unset.replace(
        "# [newsletter]", "")
    assert "newsletter" not in tomllib.loads(unset)


def test_tables_are_written_after_the_flat_keys():
    """TOML reads every bare key after a table header as that table's,
    so a site that sets one has to have its flat keys written first --
    whatever order the documented keys come in."""
    text = documented_toml({"logo_link": {"url": "https://example.org"},
                            "title": "T", "noindex": True})
    assert text.index("title = ") < text.index("[logo_link]")
    assert text.index("noindex = ") < text.index("[logo_link]")
    assert tomllib.loads(text)["title"] == "T"


def test_a_key_the_table_does_not_describe_is_still_written():
    """What site.toml's own [hugo.params] adds reaches the file it was
    meant for, after the documented keys and undocumented: only whoever
    added it knows what it is for."""
    text = documented_toml({"title": "T", "motto": "hello",
                            "extras": {"a": 1}})
    config = tomllib.loads(text)
    assert config["motto"] == "hello" and config["extras"] == {"a": 1}


def test_an_omitted_key_is_undocumented_but_never_dropped():
    """`omit` says a file has no place for a key because its engine
    takes it elsewhere -- hugo's title, address and language are
    hugo.toml's. It leaves the documentation out; it does not throw
    away a value that was set anyway."""
    text = documented_toml({"title": "T", "locale": "en"}, omit=("locale",))
    assert "the language of the pages" not in text
    assert tomllib.loads(text)["locale"] == "en"

    unset = documented_toml({"title": "T"}, omit=("locale",))
    assert "locale" not in unset


def test_examples_can_be_overridden_per_site():
    """The examples are the pelican site's resolutions; hugo's images
    sit at another depth, so what it shows of an unset one has to be
    what that exporter would actually write."""
    text = documented_toml({"title": "T"}, examples={"logo": "img/logo.svg"})
    assert '# logo = "img/logo.svg"' in text
    assert "theme/img/logo.svg" not in text


@pytest.mark.parametrize("value", [
    "plain",
    'holds "quotes" and a \\ backslash',
    "a line\nand another",             # multi-line literal
    "ends with a quote'",              # which a literal cannot close on
    "carries ''' itself",              # nor hold the delimiter
    "a tab\there\nand a newline",
    "© 2026 — unicode intact",
])
def test_any_string_a_site_carries_survives_the_writer(value):
    """The blurb and the footer line are Markdown a person wrote, so
    the writer has to carry whatever is in them: the multi-line form is
    for readability and never at the cost of the text."""
    assert tomllib.loads(f"v = {toml_value(value)}") == {"v": value}


def test_a_multi_line_string_is_written_as_one():
    """A Markdown footer of several lines is readable in the file
    rather than a run of \\n escapes."""
    text = toml_value("first\nsecond")
    assert text == "'''\nfirst\nsecond'''"


def test_toml_document_writes_no_documentation():
    """The plain form, for a file nobody reads for documentation: the
    same ordering rule, none of the prose, and no key for a None."""
    text = toml_document({"title": "T", "logo": None, "hugo": {}})
    assert "#" not in text
    assert tomllib.loads(text) == {"title": "T", "hugo": {}}
