#!/usr/bin/env python3
"""Point site.json's base_url at one preview deployment's subpath.

Used by the preview workflow before each site exporter runs, so the
absolute links each generator bakes in (feeds, redirect stubs) land
under that site's directory of the GitHub Pages deployment. Patches the
file in place; the workflow never commits the change.
"""

import json
import sys

with open("site.json", encoding="utf-8") as fh:
    config = json.load(fh)
config["base_url"] = sys.argv[1]
with open("site.json", "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
