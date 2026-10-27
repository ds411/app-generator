# 0020. Sign-in with OpenID Connect providers

- Date: 2026-10-24
- Deciders: Maintainers

## Status

Accepted

## Context

ADR 0011 gives the apps a sign-in with a user name and a password, and
leaves out identity providers: a provider is an external service, and
each test and each local run would need one. Many organizations want
their users to sign in with the account of the organization, and to
keep no passwords in the app.

The authorization code flow of OpenID Connect with PKCE (RFC 7636) is
the usual flow for a browser. The app must check the ID token: the
signature with a key of the provider (its JWKS), the issuer, the
audience, the end time, and the nonce of the flow. The check of a
signed token (JWS) needs a JOSE package. The sign-in had no package of
its own until now.

## Decision

- The key `auth.providers.<name>` adds a provider: the issuer URL, the
  environment variables of the client ID and the client secret, the
  scopes, the claim that gives the user name (`username_claim`, default
  `email`), and `create_users`, `default_role`, and `claims` for the
  users that a first sign-in makes. Without `create_users`, an unknown
  user name gives 403. `auth.password: false` turns off the sign-in with
  a password.
- The definition holds the `https` issuer of production. The setting
  `<NAME>_ISSUER` of each app changes it, for example for a test
  provider.
- FastAPI: `GET /auth/providers/<name>/start` reads the discovery
  document, and sends the browser to the provider with a state, a
  nonce, and a PKCE challenge (S256). A signed cookie (HttpOnly,
  SameSite=Lax, 10 minutes) holds the state, the nonce, and the
  verifier until the callback. `GET /auth/providers/<name>/callback`
  checks the state, changes the code for the tokens (client secret with
  the basic scheme), checks the ID token, finds the user by the user
  name, and gives the bearer token of ADR 0011. The app accepts only
  asymmetric algorithms, and a clock difference of 60 seconds.
- With `return_to`, the callback sends the browser to a page of a front
  end, with the token (or the error) in the fragment of the URL. The
  origin of the page must be in `CORS_ORIGINS`, so that the app sends
  no token to another site. The fragment does not go to the servers.
- The package of the token check is PyJWT with its `crypto` extra
  (`pyjwt[crypto]`, and so `cryptography`). PyJWT is small, typed, and
  widely used, and it reads a JWKS. `joserfc` would also work, but it
  has fewer users, and the apps need only the check of a signed token.
  The app calls the provider with `httpx`, which the apps have already.
- The tests of each generated app use a fake provider in the same
  process (`httpx.MockTransport`, a test key of `cryptography`). The
  checks of the repository use a mock provider over HTTP:
  `scripts/mock_oidc.py`. It uses only the standard library (an RSA key
  and RS256 signatures in pure Python), so the repository has no new
  package. `scripts/check_provider_sign_in.py` signs in to the room
  booking app and to `tests/fixtures/provider-sign-in.yaml` through it.
- All signed texts of the sign-in (the session tokens, the reset tokens,
  and the flow cookies) use one function with a purpose in the signed
  message, so that a text of one purpose is not valid for another.
- The front ends (update for #271): the sign-in page has a button for
  each provider, and no password form with `password: false`. The
  Next.js app has its own flow, with the same steps and checks as the
  FastAPI app: the route handlers `/auth/providers/<name>/start` and
  `/callback`, a signed flow cookie, and the session cookie of ADR 0011.
  It checks the ID token with `jose`: the usual JOSE package of
  JavaScript, with no dependencies. The React app with
  `x-react-data: api` uses the flow of the FastAPI app with `return_to`
  set to its page `/auth/callback`, which reads the token from the
  fragment. The React app with mock data signs in a mock user at once,
  as a demonstration. A failed sign-in opens the sign-in page with a
  fixed message for a code (`?error=unknown-user` or `?error=provider`),
  so that a link cannot put another text on the page.
- No page can use a path under `/auth/` with providers: the routes of
  the front ends use them.
- Amazon Cognito with a SAML identity provider (update for #483). A user
  pool of Cognito is an OpenID Connect provider, and it does the SAML
  part with an identity provider such as Microsoft Entra ID. Thus the
  apps need no SAML code. Two keys of a provider make this work:
  - `authorize_params` adds fixed parameters to the authorization
    request, for example `identity_provider: EntraID`, so that the user
    pool sends the user at once to Entra ID. The flow sets its own
    parameters after them, and the validator rejects their names
    (`reserved-name`), so that a definition cannot change the checks of
    the flow.
  - `trust_email: true` accepts an email address that the ID token does
    not mark as verified. The user pool sets `email_verified` to `false`
    for a SAML user when no attribute of the assertion maps to it, and
    Entra ID sends no such attribute. Without the key, the apps refuse
    such a token as before. With the key, the address also counts as
    verified for the removal of a password of a sign-up that is not
    verified (ADR 0023).
  `docs/cognito-entra-id.md` gives the setup. The mock provider
  `scripts/mock_oidc.py` also acts as a user pool: its issuer has a
  path, its endpoints are on another origin, it needs `identity_provider`,
  and its ID tokens have `email_verified: "false"`.
- Roles from the groups of the provider (update for #484). `roles` of a
  provider names a claim with the groups of the user (`claim`), and
  gives a role of `access` for each group (`map`). At each sign-in, the
  app sets the role field of the user to the first role of `map`, in
  the order of the definition, whose group is in the claim, else to
  `default_role`. Without `default_role`, the app refuses the sign-in
  (403 in the FastAPI app, `?error=no-role` in the Next.js app). The
  app sets the role at each sign-in, not only for a new user, so that a
  change of the groups at the provider reaches the app at the next
  sign-in. The role of a session that runs stays until the next sign-in.
  The claim can be a list, or one text: Cognito puts a SAML attribute
  with more than one value in a custom attribute as `[a, b]`. The apps
  accept a list, `[a, b]` (also as JSON), `a,b`, and `a`. The roles of
  memberships (ADR 0048) stay as they are: `roles` sets only
  `access.role_field`. The mock provider takes the groups from the
  mock parameter `groups` of the authorization request.
- The sign-out at the provider (update for #485). `sign_out` of a
  provider makes the sign-out of the app also end the session at the
  provider, so that the next person at a shared computer cannot sign in
  as the last user with one click. `true` uses the
  `end_session_endpoint` of the discovery document with `client_id` and
  `post_logout_redirect_uri` (OpenID Connect RP-Initiated Logout). The
  mapping form has `endpoint` and `return_param` for a provider without
  it: a user pool of Amazon Cognito has `GET /logout?client_id=...&logout_uri=...`
  on its domain, and no `end_session_endpoint`. The setting
  `<NAME>_SIGN_OUT_URL` changes the endpoint, as `<NAME>_ISSUER` changes
  the issuer. The request has no `id_token_hint`: the apps do not keep
  the ID token, and the client ID names the app.
  - Next.js: the session token keeps the name of the provider of the
    sign-in (`idp`). The sign-out action deletes the session cookie,
    and returns the logout URL with `<PUBLIC_URL>/sign-in` as the page
    after the sign-out. The sign-out button opens it. A session of a
    sign-in with a password signs out as before.
  - FastAPI: `GET /auth/providers/<name>/sign-out?return_to=<page>`
    checks the origin of `return_to` against `CORS_ORIGINS`, as the
    start does (422), and sends the browser to the logout URL (303). The
    app has no session of its own to end: the token stays valid until
    its end, as after each sign-out of ADR 0011. The React app with
    `x-react-data: api` keeps the provider of the sign-in in
    `sessionStorage`, deletes its token, and opens this route.
  - Without a logout URL (no `end_session_endpoint` and no `endpoint`),
    the apps end only the session of the app, and write a warning to the
    log: a sign-out must not fail.
  - The logout of Cognito does not end the session at Entra ID. SAML
    single logout is not in the apps.

## Consequences

- The FastAPI apps with providers have two new dependencies:
  `pyjwt[crypto]` and `httpx`.
- The app finds a user by a claim, by default the email address. A
  provider that lets users choose an unverified email address could
  give a sign-in as another user, so the app refuses `email_verified:
  false`. A claim such as `sub` with a matching field is safer, and
  `username_claim` allows it.
- The purpose in the signature of the session tokens is new, so the
  tokens of an earlier version of a generated app are not valid after
  the change. The users sign in again.
- The Next.js apps with providers have the dependency `jose`.
- The checks of the repository sign in through the mock provider in the
  front ends too: `scripts/auth_ui_test.py` with Next.js, and with React
  and the FastAPI app.
- `trust_email` moves the check of the address to the provider. The docs
  tell to use it only for a provider that gives only the addresses of
  the company. A sign-in that starts at the identity provider (for
  example the My Apps portal of Entra ID) has no `state`, and the apps
  refuse it.
- With `sign_out`, each front end needs its sign-in page as a sign-out
  URL at the provider. The logout of a provider can end the sessions of
  the user in other apps of the same provider too.
- With `roles`, the provider decides the role of each user: a change of
  the role in the app lasts only until the next sign-in of the user.
  A user who loses all groups of `map` keeps the role of the last
  sign-in until the next one.
