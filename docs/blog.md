# The blog: classnode.co/blog/ and its writers

Classnode's own blog. Published posts are pages of the public site
(`docs/website.md`); writing and reviewing them happens on the portal, at
`app.classnode.co/write/`, by blog accounts that reach nothing else. Mockups:
`docs/mockups/blog/` (approved 16 October 2026, with the editor on the portal).

Code: `blog/` (models, the workflow, the Markdown, the pictures, the sign-in,
both sets of views), `static/blog/blog.css` (the public pages),
`static/write/` (the writing side's stylesheet and the editor's module),
`urls_site.py` and `urls_public.py` (the routes). Tests: `blog/tests/`,
`tests/js/blog_editor.test.js` and `tests/ui/blog.test.js`.

**Not built, on purpose:** comments, likes, newsletters, scheduled publishing,
tag pages, deleting a post.

## The public pages

- **`/blog/`**: every published post, newest first, twelve to a page
  (`/blog/page/2/` and on; `/blog/page/1/` is a 404, since it is `/blog/`).
  The newest leads the first page beside its cover. With nothing published it
  says **"First posts coming soon"** and links to the features, which is how
  the blog ships: no post, no writer and no author is made by any migration or
  command.
- **`/blog/<slug>/`**: one published post. The title, the summary, the writer,
  the date and the minutes to read in the top band, the cover, the words in
  one column of 68 characters, the tags, three more posts and the demo band.
- **Server-drawn**, through `website.views.site_page`, with the site's header
  and footer; **Blog** is in the header's nav, the phone menu and the footer's
  Product column. No script but the site's own (closing the phone menu), and
  the Article data, which no browser runs.
- **Each post's head is its own**: its SEO title (or its title) as `<title>`,
  its SEO description (or its summary) as the description, its canonical
  address (`https://classnode.co/blog/<slug>/`), `og:type` article, and its
  cover as the Open Graph and X image (1200 x 630, which is what the cover is
  cut to), with the cover's description as the image's alt. **Article
  structured data**: headline, description, image, first published, last
  changed, the writer, Classnode Edtech Limited as publisher, the page.
- **The sitemap** lists `PAGES` (now with `/blog/`), then every published post
  with its `lastmod`, and nothing else.
- **Nothing scrolls the page sideways**: a Markdown table scrolls inside the
  article (`.post-table`), code inside its block, and a long word or address
  breaks where it has to (`overflow-wrap: anywhere`).
- **Pictures** are served by `/blog/images/<key>.webp` (and `-small.webp`, half
  as wide, for a phone's `srcset`), from the database, only while their post
  is published, with an hour's cache. Each is drawn with its width and height,
  lazily below the first screen; the cover is preloaded at high priority.

## Drafts and review are never public

There is no switch on classnode.co that shows anything but a published post.
A draft or a post in review is a 404 at its address, its pictures are 404s,
it is not on the list and not in the sitemap. The writing side is routed on
the portal alone (`urls_public.py`), where every page is noindex in its header
and its head (`website.crawlers`, `templates/design/head.html`). A writer's
full preview (`/write/posts/<id>/view/`) is drawn on the portal by the same
part the public page uses (`blog/parts/article.html`), with its pictures from
`/write/images/`, which answers only the post's writer and the editors.

## Blog accounts

`accounts.User.blog_role`: "writer", "editor" or blank. A login with one is a
**blog account and nothing else**, held by three rules, each on its own:

1. **Never platform staff or a superuser**: `blog_account_is_not_staff`, a
   check constraint on the row.
2. **Never a membership at a school**: two triggers (`accounts/migrations/0017`),
   one on each table, so neither a membership for a blog account nor a blog
   role for somebody with a membership can be written by any path.
3. **`blog.middleware.BlogAccountMiddleware`** refuses a blog account on every
   school's host, whatever else is true of it, and on every portal page but
   `/write/`, `/api/csrf/` and `/api/logout/` (so `/platform/`, its handover,
   its API, the admin and the doors are refused). The 403 says "This account
   is for Classnode's blog only." (`accounts.refusals.BlogAccountOnly`). It
   reads the user the request already loads and nothing else, and asks nothing
   on classnode.co, where it would read a session on every public page.

So a writer can never reach any school's data or `/platform/`, and the owner,
who is platform staff, uses another address for the blog (a `+blog` one works).
Accounts are made by the operator:

    python manage.py blog_account kemi@example.com --name "Kemi Oladipo" --role writer
    python manage.py blog_account tunde@example.com --role editor
    python manage.py blog_account kemi@example.com --remove

## Signing in

`/write/sign-in/`: an email, then a six-digit code sent to it (`blog.signin`).
The platform's email-code sign-in, reused: `generate_code()` and `hash_code()`
from `accounts.guardian_contacts` (only the SHA-256 is kept), five guesses and
fifteen minutes (`MAX_VERIFICATION_ATTEMPTS`, `DEFAULT_VERIFICATION_TTL`), one
live code per account, sealed on the queue and sent off the request by the
email provider every code goes through (`blog.tasks`, `messaging.providers`,
the `SIGN_IN_CODE` words), at most five sends an hour, and the throttle in
`accounts.throttling`. Its own table (`blog.SignInCode`) and door, because a
guardian's codes belong to a guardian's channel, which goes dormant and is
woken by a school.

**One answer for every address**: "If that address belongs to a blog account,
a code has been sent to it." whether it does or not, and the send is after the
commit on a worker, so the time taken says nothing either. One sentence for
every code that does not work. The throttle's bucket is `SignInScope.BLOG_EMAIL`,
so guessing at a writer's address closes no guardian's door.

## Draft, In review, Published

`blog.workflow` is the one place that decides, and every view asks it:

| who | may |
| --- | --- |
| a writer | create posts; edit their own while a draft; send it for review |
| an editor | everything, on every post: edit in any state, publish (from review, or a draft), send back with a note, unpublish |
| anybody else | nothing; `/write/` sends them to sign in, or refuses them |

- **Publishing needs a whole post** (`workflow.problems()`): a title, an
  address of its own, a summary, words, a cover and its description, an SEO
  title and description, and a description for every picture in the body. A
  writer is told the same list when they send it for review.
- **Send back** returns it to Draft with the editor's note, which the writer
  sees on their list and in the editor. Sending it again clears the note.
- **Unpublish** returns it to Draft: off the site, the list and the sitemap at
  once.
- **The address is fixed once published**, so a shared link keeps working.
- **A post a person may not open is a 404**, never a 403, so a writer cannot
  learn another writer's drafts exist.
- Every move locks the post's row first.
- **A field a request does not send is kept**, never blanked: Publish posted on
  its own changes nothing but the state.

## The editor

`/write/posts/<id>/`: one form that posts and redirects, so it saves with no
script. `static/write/app.js` is named by this page and no other, and never
by a page on classnode.co (a test reads every template for it). It adds:

- **The live preview**: the Markdown is sent as it is typed
  (`/write/posts/<id>/preview/`) and drawn and sanitised by the server exactly
  as the post will be, so the preview is never the module's guess.
- **The picture box**: a JPG, PNG or WebP, with a description that is required
  before it is sent. The server draws it again as WebP (`blog.images`): at
  most 1600 pixels wide in the body, a cover cut to 1200 x 630 from its middle,
  quality 80, each with a copy half as wide; nothing of the original file is
  kept, and a file over 10 MB or 40 megapixels is refused before it is
  decoded. In the Markdown it is `![what it shows](image:KEY)`, and only this
  post's own uploads are drawn.
- Counters on the title, summary, SEO title (60) and SEO description (155),
  and a search-result preview.
- **On a phone**: Write, Preview and Details as tabs, and the two main buttons
  in a bar fixed to the bottom of the screen. The form is padded by the bar's
  height plus the safe area, so the bar never covers a word. The viewport says
  `interactive-widget=resizes-content`, so Chrome on Android shrinks the page
  for the keyboard and the bar rides above it; where a browser does not, the
  module lifts the bar by the keyboard's height (`--keyboard`, from the visual
  viewport).

## Markdown, and what it may become

`blog.markdown.render()`: Python-Markdown (tables, fenced code), then **nh3**
with an allowlist: paragraphs, h2 to h4 (a `#` is drawn as h2: the page's
title is its one h1), emphasis, code, quotes, lists, links (`http`, `https`
and `mailto`, with `rel="noopener noreferrer"`), tables and our own pictures.
`<script>` and `<style>` go with everything inside them, and so do frames,
objects, embeds, forms and SVG; every `on…` handler, `style` and `class` is
dropped; any `<img>` that is not one of this post's uploads is dropped. The
only markup added after the sanitiser is our own wrapper round a table.

## The lists on /write/

`/write/` (a person's own posts) and `/write/review/` (editors only: in review
first, oldest at the top, then Published and Drafts). On a phone each row is a
card (`table.stack`), and the tab row scrolls sideways with its last 32px
fading out and room past the last tab, so nothing is cut where it stops. The
top bar's links (Your posts, Review queue, View the blog) and Sign out are in a
menu on a phone.

## What holds it

- `blog/tests/test_access.py`: writer, second writer, editor, school staff,
  platform staff and nobody signed in, against every page and move; two
  schools. The two controlled rules are below.
- `blog/tests/test_public.py`: the empty state, nothing seeded, drafts and
  posts in review never public (page, pictures, list, sitemap), unpublishing,
  the head and the Article data, one h1, scripts, pages, the nav and footer
  links, and a script tag in a published post's Markdown stripped.
- `blog/tests/test_markdown.py`, `test_images.py`, `test_signin.py`: the
  sanitiser, the pictures and the door.
- `tests/js/blog_editor.test.js`: the editor's pure parts.
- `tests/ui/blog.test.js`: in Chromium, from an empty blog through a writer's
  post, refused when the writer publishes it, published by an editor; every
  page at 320, 375, 414, 768 and 1280, held to no sideways scroll, 44px
  targets and 15px phone text, and photographed; the editor's bar never
  covering the post and sitting above a keyboard.

### The controls

Each rule was broken in the code, its test seen red, and the code restored
and seen green, on 16 October 2026:

- **A writer cannot publish**: the editor check in `workflow.publish()`
  removed. `WriterCannotPublishTests` failed (a writer's publish answered 302
  and the post was on the site); restored, green.
- **A writer cannot reach a school's data**: the school-host refusal in
  `BlogAccountMiddleware` removed. `test_even_holding_a_membership_the_trigger_should_have_refused`
  failed (the writer, holding a bursar's membership the trigger had been got
  round for, read Sunrise's fee books: `/api/fees/classes/` answered 200), and
  so did every other test in the class; restored, green. And the triggers
  dropped from the migration: `test_a_blog_account_cannot_be_given_a_membership`
  and `test_a_member_of_a_school_cannot_be_made_a_blog_account` failed
  (IntegrityError not raised); restored, green.

## Measured

Lighthouse 12.8.2, mobile, 3 runs each against a local server with `DEBUG`
off and the static files served by WhiteNoise as in production, six published
posts in place (16 October 2026):

| page | performance | accessibility | best practices | SEO | LCP | CLS | TBT |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/blog/` | 100, 100, 100 | 100 | 76 | 100 | 1.7 s | 0 | 0 ms |
| a post | 100, 100, 100 | 100 | 76 | 100 | 1.7 s | 0 | 0 ms |

Best practices loses only to the local server being plain HTTP (production is
HTTPS behind Caddy) and to `/favicon.ico`, which is a 404 on every page of the
site, the homepage included, and is not the blog's.
