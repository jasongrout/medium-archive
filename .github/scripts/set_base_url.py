#!/usr/bin/env python3
"""Point a site.toml's base_url at one preview deployment's subpath, and
mark the deployment a preview.

Used by the preview workflow before each site exporter runs, so every
absolute URL a generator bakes in lands under that site's directory of
the GitHub Pages deployment. The previews are three complete copies of
the archive that search engines could otherwise index ahead of, and
then alongside, the real site, so `noindex` is set too: every page of
a preview carries a noindex robots tag and its robots.txt disallows
crawling. `plausible` goes the other way and is dropped rather than
set: a preview is not the site, so its visits are not the site's
either, and counting them would report three copies of every page
against the real blog's stats. Patches the file in place; the workflow
never commits the change.

The patch is textual rather than a load-and-dump, so that what the file
is mostly made of -- the documentation above each key -- survives a
preview build. The two keys the preview sets are written at the top,
which is where a bare key is always the document's own rather than the
last table's, and any live assignment of the three further down is
dropped -- so that neither of the two is defined twice (which TOML
forbids), and so that the third is not defined at all. A commented-out
one is left alone: it defines nothing, and it is the documentation.

Usage: set_base_url.py SITE_TOML BASE_URL
"""

import json
import re
import sys
import tomllib

# The keys a preview build takes out of the file: the two it writes
# back at the top, and the analytics script it drops.
OVERRIDDEN = ("base_url", "noindex", "plausible")

path, base_url = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    text = fh.read()

# a live assignment of any of them, at the start of a line and so at
# the top level of the file rather than inside a table
existing = re.compile(rf"(?m)^(?:{'|'.join(OVERRIDDEN)})\s*=.*\n?")
# json.dumps writes a TOML basic string: TOML takes every escape JSON
# has bar `\\/`, which json.dumps never writes
patched = (f"base_url = {json.dumps(base_url)}\nnoindex = true\n\n"
           + existing.sub("", text))

# the preview is worthless if any of the three silently failed to take
config = tomllib.loads(patched)
assert config["base_url"] == base_url, config.get("base_url")
assert config["noindex"] is True, config.get("noindex")
assert "plausible" not in config, config.get("plausible")

with open(path, "w", encoding="utf-8") as fh:
    fh.write(patched)
