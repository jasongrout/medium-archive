# A MyST site

Written by `medium-archive myst` from an archived Medium publication.
Everything the site needs is in this directory: the posts as MyST
Markdown with front matter, their images beside them, and `myst.yml`
naming the table of contents.

## Build it

```sh
myst start                    # serve it, rebuilding as files change
myst build --html             # or: render it into _build/
```

`mystmd` (`npm install -g mystmd`, or `pip install mystmd`) is the only
thing to install; it fetches its site template on the first build.

## What to edit

| file | what it holds |
|------|---------------|
| `myst.yml` | the site's title, description and address, the table of contents, and the plugins the pages use |
| `index.md` | the landing page: its blurb and the cover-image gallery |
| `archive.md` | the chronological post list, grouped by year |
| `posts/<date>-<slug>/<page>.md` | the posts, with their images beside them |
| `listing-covers.mjs` | the companion plugin that gives the gallery its local cover thumbnails |

`site.options.url` in `myst.yml` is what absolute links are built from,
so set it to the domain the site is actually served from.

## Write a post

A post is a directory under `posts/` holding one Markdown file, with
its images beside it. The file name is the page's URL, which mystmd
caps at 50 characters.

```
posts/2026-01-31-a-new-post/
  a-new-post.md
  images/diagram.png
```

```markdown
---
title: A new post
date: 2026-01-31
authors:
  - name: Ada Lovelace
tags:
  - jupyter
description: The excerpt, and the page's meta description
thumbnail: images/cover.jpg
---

The body, as MyST Markdown.

![a diagram](images/diagram.png)
```

- `tags` here are the names a reader sees, not slugs: MyST has no tag
  pages, so nothing derives a URL from them.
- `thumbnail:` is the gallery's cover for the post; `cover.jpg` beside
  the page is the one the exporter baked.
- Add the page to `myst.yml`'s table of contents, or it is built but
  not linked from anywhere.

## While this directory is still generated

`medium-archive myst` writes the files it generates over whatever is
here and leaves everything else alone, so until this site is a
repository of its own, corrections belong upstream in the archive:
site-wide settings in its `site/site.toml`, tag names in its
`archive/tags.json`, a byline in the post itself. Once it is a
repository of its own — `medium-archive myst --out DIR` builds into it,
and `--clean` sweeps out the pages the archive no longer has, sparing
`.git/` and everything `.gitignore` here covers — this is the only
copy, and the files here are the ones to edit.
