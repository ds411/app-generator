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
- The front ends add the buttons and the callback in a separate story.
  Until then, Next.js has a gap file for each provider, and React
  excludes the kind `provider`.
