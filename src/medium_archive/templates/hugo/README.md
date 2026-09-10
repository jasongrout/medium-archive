# A Hugo blog

Written by `medium-archive hugo` from an archived Medium publication.
Everything the site needs is in this directory: the posts as Markdown
with YAML front matter, their images beside them in leaf bundles, and a
self-contained theme under `layouts/`. There is no theme module and no
Hugo module to fetch — one `hugo` binary builds it.

## Build it

```sh
hugo                          # build the site into public/
pagefind --site public        # index it, which is what /search/ reads
hugo server                   # or: serve it at localhost:1313
```

Hugo extended 0.156 or newer: the theme is written in the layout
structure current Hugo looks pages up in, reads its data files through
`hugo.Data`, and uses the image pipeline the extended build carries.
`pagefind` (`npm install -g pagefind`) fills the `/search/` page;
without it the page loads and finds nothing.

## What to edit

| file | what it holds |
|------|---------------|
| `config/_default/params.toml` | what the pages say about themselves: the marks in the masthead and where they point, the banner, the line under every page, the newsletter band, the share image, the publication's handle and profiles |
| `config/_default/hugo.toml` | the site's address, name and language, which Hugo reads only at the root of its configuration — and below them the machinery: the taxonomies, the related-posts index, the paginator, Goldmark and Chroma |
| `content/_index.md` | the landing page's blurb |
| `data/tags.json` | tag slug → the name the tag is shown under |
| `data/authornames.json` | author slug → the name they are shown under |
| `data/authors.json` | author name → their profile address, which the structured data names as theirs |
| `content/posts/<year>/<slug>/index.md` | the posts, filed under the year they were published in, with their images beside them |
| `layouts/`, `static/`, `assets/` | the templates, the stylesheet and the site's images: how the pages look |

`baseURL` in `hugo.toml` is what every absolute link is built from —
the feeds, the redirect stubs, the Open Graph tags, the share links —
so set it to the domain the site is actually served from.

## Write a post

A post is a leaf bundle: a directory under `content/posts/<year>/`
holding an `index.md`, with its images beside it. The page is served at
`/posts/<year>/<directory>/`, where the year is the year of the post's
`date` — not of the directory it sits in, so a draft written in one
year and published in the next gets the right address either way.

```
content/posts/2026/a-new-post/
  index.md
  images/diagram.png
```

Each `content/posts/<year>/` is a section, and its page is the year
listing at `/posts/<year>/` — what a reader gets by trimming a post's
address. It is built from the posts; there is nothing to write.

```markdown
---
title: A new post
date: '2026-01-31T09:00:00Z'
authors:
- ada-lovelace
tags:
- jupyter
subtitle: The line under the title, Markdown like the body
description: The excerpt on the card, and the page's meta description
cover: images/cover.jpg
---

The body, as Markdown.

![a diagram](images/diagram.png)
```

- `authors` and `tags` are slugs, not names, so that their URLs are
  exact whatever the name holds; the name each is shown under comes
  from `data/authornames.json` and `data/tags.json`, which the term
  pages take their titles from. A slug missing from those files still
  gets its term page; it is shown as the slug itself.
- `lastmod:` is what the sitemap reports as the page's last change.
- `cover:` is the card image and the picture a share of the page
  carries. It is a resource of the bundle, so Hugo reads its size
  itself and any size will do.
- A body image is read as a resource of the bundle, so it carries its
  real width and height. A photograph also gets a responsive `srcset`;
  a png or webp is treated as line art and kept whole, since a
  screenshot's 9 px labels do not survive being resized.
- A captioned image is written as
  `{{< figure src="..." alt="..." >}}the caption{{< /figure >}}`, which
  is what keeps the caption in a `<figcaption>` with its picture.
- `aliases:` lists old paths this page should be reachable at; Hugo
  renders a redirect stub for each.

## While this directory is still generated

`medium-archive hugo` writes the files it generates over whatever is
here and leaves everything else alone, so until this site is a
repository of its own, corrections belong upstream in the archive:
site-wide settings in its `site/site.toml`, tag names in its
`archive/tags.json`, a byline in the post itself. Once it is a
repository of its own — `medium-archive hugo --out DIR` builds into it,
and `--clean` sweeps out the pages the archive no longer has, sparing
`.git/` and everything `.gitignore` here covers — this is the only
copy, and the files here are the ones to edit.
