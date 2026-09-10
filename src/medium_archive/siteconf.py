"""The site's own data: every key it can carry, what each one is for,
and the writer that puts that documentation into the file beside the
value it explains.

Three files hold this data, at two resolutions. The archive's
hand-written `site/site.toml` is the input, read by every exporter
(load_site_inputs). Each exporter then writes its engine's own copy,
resolved for the site it built -- the images as the copies that site
carries, and what several keys together come to (the profile list, the
masthead link's label, the newsletter band's defaults) written out as
what it came to: `site.toml` beside the pelican site's pelicanconf.py,
`config/_default/params.toml` in the hugo site's config directory.
Those two are generated, but a name, a mark or a blurb is exactly what
a checked-in copy of a site corrects by hand, so each key is written
with its documentation above it and the config that reads it holds
none of its own -- pelicanconf.py and hugo.toml are machinery, and say
so.

That is what the file is TOML for. A comment is the whole point and
JSON has none; and TOML, unlike YAML, retypes nothing a hand-editor
writes -- the `twitter` handle opens with `@`, which YAML reserves as
an indicator, and pyyaml reads a bare `no` locale (Norwegian) as
false. What TOML lacks is null, which suits the file better than the
`null`s it replaces: an unset key is written commented out, under the
same documentation and beside an example of what it would hold, so the
file is still the list of what there is to set and now says what each
one would look like set. Every reader takes an absent key as unset
already.
"""

import json
import textwrap
import tomllib
from pathlib import Path

# How wide a `# ` comment line is allowed to run.
COMMENT_WIDTH = 72

# Every key the site's data can carry, in the order it is written, as
# (name, what it is for, an example of it set). The documentation is
# here once and reaches every file that carries the key -- both
# exporters' copies, and neither engine's config -- so the two sites
# cannot come to describe the same key differently. A key whose value
# is a table (logo_link, newsletter) is written after the flat ones,
# which is TOML's own ordering rule, and the writer sees to that.
#
# The examples are the pelican site's resolutions, that being the file
# that carries every key; hugo's copy overrides the few that differ
# (its images sit at another depth), and passes over the keys its
# engine takes elsewhere -- the site's name, address and language are
# hugo.toml's, and its landing-page blurb is content/_index.md.
SITE_KEYS = (
    ("title",
     "the publication's name: the masthead beside the avatar (unless a "
     "logo stands in for it), the end of every page's title, and the "
     "title of the feeds.",
     "My Blog"),
    ("description",
     "one line on what the publication is: under the name in the "
     "masthead, in the feeds, and the description a search result or a "
     "shared link is summarised with.",
     "News, releases and community stories."),
    ("base_url",
     "the address this site is served from, without the trailing slash "
     "Pelican does not want: what every absolute link is built against "
     "-- the feeds, the redirect stubs, the Open Graph tags, and the "
     "share links a reader hands to LinkedIn or Facebook.",
     "https://blog.example.org"),
    ("locale",
     "the language of the pages, as <html lang> and in the feeds.",
     "en"),
    ("intro",
     "the landing-page blurb, Markdown: the paragraph above the first "
     "row of cards.",
     "News and releases from [the project](https://example.org)"),
    ("footer",
     "the line under every page, Markdown. `{year}` in it becomes the "
     "year the site is built, so a copyright notice stays current.",
     "© {year} The Example Foundation"),
    ("avatar",
     "the small round mark beside the site's name in the header, and "
     "the publisher's logo in every page's structured data.",
     "theme/img/avatar.svg"),
    ("favicon",
     "the browser-tab icon.",
     "theme/favicon.svg"),
    ("logo",
     "a masthead logo that stands in for the site's name -- a wordmark, "
     "the way jupyter.org's navbar carries its rectangle logo. With one "
     "set the header shows it instead of the avatar and the name.",
     "theme/img/logo.svg"),
    ("logo_dark",
     "the same mark drawn for the dark palette.",
     "theme/img/logo-dark.svg"),
    ("announcement",
     "a site-wide banner above the header: an http(s) URL the theme "
     "fetches client-side (empty content hides the banner, like Sphinx "
     "themes' html announcement option), or literal HTML.",
     "https://example.org/assets/banner.html"),
    ("twitter",
     "the publication's @handle, credited on links shared to X/Twitter.",
     "@example"),
    ("profiles",
     "the publication's addresses elsewhere (the X/Twitter profile the "
     "handle above names among them): the Organization's sameAs in "
     "every page's structured data.",
     ["https://example.org", "https://x.com/example"]),
    ("share_image",
     "the og:image of a page with no cover of its own.",
     "theme/img/share.png"),
    ("share_image_size",
     "its pixel size, which the theme has no image pipeline to measure.",
     [1200, 630]),
    ("cover_size",
     "the size the card covers were baked to, or unset when they kept "
     "their source size (the exporter having been run without Pillow).",
     [640, 360]),
    ("noindex",
     "keep search engines off this deployment (a preview): a noindex "
     "robots tag on every page, and a robots.txt that disallows all.",
     True),
    ("redirects",
     "what this site does about old inbound links. \"stubs\" is a "
     "meta-refresh stub page at every old path, which works on any "
     "static host and is the only mechanism GitHub Pages has; \"file\" "
     "is a `_redirects` file at the site root, which Netlify, "
     "Cloudflare Pages and their imitators answer with a real HTTP 301 "
     "and GitHub Pages ignores; \"both\" is both, \"none\" neither. "
     "redirects.csv, the map both are rendered from, is written either "
     "way.",
     "both"),
    ("logo_link",
     "where the masthead points when the mark on it stands for "
     "something larger than the blog -- the address, and the name the "
     "link reads under. Unset, the masthead points at the site's own "
     "home.",
     {"url": "https://example.org", "label": "example.org"}),
    ("newsletter",
     "the signup band at the foot of every page: its heading and the "
     "ids of the HubSpot form it embeds. Unset, there is no band.",
     {"heading": "Subscribe for updates", "hubspot_portal": "1234567",
      "hubspot_form": "00000000-0000-0000-0000-000000000000",
      "hubspot_region": "na1"}),
)


def load_toml(path: Path) -> dict:
    """A TOML file as a dict."""
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def toml_value(value) -> str:
    """One TOML scalar, array or inline table. Scalars and arrays go
    through JSON, whose syntax for them TOML shares exactly (its basic
    strings take JSON's escapes, and `\\/` is the one JSON escape TOML
    lacks and json.dumps never writes); a string holding newlines is
    written as a multi-line literal instead, so a Markdown footer or
    blurb stays readable rather than becoming a run of `\\n`."""
    if isinstance(value, str) and "\n" in value and _literal_safe(value):
        return f"'''\n{value}'''"
    if isinstance(value, dict):
        inner = ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items())
        return f"{{ {inner} }}"
    return json.dumps(value, ensure_ascii=False)


def _literal_safe(value: str) -> bool:
    """Whether a multi-line literal string can carry this text as it is:
    no delimiter inside it, no trailing quote to run into the closing
    one, and no control character a literal may not hold (a tab may)."""
    return ("'''" not in value and not value.endswith("'")
            and not any(ch < " " and ch not in "\n\t" for ch in value))


def comment(text: str) -> str:
    """Prose as `# ` lines, wrapped, blank-line-separated paragraphs
    kept apart by a bare `#`."""
    return "\n#\n".join(
        textwrap.fill(para, width=COMMENT_WIDTH,
                      initial_indent="# ", subsequent_indent="# ")
        for para in text.split("\n\n"))


def _assignment(name, value) -> str:
    """One key as TOML: a table header and a line per entry when the
    value is a table, otherwise the one `name = value` line."""
    if isinstance(value, dict):
        return "\n".join([f"[{name}]"] + [f"{k} = {toml_value(v)}"
                                          for k, v in value.items()])
    return f"{name} = {toml_value(value)}"


def _entry(name, value, doc, example) -> str:
    """One documented key: its prose, then the key itself -- set, or,
    where the site does not set it, commented out and holding the
    example of it set that stands in for the null TOML has no word
    for."""
    if value is None:
        body = "\n".join("# " + line for line
                         in _assignment(name, example).splitlines())
    else:
        body = _assignment(name, value)
    return comment(doc) + "\n" + body


def toml_document(values: dict) -> str:
    """A dict as plain TOML, with nothing said about what any of it is
    for: flat keys first and then a table per dict value, which is
    TOML's own ordering rule. What writes a file nobody reads for
    documentation -- a test's input, a scratch config."""
    flat = [_assignment(name, value) for name, value in values.items()
            if value is not None and not isinstance(value, dict)]
    tables = [_assignment(name, value) for name, value in values.items()
              if isinstance(value, dict)]
    return "\n".join(flat + tables) + "\n"


def documented_toml(values: dict, examples=None, omit=()) -> str:
    """The site's data as TOML, every key under its own documentation.

    `values` is what this site came to; a key missing from it (or None)
    is one the site does not set, written commented out beside its
    example. `examples` overrides those examples where a site resolves
    a key differently from the pelican one SITE_KEYS is written for,
    and `omit` names the keys a file does not carry at all because its
    engine takes them somewhere else. A key in `values` that SITE_KEYS
    does not describe -- what site.toml's own [hugo.params] adds -- is
    written after the documented ones and undocumented, only whoever
    added it knowing what it is for.
    """
    examples = examples or {}
    described = [(name, doc, examples.get(name, example))
                 for name, doc, example in SITE_KEYS if name not in omit]
    entries = [(name, values.get(name),
                _entry(name, values.get(name), doc, example))
               for name, doc, example in described]
    # a value the table does not describe here -- one [hugo.params]
    # added, or one this file documents nowhere because its engine
    # takes it elsewhere and it was set anyway -- is still written,
    # after the documented keys and without documentation
    named = {name for name, _, _ in described}
    entries += [(name, value, _assignment(name, value))
                for name, value in values.items()
                if name not in named and value is not None]
    # flat keys before the first table header, as TOML requires. An
    # unset key is a run of comments whatever its shape, so only a
    # table this site actually sets has to move.
    flat = [text for _, value, text in entries if not isinstance(value, dict)]
    tables = [text for _, value, text in entries if isinstance(value, dict)]
    return "\n\n".join(flat + tables) + "\n"
