# 0032. Pages in frames of other websites

- Date: 2026-10-26
- Deciders: Maintainers

## Status

Accepted

## Context

A booking page or a form of an app can work on the website of a
customer: the website shows the page in an `iframe`. The browser decides
if a page can show in a frame of another website:

- The header `Content-Security-Policy: frame-ancestors <sources>` names
  the websites that can show the page in a frame. A browser does not
  show the page in a frame of another website. The older header
  `X-Frame-Options` cannot name a list of websites.
- Without the header, each website can show each page of the app in a
  frame. A hidden frame can then make a user click a button of the app
  on another website (clickjacking). The apps did not send the header.
- The Next.js app sets the headers of a path in `next.config.ts`. The
  React app is static files: only the server of the files can send a
  header, and its Docker image serves them with nginx. A client route of
  React Router gets `index.html` from nginx.
- In a frame, the app shell of a page (the sidebar, the top bar, and the
  header with the app title) takes the space of the website, and its
  links open the other pages of the app in the frame.
- In a frame of another website, a browser can block the cookies of the
  app, so the sign-in of the app does not work there.

## Decision

- A page takes `embed`: a list of origins (`https://`, a host name in
  lower case, and an optional port). The validator reports `embed` on a
  page that is not public (the definition has `auth`, and the page is
  not in `auth.public_pages`), on a page with `layout`, and an origin
  that is not an https origin.
- A page with `embed` shows without the app shell: in the route group
  `app/(embed)/` of the Next.js app, and in `EmbedLayout` of the React
  router. The page search does not find it.
- The page sends `Content-Security-Policy: frame-ancestors 'self'
  <origins>`. All other pages send `frame-ancestors 'self'`: other
  websites cannot show them in a frame.
- The Next.js app sends the headers from `headers()` in
  `next.config.ts`: one rule for all paths, then one rule for each page
  with `embed` (the last rule of a path wins). The React app sends them
  from `nginx.conf`: a `map` of the request URI gives the sources, so an
  internal redirect to `index.html` keeps the sources of the page.
- The project tracker example has the page `holiday_widget` with the
  public holidays for `https://partner.example`. The UI tests open the
  page in a frame of a test website at that origin and at another
  origin, and open a page without `embed` in a frame of that origin.

## Consequences

- An app author allows a list of websites in one line, and the docs
  give the `iframe` of the website. A script that makes the frame is not
  in this version.
- The apps that other websites showed in frames before stop working
  there. The fix is `embed` on the page.
- Vite (`pnpm dev` and `pnpm preview` of the React app) and other
  servers of the static files do not send the headers of `nginx.conf`.
  `next dev` sends the headers of `next.config.ts`.
- A link on a page in a frame opens the other page in the frame too.
  The pages in a frame are usually one form or one view.
- A browser that blocks the cookies of the app in the frame shows the
  page in the language of the browser, not the language that the user
  selected in the app.
