#!/usr/bin/env python3
"""Point a site.json's base_url at one preview deployment's subpath, and
mark the deployment a preview.

Used by the preview workflow before each site exporter runs, so every
absolute URL a generator bakes in lands under that site's directory of
the GitHub Pages deployment. The previews are three complete copies of
the archive that search engines could otherwise index ahead of, and
then alongside, the real site, so `noindex` is set too: every page of
a preview carries a noindex robots tag and its robots.txt disallows
crawling. Patches the file in place; the workflow never commits the
change.

Usage: set_base_url.py SITE_JSON BASE_URL
"""

import json
import sys

path, base_url = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    config = json.load(fh)
config["base_url"] = base_url
config["noindex"] = True
with open(path, "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
