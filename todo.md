# Status: what changed and what remains

## Done

Tool work from the 2026-08 audit sessions. Each change was validated by
a full `convert --clean` over a large real archive, a clean `lint` run,
and the offline test suite.

- **Chrome-only shell guard.** A `page.html` that is Medium's empty app
  shell (no `<article>`, no JSON-LD, no title) is never converted into a
  post of nav links. See `page_shell` in `src/medium_archive/convert.py`.
- **The embedded editor state is the preferred Medium body source.**
  Every Medium page carries its post twice: as rendered HTML and as the
  editor state in `window.__APOLLO_STATE__`. `convert` now prefers the
  state, in the order `export` > `feed` > `state` > `page`, with
  `--prefer-page` overriding. The state has no chrome to strip and keeps
  what the renderer destroys: full link spans over code fragments, bold
  on code, iframe embeds that un-hydrated captures drop, and clean
  one-line links for link-preview cards (`src/medium_archive/state.py`).
  It is also how shell-only captures convert at all, with real dates
  and titles; a shell's images stay remote until re-fetched, and a shell
  with no usable state still fails loudly. `compare --state` verifies
  the state conversion against account exports the way plain `compare`
  verifies the page conversion.
- **Byline avatars stripped.** Authors with a custom subdomain
  (`name.medium.com`) have no `/@` in the byline href, so their avatar
  block leaked into page-converted bodies as a remote image.
  `page_body` now also strips on `source=post_page---byline`.
- **Medium link telemetry stripped.** The renderer appends a
  `source=post_page---…` query parameter to links on any host.
  `to_markdown` drops it. The dash-run value pattern marks it as
  Medium's, so a site's own `source` parameter survives.
- **Ghost-migration line breaks.** Medium's importer turns every wrapped
  source line of a migrated Ghost post into a `<br><br>` pair
  mid-paragraph. For posts with a Ghost origin these collapse to the
  space the wrap stood for (`collapse_br_pairs`). Posts authored in
  Medium's own editor keep `<br><br>` as an intentional paragraph break.
- **Readability fixes.** Captioned figures keep their
  `<figure>`/`<figcaption>` shell, and the sites render it as Medium
  did: caption under its picture, styled by CSS, associated with the
  image for assistive tech. A caption whose figure lost its image
  renders in italics. A leading heading that repeats the post title is
  dropped. A body never opens with the divider left by the removed
  subtitle block. Whitespace-only hard-break lines normalize to blank
  lines outside code fences. Iframes render as `[embed: url](url)`.
  `slug_of` percent-decodes, so directory names cannot mix encoded and
  decoded forms of one slug, and `resolve_canonical` compares decoded.
- **`lint` subcommand.** Defect signatures (leftover Medium chrome,
  unclosed fences, missing image files, remote Medium CDN images) exit
  non-zero, so regressions surface on every convert. `lint --embeds`
  adds the embeds whose content the archive lacks, as problems: every
  `[embed: url]` link an iframe became (the sites render the link, not
  the content), and every embed an export or feed body dropped that the
  page's editor state carries (`state_embed_targets`, compared by
  count, since the state names a canonical page where the export names
  the embed URL). Opt-in because neither is a conversion defect; an
  archive's CI runs it as a separate job that fails until the posts are
  fixed by hand. An iframe with no source (how a feed body renders a
  gist) now converts to the `[missing embed]` placeholder instead of a
  dangling `embed:` with no link, so plain `lint` catches it too.
- **YouTube embeds are players, not links.** The archive has the
  video's URL, which is all the player needs, so `to_markdown` keeps a
  YouTube iframe as an iframe: one canonical line
  (`convert.youtube_iframe`) with the video on the no-cookie host, any
  `t=`/`start=` start time, the resource title the state knows as the
  accessible name (an export iframe has none; "YouTube video" then),
  lazy loading and YouTube's own `allow` list. `youtube_video`
  recognizes every URL form Medium and the state produce (watch?v=,
  youtu.be, /embed/, /v/, /shorts/, /live/) and refuses playlists.
  Hugo and Pelican render the line as the raw HTML block it is (as
  they do the figure shells), with `card.css` scaling the 560×315
  player to the column at 16:9; the MyST exporter rewrites it to the
  `{iframe}` directive, captioned or not, since mystmd is not
  guaranteed to render raw HTML. `compare` sets the title aside, as it
  does fence languages, so the sources still agree. Every other iframe
  is still the `[embed: url]` link, which `lint --embeds` reports.
- **Giphy embeds are archived files.** The embed's target is the media
  file itself (`media.giphy.com/media/<id>/giphy.gif` or `.mp4`; a
  giphy.com page or embed URL names the id the gif URL is built from,
  `images.giphy_media`). `fetch` adds those files to the post's image
  download (`fetch.embed_asset_urls`), and its skip-already-archived
  path backfills them into `raw/<id>/images/` and `images.json` for
  posts fetched before this existed, the way gist media is backfilled.
  `convert` then replaces the iframe with the file: an `<img>` for a
  gif or webp, localized with the other images, with Giphy's page-title
  suffix trimmed from the alt; a `<video autoplay loop muted
  playsinline>` for an mp4, one canonical line like the YouTube player
  (`VIDEO_RE`), copied beside the post and listed in the front matter's
  images so every exporter places it (the placer passes non-images
  through). MyST gets `![](clip.mp4)` or a `{figure}` around it, which
  mystmd renders as a video. `lint --embeds` leaves Giphy targets out
  of the state's embed count, since they convert either way, and
  reports a file still served from Giphy until `fetch` runs again.
  Built and tested offline: the sandbox's proxy refuses media.giphy.com,
  so the first live backfill deserves a look. (It got one: a first run
  merged the two `giphy.mp4` basenames of one post into a single file,
  through the de-duplication meant for a Medium asset under two CDN
  hosts; only Medium CDN URLs merge now, and Giphy files carry their
  id.)
- **Tweets are archived and quoted.** A tweet's text exists nowhere
  in a Medium page: the state has an embedly wrapper with an empty
  title, and the export has Twitter's widget markup, a
  `twitter-tweet` blockquote holding only the tweet's link. `fetch`
  now archives each tweet embed's oEmbed payload (`fetch_tweets`,
  from `publish.x.com/oembed`, which needs no credentials; checked
  live 2026-09, and `publish.twitter.com` redirects there) into
  `raw/<id>/media/tweet-<tweet id>.json`, on new posts and on the
  backfill path. `convert` renders an archived tweet as a blockquote
  (`tweet_html`): the text with its links, `ref_src` tracking dropped,
  a hard break per line, then "— Name (@handle), Month D, YYYY" with
  the author and the date linked. Plain Markdown, so every generator
  renders it and it outlives the tweet. The export's empty widget
  blockquote is normalized to an iframe on the tweet's URL first, so
  it takes the same path (a Ghost capture's blockquote that already
  carries the text is left alone). A tweet the endpoint reports gone
  stays the `[embed: url]` link, which `lint --embeds` names as an
  unarchived tweet; the quote of an archived one counts as content
  (`TWEET_QUOTE_RE`, the attribution line's dated status link).
  A tweet's photos come from X's syndication endpoint
  (`cdn.syndication.twimg.com/tweet-result`, the one static tweet
  renderers read; unauthenticated, keyed by react-tweet's token
  derivation from the id, `tweet_token`, checked live 2026-09):
  `fetch_tweets` archives that payload as `tweet-<id>.media.json`
  for a tweet whose oEmbed html links a picture, `embed_asset_urls`
  adds each photo (X's default 1200 px size, past what the themes
  render) and each video's poster
  frame to the post's image download, and `tweet_pictures` puts them
  in the quote, the photos as images and a poster linked to the
  tweet, dropping the `pic.twitter.com` link they stood behind. The
  archived tweet is swapped in ahead of the image pass so those
  images localize like the rest. A video itself is not archived: its
  mp4 lives on X's CDN under changing URLs. A deleted tweet (404 from
  the oEmbed endpoint) is recorded in `tweet-<id>.json` as
  `{"deleted": true, "url", "status", "checked_at"}` rather than left
  to be asked about on every run: convert writes a link saying the
  tweet is no longer available, and lint treats the record as the
  embed's content. Deleting the file asks again; a hand-written
  oEmbed-shaped payload (text recovered from a Wayback capture, say)
  replaces the record with a real quote.
- **Known providers' players stay iframes.** For an embed whose
  content is a player with nothing to archive, the editor state
  carries the provider's own embed URL (the embedly wrapper's `src=`)
  and the size Medium showed it at (`iframeWidth`/`iframeHeight`);
  `_iframe` passes both through as `data-embed`, `width` and
  `height`. `convert.provider_embed` keeps an iframe for a host in
  `PROVIDER_EMBEDS` (Carbon, Vimeo, CodePen, Spotify, SoundCloud), on
  the state's embed form when its host is the
  provider's, else derived from the canonical page URL, so export
  iframes work too. `embed_iframe` is the one line for every kept
  player, YouTube included: src, title, width, height, an inline
  `aspect-ratio` the theme's CSS scales to the column (a 720×200
  podcast player is not a 16:9 box), lazy loading, and YouTube's
  allow list on its host only; YouTube keeps the 560×315 default
  rather than Medium's size. The cost is a third-party frame at read
  time and nothing once the provider is gone. art19 was on the list
  and came off it: its pages send a frame-ancestors policy, so the
  player renders as a browser error on any other site (seen in
  Firefox). `PROVIDER_LINKS` names such providers, and their embeds
  become a plain link titled by the state (the episode's name), which
  `lint --embeds` reads as content rather than an unfilled embed.
- **Carbon snippets are archived as code.** A Carbon embed page
  (`carbon.now.sh/embed/<id>`) is a Next.js page whose `__NEXT_DATA__`
  carries the snippet itself: `code` and `language` (found by reading
  one in a browser). `fetch_carbon` archives that object into
  `raw/<id>/media/carbon-<id>.json` on the same incremental path as
  gists and tweets, and `convert` inlines it as a language-tagged
  fence (`_archived_carbon`; Carbon's "auto" stays bare), with the
  provider iframe as the fallback until fetched. `lint --embeds`
  leaves an archived snippet's target out of the state's embed count,
  as a fence cannot be told from any other. Tested against the pasted
  page data only; the sandbox cannot reach carbon.now.sh.
- **Substitution fixups.** Raw HTML is often one enormous line, so a
  unified diff of a one-character fix embeds the whole line twice and
  cannot be reviewed. `fixups/*.sub` files hold single-line
  `old:`/`new:` substitutions, with an optional exact `count:` and
  `old-regex:` for regexes, and fail loudly like patch hunks. `*.patch`
  remains for structural edits. Fixups should not patch a page's
  embedded editor-state copy: its markup offsets index into the stored
  text, so editing it would skew them.
- **`myst` subcommand.** Builds a MyST (mystmd) site in
  `<out>/site-myst/` from the converted posts, so a browsable blog
  reproduces offline from `raw/` plus `fixups/`. One page per post, with
  the filename as the URL slug (date-prefixed only when several posts
  share a slug). mystmd caps served slugs at 50 characters, so
  `redirects.csv` targets replicate its slug rules: truncation,
  `[a-z0-9-]` folding, collision numbering. A year-grouped TOC, a
  cover-image gallery landing page through the pinned myst-listing
  plugin, and a chronological `archive` page. Covers are the same
  640×360 crop-or-letterbox thumbnails as the card themes' and double as
  each page's social-card image. A small generated companion plugin,
  `site-myst/listing-covers.mjs`, turns the gallery's CSS cover
  backgrounds into real image nodes so mystmd's image pipeline serves
  local files. In-publication links are rewritten to site pages, and
  prose MyST would misparse is escaped (`@handle` reads as a citation,
  paired `$` as math). Site-wide text comes from a hand-written
  `<out>/site.json`. Validated with a full `myst build --html` over the
  real archive: 336/336 pages (334 posts plus landing and archive), 334
  gallery cards (255 with covers), every redirect target resolving to a
  built page, and no warnings beyond pre-existing dead in-page anchors
  from the Medium era (`src/medium_archive/myst.py`).
- **`hugo` and `pelican` subcommands.** The same site for those
  generators, in `site-hugo/` and `site-pelican/`, sharing page URLs,
  link rewriting, `site.json` and per-site redirect maps through
  `src/medium_archive/sites.py`, so generators can be compared on
  identical content. Hugo got tag and author taxonomy pages with
  per-term feeds, old inbound paths as alias redirect stubs, and a
  minimal self-contained theme. Pelican initially relied on its built-in
  theme, with colocated images rewritten to `{attach}` links. Each was
  validated with a real generator build over the full archive (hugo
  0.152.2, pelican 4.12.0). A third exporter, `zola`, shipped alongside
  and was dropped later (see below).
- **Card-grid blog theme for hugo and pelican, with Pagefind search and
  image optimization.** Both exporters ship the same self-contained card
  theme, in the vein of pytorch.org/blog: paginated cover-card home,
  tag/author card listings, chip indexes, and a /search/ page wired to
  Pagefind. Pagefind serves full-text search as a results page with
  highlighted in-context excerpts and per-section sub-results
  (`pagefind --site public|output` after building). Hugo optimizes
  images natively: 640×360 cover thumbnails via `.Fill` and responsive
  lazily-loaded webp variants for body images via a render hook, with
  gif, svg and non-image resources passing through. Pelican generates
  640×360 JPEG cover thumbnails at export time when Pillow is installed
  (the `covers` extra), lazy-loads body images through a Markdown
  extension embedded in its generated config, and enables heading ids
  so search results anchor to sections.

  Pelican also got redirect-stub parity. A plugin embedded in its
  generated config renders the exported redirects.csv into meta-refresh
  stub pages after each build, matching Hugo's alias count row for row,
  since Pelican has no aliases feature of its own. The same plugin
  brings body-image parity with Hugo's render hook: after each build it
  rewrites every still body image to lazily-loaded webp srcset variants
  (480/736/1104, never upscaled, real width/height, the same sizes
  hint). It encodes from and mtime-caches against the content-side
  originals, because Pelican freshens output copies every build, which
  would defeat a cache keyed on them. On the reference archive: 1854
  variants on the first build in about 2.5 minutes (the same codec cost
  as Hugo's first build), then 0 re-encoded and about 20 s on rebuilds.
  This was chosen over the pelican-image-process plugin after reading
  its source: that plugin only processes class-annotated images (the
  annotation would have to come from this exporter anyway), flattens
  animated gifs, emits fixed-name srcset descriptors regardless of
  actual image size, and adds bs4 and lxml (AGPL) to the site's build
  requirements.

  Covers are chosen by sniffing dimensions from image headers, with no
  image library needed for that path. Only png, jpeg and webp names
  qualify: the baked cover is served as cover.jpg and Hugo's card
  template rasterizes it, which aborts the build on an svg badge it
  cannot decode. Relatedly, `convert` now renames images fetched from
  extensionless URLs (stored as `.bin` in raw/) to the extension their
  bytes call for, so every derived layer gets typed image names; 103
  such files in the reference archive. Both sites were validated end to
  end in headless Chromium, including search with highlights.
- **Sortable tag/author chip indexes (hugo and pelican).** The card
  theme's /tags/ and /authors/ pages get a "Sort by name/count" control,
  a plain HTML+JS snippet shared verbatim between the two generators
  like the theme picker. Name is the A–Z order the generators emit, so
  the no-JS page reads the same. Count sorts most posts first with
  alphabetical ties. The choice persists per browser via localStorage.
  Verified in headless Chromium against the reference archive on all
  four pages (both generators × tags/authors), including persistence
  across reloads and identical counts across generators.
- **Click-to-zoom body images (hugo and pelican).** Clicking an article
  image, or pressing Enter on it (zoomable images take keyboard focus
  and a button role), opens it full size in a `<dialog>` modal captioned
  with its alt text. This restores the one Medium reading affordance the
  conversion drops: Medium's own "Press enter or click to view image in
  full size" hint is stripped as chrome by `pages.py`. It is another
  plain HTML+JS snippet shared verbatim between the two generators,
  spliced into the post templates rather than the base ones. Only images
  worth zooming are marked, so the cursor never promises a no-op. The
  test compares the `width` attribute both exporters already emit
  against the rendered width, not `naturalWidth`, which the browser
  density-corrects to the layout size once a srcset variant is in play.
  The modal loads the `src`, which the responsive markup keeps as the
  full-size original, never a variant. Images inside a link are left
  alone, so a linked image still follows its link. It closes on a click
  anywhere, Esc, or a page scroll. Verified in headless Chromium against
  real hugo (0.140.2 extended) and pelican (4.12.0) builds of a fixture
  archive: 26 assertions per generator over marking, the affordances,
  open/close by mouse, keyboard and scroll, the zoomed source being the
  original, and re-measurement when the window resizes under an image.
- **Hugo named-theme support removed.** The `hugo` step once let
  `site.json` name a real theme (`theme`, `theme_repo`) and gave the
  Dream theme first-class treatment: its params, search and archives
  sections, byline links. The archive settled on the built-in card
  theme, so that path is gone. The exporter always writes its own
  layouts, and the `hugo` section keeps only `locale`, `avatar`,
  `favicon` and `params`. The three exporters were consolidated on
  `sites.py` in the same pass: one `Covers` object picks, references and
  bakes card covers (Pillow detection once), one `place_images` loop
  places a post's images beside its page, one `copy_site_asset` ships
  the avatar and favicon (a missing file is now noted by every exporter,
  not just hugo), one `write_templates` writes a theme, and one
  `FIGURE_SHELL_RE`/`rewrite_figures` pair parses convert's figure
  shells for all three figure rewrites.

From the 2026-08 review of other Medium-to-Markdown tools (medium-2-md
and mediumexporter; the latter's media-resource handling exposed a
silent data loss here):

- **Gist embeds recovered instead of silently dropped.** A gist embed's
  media resource has an empty `iframeSrc`, since gists are the one embed
  type not routed through embedly, so its content exists nowhere in the
  page. The state conversion emitted nothing at all, and export and
  Ghost bodies carry it as a `<script src="…gist.github.com/….js">` tag
  that also converted to nothing. Now `fetch` archives the media payload
  (`medium.com/media/<id>?format=json`, mediumexporter's trick) and the
  gist's files (GitHub gists API) into `raw/<id>/media/`, incrementally,
  so a re-run backfills posts archived before this existed. `convert`
  inlines the files as language-tagged fences from any body source.
  Without archived media the embed becomes an `[embed: <gist url>]` link
  (export and Ghost bodies name the gist) or a
  `[missing embed: <name>]` placeholder (the state does not), and `lint`
  flags the placeholders. A Markdown gist file is inlined verbatim
  rather than fenced: it is the one way to put a table in a Medium post
  (blog.jupyter.org's 2026 survey results), so its source is prose to
  render, not code to show. And a feed body's gist, an empty iframe
  around a `medium.com/media/<id>/href` link, resolves through that
  media id to the archived files like the state and script forms, so
  the fixup that used to put a `<script src>` back is not needed.
- **Code fences carry languages.** The state's `codeBlockMetadata`
  records the language Medium highlighted (author-set or auto-detected;
  DISABLED stays bare). Gist files and Ghost `language-*` classes
  provide it too. `to_markdown` now emits it on the opening fence, and
  `compare` drops fence info strings, since only some sources know them.
- **User mentions resolve.** Mention markups carry a `userId` and no
  href, and rendered as empty links. The state's own `User:` entry names
  the profile (`https://medium.com/@username`). Unresolvable mentions
  stay plain text.

Image handling:

- **Sites carry display copies of images, capped at export time.** The
  exporters used to hard-link every full-resolution original from
  `posts/` into each site, so sources dominated the built output: about
  800 MB of an 850 MB site on the reference archive, duplicated per
  generator, with animated gifs alone about 600 MB, while the themes'
  srcset ladders top out at 1104 px. The shared image-placement path
  (`ImagePlacer` in `sites.py`, used by every site exporter) now resizes
  anything past a cap as it is placed. Stills go to a 1600 px longest
  edge via Pillow, format preserved, ICC kept, palette images
  de-paletted, and the original kept whenever the resize does not
  actually shrink the file. Animated gifs go to 1104 px via gifsicle
  with `-O2 --resize-fit --no-conserve-memory`: `-O2` re-optimizes
  frames to 2/3 the bytes of a bare resize, `--lossy` measured slower
  for no further gain, and without `--no-conserve-memory` huge gifs trip
  a low-memory mode that turned a 60 s resize into 5+ minutes (peak RSS
  measured about 1.1 GB on an 851-frame 22.6 MB gif). Display copies are
  built once into `<out>/.image-cache/<caps>/`, warmed in parallel up
  front since encodes hold no GIL, and hard-linked into every site.
  `raw/` and `posts/` stay at full resolution, unreadable or exotic
  files pass through unchanged, and a missing tool degrades to full-size
  placement with a note. `site.json` tunes or disables the caps
  (`"images": {"still_max_edge": N, "animated_max_edge": N}`, 0 = off).
  Validated by the offline suite (real-image tests, with a gifsicle test
  that skips where it is not installed) and a full three-site rebuild of
  the reference archive.
- **Line art is kept whole, not resized.** The cap above treated a
  survey chart like a photograph, and the srcset ladder below it
  finished the job. Measured on one of the 2026 survey charts, ink
  contrast fell from 3.4:1 at the source's 1430 px to 2.3:1 at the
  736 px variant a phone picks, well under the 3:1 small text needs,
  and its 9 px axis labels came out around 4.6 px. Downscaling was not
  even buying much: flat color compresses by run length, not pixel
  count, so a lossless encode of most of this archive's line art comes
  out larger downscaled (18 of 25 sampled), as antialiasing invents
  intermediate colors. `ImagePlacer` now classifies each PNG at about
  8 ms an image: at most 8192 colors and at least 0.55 horizontally flat
  pixel pairs is line art, which separates this archive's line art
  (200-8000 colors, 0.55-0.98 flat) from its photographs (14000+ colors,
  under 0.5 flat). Line art is re-encoded to lossless webp at its own
  resolution, exempt from the still cap: pixel-exact text for about 60%
  fewer bytes than the source PNG. The 2026 survey post went from 557 KB
  of PNG to 201 KB, against 264 KB for a ladder that could not render
  the captions. A photograph that arrived as PNG takes the photo path
  instead (capped, JPEG q85, or webp when it carries alpha), which is
  where the archive's 63 photo-in-PNG files, about 70 MB, were hiding.
  Intricate line art is bounded rather than resized: past 500 KB
  lossless it retries at webp q90, and only a panorama past 4000 px is
  finally scaled. `place()` returns the path it wrote and the exporters
  retarget their pages' `images/<name>` references, so a changed format
  follows through to the markdown. The hugo render hook and pelican
  plugin skip the variant ladder for png and webp, which also hands
  click-to-zoom a full-resolution `src` to open rather than a 1600 px
  resample. The cache directory carries a scheme tag, so copies written
  by the old scheme are ignored rather than misread.
- **`zola` exporter dropped.** The Zola site fell far enough behind the
  hugo and pelican ones to stop being worth carrying: those two share
  the card-grid theme, Pagefind search, cover thumbnails and responsive
  body images, while the zola site kept the older list theme none of
  that work reached. Its module, Tera templates, config template,
  stylesheet and tests are gone, along with the `zola` subcommand. The
  shared machinery in `sites.py` was unchanged, so `hugo`, `pelican` and
  `myst` build exactly as before. An archive's `site-zola/` directory,
  if one was built, is stale output and can be deleted.

Tags:

- **tags.json: `imply` and per-post `remove`.** Curating an archive's
  tags needs both directions, and the file only had one. `"imply"`
  states that one tag entails another everywhere it appears (every
  `jupytercon` or `workshops` post is also an `events` post) instead of
  repeating the pairing per post. `"remove"` subtracts a tag from the
  posts it does not describe, keyed by slug like `"add"`. That is the
  cheaper half of splitting an over-applied tag when most of its uses
  are right; drop-then-re-add stays the right move when most are wrong.
  The passes run drop, rename, add, imply, remove, so an added tag
  entails as much as an inherited one and a remove has the last word
  even over an implication. Both new sections fail as loudly as the old
  ones: chained or dropped implications, a tag both added and removed
  on one post, and stale entries (an implication no post triggers, a
  remove of a tag no matching post carries) all abort
  (`src/medium_archive/tags.py`).
- **tags.json: `display`, the name a tag is shown under.** Medium tags
  are slugs, so an archive's tags rendered as `jupyter-notebook` and
  `ipython` where a reader expects "Jupyter Notebook" and "IPython".
  Spelling them correctly is a display concern, not an identity one, so
  the `"display"` section maps a tag to its name and nothing else moves.
  A tag stays one slug through `posts.json`, the rest of `tags.json`,
  and every `/tags/<tag>/` URL and per-tag feed. A tag with no entry
  shows as itself with its hyphens as spaces (`open-science` → "open
  science"), which is why the section only holds the tags that need a
  proper name. An entry repeating that default, a name two tags would
  share, and a name for a tag no post carries all abort, like every
  other section's stale or contradictory entry.

  Each exporter carries the name the way its generator wants it. Hugo
  gets the map as `data/tags.json`, from which a content adapter
  (`content/tags/_content.gotmpl`) creates a term page per tag with that
  title, so cards, the tag page and its `<title>`, the chip index and
  the per-tag RSS feed all pick it up while front matter keeps the slug,
  and a checked-in site renames a tag in one file.
  Pelican gets a `TAG_DISPLAY` map in `pelicanconf.py`, which the site
  plugin sets on the `Tag` objects once the tags are collected. Tags
  still reach Pelican as slugs, so `tag.slug` is exact rather than
  whatever its slugify makes of a name like "C++". Naming the objects
  rather than filtering in the theme is what reaches the per-tag feed's
  title, which Pelican builds in Python. Pelican makes a `Tag` object
  per article while `generator.tags` is keyed on the slug, so each
  article's list is pointed at the one named object; otherwise a tag
  would be named on its own page and on a single card and stay a slug
  everywhere else. MyST has no tag pages, so its front matter simply
  carries the names (`src/medium_archive/tags.py`, `sites.py`,
  `hugo.py`, `pelican.py`, `myst.py`).

Feeds and sharing:

- **The RSS mark, and a feed link per term.** The header's feed link
  was the word "RSS" among the nav's other words, and the per-term feeds
  both generators emit were reachable only through
  `<link rel="alternate">`, which means only through a browser that
  still surfaces one. Both now use `shared/feed-icon.html`, the RSS mark
  as an inline SVG in the same stroked style as the theme picker's
  icons, in the header and beside a tag's or an author's heading,
  linking that term's own feed. Hugo draws the link from
  `.OutputFormats.Get "rss"`, so it appears exactly where a feed exists;
  pelican's comes from `TAG_FEED_ATOM` and `AUTHOR_FEED_ATOM`. Both
  heads now declare the same pair, the site-wide feed on every page plus
  this page's own where it has one, each `<link>` titled the way that
  feed titles itself, since a reader files a subscription under the name
  the link gives it. Hugo had been advertising a term's feed under the
  bare site title (subscribing from /tags/jupyterlab/ filed "Jupyter
  Blog", not "JupyterLab · Jupyter Blog") and nothing at all on a post
  page (`templates/shared/feed-icon.html`, `card.css`, both themes).
- **Share links on every post.** Nothing on a post offered to pass it
  on. Both card themes now close an article with five links: LinkedIn,
  Facebook, Bluesky, Mastodon and email, under the networks' own
  logomarks, drawn from one hidden `<symbol>` sprite
  (`shared/share-icons.html`) so the marks are shared even though only
  each engine knows a post's URL. The URLs are built at render time from
  the post's absolute permalink, percent-encoded by Go's contextual
  escaping on hugo and by an explicit `|urlencode` on pelican's Jinja,
  which does none of its own. They are only as real as `site.json`'s
  `base_url`, like the feed URLs and redirect stubs. Mastodon is the one
  network with no single address to send a share to, so that link is
  the one piece of script (`shared/share-mastodon.html`): it asks for
  the reader's server, normalizes a pasted server URL or `@you@server`
  handle down to the domain, remembers it per browser, and falls back
  without JS to the server directory. The bar sits inside the post card
  under a rule and carries `data-pagefind-ignore`, so "Share" never
  lands in the search index (`templates/shared/share-icons.html`,
  `templates/shared/share-mastodon.html`, `card.css`, both post
  templates).
- **Open Graph metadata, without which half the share links do
  nothing.** The first share links shipped against pages carrying no
  `og:` tags at all. LinkedIn's and Facebook's share URLs pass only the
  page address, and everything their share box shows is read back off
  the page, so a share of a post came up blank. Both card themes' heads
  now carry `og:site_name`, `type`, `title`, `url` and `description`,
  the post's baked 640x360 cover as `og:image` (with `twitter:card`
  following whether there is one), `article:published_time`, its
  authors and tags, and a canonical link. The other half of that same
  failure was `base_url`: unset, hugo falls back to `example.org` and
  pelican to an empty `SITEURL`, so every share link pointed at a domain
  the archive does not own or at a relative path LinkedIn rejects, and
  the build said nothing. `load_site_inputs` now warns once, where both
  exporters already meet. Share links are the first feature where a URL
  leaves the site, so a wrong one fails outright instead of degrading
  (`sites.py`, both base templates).
- **The share bar under the byline too, and monochrome marks.** A
  reader who decides to pass a post on usually decides at the top,
  where the byline says whose it is, not after scrolling to the foot.
  The bar now renders in both places, which meant giving each engine one
  definition of it rather than four copies: hugo gets
  `partials/share.html`, the pelican theme a `share()` macro beside
  `card()`, each called twice, with the `<symbol>` sprite still spliced
  in once and the Mastodon script binding every anchor rather than the
  first. The byline copy takes no rule above it, since one there cuts
  the head off the article, and `.post-meta` carries the tighter margin
  that pairs with it. Hover no longer tints the marks with the site
  accent. These are the networks' logos, and most of their brand
  guidelines allow a one-color rendering but not a recoloring, so a
  hover deepens the mark toward the ink instead (`partials/share.html`,
  `macros.html`, `card.css`, `shared/share-mastodon.html`).
- **The pelican theme escapes what it renders.** Pelican's own default
  `JINJA_ENVIRONMENT` sets no `autoescape` and Jinja's default is off,
  so a theme emits every `{{ }}` raw. The burden of escaping is the
  theme author's, because `article.content` has to pass through as the
  HTML it is, and this theme had not been carrying it. A post titled
  `<script>...` therefore ran as a script on its own page, its cards,
  and its `<title>`, as did a tag's display name and an author's. None
  of those are written by the person building the archive; they come
  from the archived publication. Demonstrated in a browser before and
  after: stock defaults executed all three payloads, and the fix
  executes none. The generated config now turns `autoescape` on
  (restating pelican's other three defaults, which the setting
  replaces) and the theme marks the one genuinely-HTML value,
  `article.content`, `|safe`. Hugo was never affected: Go's
  html/template escapes contextually, which is also why the two engines
  had been rendering such a title differently (`pelicanconf.py.tmpl`,
  `article.html`).
- **Truncated titles completed.** Medium titles a post whose author set
  none with its opening heading, cut to about a hundred characters with
  an ellipsis, and that cut form is all the stored title, the JSON-LD
  headline and `og:title` carry. Such a post converted with the
  truncated title in its front matter and, since the body's opening
  heading no longer matched it, the full heading left in the body
  right under the title. `convert` now completes the title from the
  heading (the rendered `<h1>`, or the state's opening heading
  paragraph) and matches an ellipsis-truncated title as a prefix when
  dropping the body's repeat (`heading_is_title` and
  `untruncated_title` in `src/medium_archive/pages.py`, used by
  `page_body`, `extract_metadata` and `state.py`). One post in the
  test archive was affected; no other post's output changed.

- **Share URLs checked against each network's own documentation;
  Mastodon moved to its official share sheet.** LinkedIn's
  `sharing/share-offsite/?url=` is the form its developer docs give,
  the one parameter left since `shareArticle`'s title and summary were
  retired in 2018; the share box reads everything else off the page's
  Open Graph tags. Bluesky's `bsky.app/intent/compose?text=` is the
  form its action-intent docs give, a single URL-escaped `text` with no
  separate URL or title parameter, under the 300-grapheme post limit.
  Facebook's only documented share URL is the Share Dialog,
  `facebook.com/dialog/share?app_id=...&href=...`, which needs a
  registered app id; `sharer.php?u=` is undocumented, but it is the
  app-id-free form every share bar uses and Meta has kept it live while
  stripping every parameter but `u`, so it stays, deliberately. The
  email link follows RFC 6068. Mastodon was the one that had moved on:
  since 2026-03 the project hosts share.joinmastodon.org, an official
  share sheet that takes the text in `#text=` (its own instruction page
  generates the hash form, which keeps the text out of server logs and
  referrers; `?text=` works too), asks the reader for their server,
  remembers their accounts, resolves each server's share template over
  WebFinger before falling back to `https://server/share?text=`, and on
  a phone tries the `mastodon://share` app link. That is what this
  theme's prompt script did, done by the network itself, so the script
  went (`shared/share-mastodon.html`), and the link is a plain href
  like the other four: no `data-share-text`, no server-directory
  fallback, no `localStorage` (`partials/share.html`, `macros.html`,
  both post templates, `templates/README.md`). The `/share?text=`
  route the script used was real, for the record: Mastodon's
  `render_initial_state` joins its `title`, `text` and `url` params
  into the compose box.

## Remaining

- Take the share bar's marks from each network's own brand material
  rather than the reproductions they run on now. The logomarks come
  from Simple Icons, a faithful reproduction but not the source, and
  one that dropped LinkedIn's over that company's branding policy, so
  that one is lifted from an old release. Per network, the official
  logo file with its usage rules is worth confirming at the source:
  clear space, minimum size, and which one-color renderings are
  permitted. The bar assumes a monochrome mark tinted by
  `currentColor`, which is why hovering deepens it instead of coloring
  it. Each network's guidelines may also constrain the wording beside
  the mark. The share URLs themselves were checked against the
  networks' documentation in 2026-09 (above).

- (Done 2026-09.) The reference archive's `fetch` re-run backfilled
  every gist's media (the 26 placeholders across 7 posts went), then
  the tweets, Carbon snippets and Giphy files as each was added; the
  medium.com/media endpoint and the anti-hijacking-prefix parsing
  worked live as implemented from mediumexporter's usage. The one
  surprise was the Giphy filename collision, fixed above.

- Link contrast in the card theme. Links were `--accent` (#f37626,
  Jupyter Orange) text, which is 2.8:1 against the light palette's white
  cards, below WCAG AA's 4.5:1 for normal-size text, let alone AAA's
  7:1; jupyter.org makes the same trade-off with its orange links, and
  this archive kept it through the 2026-08 restyle. Resolved in 2026-09
  without a shade: a link now keeps the colour of the text around it
  (ink in a paragraph, the muted grey in a byline; every text token
  clears AAA) with a .1em rule in the accent under it (2px in the
  article column, thinner under the small metadata lines), so the orange,
  which carries no letterforms, is what says "link". Component
  links (nav, card titles, chips, pills, page numbers) carry no rule at
  rest and show it on hover; the hover state of a prose link is
  unchanged from its rest state, by choice. The same treatment applies
  in both palettes, though orange text passes AA on the dark cards, so
  that the link language does not change with the theme. The text grays
  are held to AAA: `--muted` was raised in the 2026-08 restyle
  (#6a6a6a→#525252 light, #9b9791→#aeaaa4 dark) so every text token
  clears 7:1 on both the page background and the cards. Alternatives
  weighed and not taken: a link shade token per palette (#b45110 clears
  AA in light; #f58d47 clears AAA in dark) is a shade of the brand
  colour, which the guidelines rule out; an always-on underline under
  orange text fixes only the colour-alone question (1.4.1), not text
  contrast (1.4.3).

Archive-specific follow-ups (posts whose images still need fetching,
hand-correction candidates) live in each archive's own notes, alongside
its `fixups/`.
