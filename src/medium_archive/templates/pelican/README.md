# A Pelican blog

Written by `medium-archive pelican` from an archived Medium
publication. Everything the site needs is in this directory: the posts
as CommonMark with YAML front matter, their images beside them, the
theme, and the plugins that give the site responsive images,
redirects, a sitemap and a "More posts" block. Nothing is fetched from
anywhere at build time, and there is no theme or plugin to install
beyond Pelican itself.

## Build it

```sh
pip install pelican markdown-it-py mdit-py-plugins pyyaml pillow
pelican                       # build the site into output/
pagefind --site output        # index it, which is what /search/ reads
pelican -l                    # or: build and serve at localhost:8000
```

`markdown-it-py` and `mdit-py-plugins` are the CommonMark reader this
site reads posts with; `pyyaml` reads their front matter. Pillow is
what gives every body image its real width and height and the
photographs among them responsive variants; without it they are served
as they are. `pagefind` (`npm install -g pagefind`) fills the
`/search/` page; without it the page loads and finds nothing.

## What to edit

| file | what it holds |
|------|---------------|
| `site.toml` | everything the pages say about themselves: the site's name, its address, the marks in its masthead and where they point, the landing-page blurb, the line under every page, the banner, the newsletter band, the share image |
| `data/tags.json` | tag slug → the name the tag is shown under |
| `data/authornames.json` | author slug → the name they are shown under |
| `data/authors.json` | author name → their profile address, which the structured data names as theirs |
| `content/posts/<slug>/index.md` | the posts, with their images beside them |
| `theme/` | the templates and the stylesheet: how the pages look |
| `pelicanconf.py` | machinery — the CommonMark reader, the URL scheme, the feeds, and the plugins. It reads `site.toml` and holds no site data of its own |

`site.toml` lists every key it can carry, each under a comment saying
what it is for, and the ones this site does not set commented out
beside an example of them set — so it is also the list of what there is
to set. Nothing in `pelicanconf.py` explains any of them; that file is
machinery, and every export overwrites it. The address `site.toml`
names, `base_url`, is what every absolute link is built from — the
feeds, the redirect stubs, the Open Graph tags, the share links — so
set it to the domain the site is actually served from.

## Write a post

A post is a directory under `content/posts/` holding an `index.md`,
with its images beside it:

```
content/posts/a-new-post/
  index.md
  images/diagram.png
```

```markdown
---
title: A new post
date: 2026-01-31 09:00
authors:
- ada-lovelace
tags:
- jupyter
subtitle: The line under the title, Markdown like the body
summary: The excerpt on the card, and the page's meta description
cover: images/cover.jpg
---

The body, as CommonMark.

![a diagram]({attach}images/diagram.png)
```

- `slug` is the URL: the page is served at `/posts/<slug>/`. Left out,
  as above and as every post here leaves it out, it is the post's
  directory name -- so a directory name is worth choosing as carefully
  as a URL. It is read as it stands, not slugified: `A New Post` would
  serve at `/posts/A New Post/`, and an accent in the name is an accent
  in the address, which is why every name here is lowercase ASCII.
  Write the field to keep a post's URL when its directory is renamed.
  The build prints a line for each post served somewhere other than
  under its directory name, and stops if two posts would write the same
  page.
- `authors` and `tags` are slugs, not names, so that their URLs are
  exact whatever the name holds; the name each is shown under comes
  from `data/authornames.json` and `data/tags.json`. A slug missing
  from those files is shown as the slug itself.
- Dates are `YYYY-MM-DD HH:MM`, read as UTC. `modified:` is the same
  shape and is what the sitemap reports as the page's last change.
- An image needs the `{attach}` prefix, which is what publishes the
  file beside the page and rewrites the link to it.
- `cover:` is the card image and the picture a share of the page
  carries. The covers here were baked to the size `site.toml`'s
  `cover_size` names, and the pages declare that size to share targets,
  so either crop a new cover to it or drop that key.
- A png or webp body image is treated as line art and served whole,
  since a screenshot's 9 px labels do not survive being resized; a
  photograph gets the responsive variants.
- A captioned image is written as a `::: figure` directive, with the
  caption as the directive's body; see any post that has one.

## While this directory is still generated

`medium-archive pelican` rewrites every file here except `output/`, so
until this site is a repository of its own, corrections belong upstream
in the archive: site-wide settings in its `site/site.toml`, tag names
in its `archive/tags.json`, a byline in the post itself. Once it is a
repository of its own, this is the only copy, and the files here are
the ones to edit.
