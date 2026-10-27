"""Sign in to a generated FastAPI app through the mock OpenID Connect provider (ADR 0020).

The script starts the mock provider of `scripts/mock_oidc.py`, and the
app on the machine with SQLite (`uv run fastapi run`). The settings of
each provider of the definition point to the mock provider. Then the
script does the steps of a browser for each provider: the start, the
sign-in at the provider, and the callback. A provider that makes users
signs in a new user, and `/auth/me` gives the user of the token. A
provider that does not make users refuses the unknown user (403). With
the first provider, the script also checks the callback to a page of a
front end (`return_to`). A provider with the parameter
`identity_provider` (`authorize_params`) signs in at the mock user pool of
Amazon Cognito, whose ID tokens do not mark the email address as
verified: the provider needs `trust_email`. A provider with `roles` signs
in one user with each group of `roles.map` in turn, and then without a
group: `/auth/me` gives the role of the group each time, and at last the
default role, or the app refuses the sign-in (403). A provider with
`sign_out` sends the browser of the sign-out route to the logout endpoint
of the mock provider, with the client ID and the page after the sign-out,
and the mock provider sends it back to the page.

Run it from the repository root, with an app that a check script
generated and installed (`uv sync`):

    uv run scripts/check_provider_sign_in.py <definition> <app folder>

It uses the ports 8430 (the app) and 9430 (the mock provider).
"""

import argparse
import http.cookiejar
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

import mock_oidc

from appgen.dsl import load_definition
from appgen.dsl.auth import Provider

APP_PORT = 8430
APP_URL = f"http://127.0.0.1:{APP_PORT}"
FRONT_END = "http://localhost:5173"


class CheckError(Exception):
    """A check of the sign-in failed."""


def log(message: str) -> None:
    print(f"provider-sign-in: {message}", flush=True)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Browser:
    """An HTTP client with cookies that does not follow redirects, as the steps of a browser."""

    def __init__(self) -> None:
        cookies = urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        self.opener = urllib.request.build_opener(cookies, _NoRedirect())

    def get(self, url: str, headers: dict[str, str] | None = None) -> tuple[int, Any, str]:
        """Return the status, the headers, and the body of a GET request."""
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, response.headers, response.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read().decode(errors="replace")


def _expect(status: int, expected: int, what: str, body: str) -> None:
    if status != expected:
        raise CheckError(f"{what} gave the status {status}, not {expected}: {body[:500]}")


def sign_in(
    browser: Browser,
    name: str,
    provider: mock_oidc.MockProvider,
    email: str,
    return_to: str | None = None,
    groups: tuple[str, ...] = (),
) -> tuple[int, Any, str]:
    """Do the steps of the browser, and return the answer of the callback. The mock provider
    gives the user the groups (the claim `groups`, or `custom:groups` in the user pool)."""
    query = f"?{urlencode({'return_to': return_to})}" if return_to else ""
    status, headers, body = browser.get(f"{APP_URL}/auth/providers/{name}/start{query}")
    _expect(status, 302, f"GET /auth/providers/{name}/start", body)
    location: str = headers["Location"]
    if not location.startswith(f"{provider.authorization_endpoint}?"):
        raise CheckError(f"The start sent the browser to {location}, not to the provider.")
    mock_query = {"login_hint": email} | ({"groups": ",".join(groups)} if groups else {})
    status, headers, body = browser.get(f"{location}&{urlencode(mock_query)}")
    _expect(status, 302, "the sign-in at the mock provider", body)
    callback: str = headers["Location"]
    if not callback.startswith(f"{APP_URL}/auth/providers/{name}/callback?"):
        raise CheckError(f"The provider sent the browser to {callback}, not to the callback.")
    return browser.get(callback)


def me_of(body: str) -> dict[str, Any]:
    """Return the user of the token of the answer of a callback (`GET /auth/me`)."""
    token = json.loads(body)["access_token"]
    status, _, body = Browser().get(
        f"{APP_URL}/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    _expect(status, 200, "GET /auth/me", body)
    me: dict[str, Any] = json.loads(body)
    return me


def check_roles(
    name: str, provider: Provider, mock: mock_oidc.MockProvider, role_field: str
) -> None:
    """Sign in one user with each group of `roles.map` in turn, and then without a group."""
    assert provider.roles is not None
    email = f"{name}.grouped@example.com"
    for group, role in provider.roles.map.items():
        status, _, body = sign_in(Browser(), name, mock, email, groups=(group,))
        _expect(status, 200, f"the callback of {name} with the group {group}", body)
        found = me_of(body).get(role_field)
        if found != role:
            raise CheckError(f"The group {group} gave the role {found}, not {role}.")
        log(f"{name}: the group {group} gives the role {role}")
    status, _, body = sign_in(Browser(), name, mock, email)
    if provider.default_role is None:
        _expect(status, 403, f"the sign-in of a user without a group with {name}", body)
        log(f"{name}: the app refuses a user whose groups give no role (403)")
        return
    _expect(status, 200, f"the callback of {name} without a group", body)
    found = me_of(body).get(role_field)
    if found != provider.default_role:
        raise CheckError(f"No group gave the role {found}, not {provider.default_role}.")
    log(f"{name}: without a group, the user gets the default role {found}")


def check_sign_out(name: str, provider: Provider, mock: mock_oidc.MockProvider) -> None:
    """With `sign_out`: the sign-out route sends the browser to the logout endpoint, and the
    logout endpoint sends it back to the page of `return_to`."""
    assert provider.sign_out is not None
    page = f"{FRONT_END}/sign-in"
    browser = Browser()
    status, headers, body = browser.get(
        f"{APP_URL}/auth/providers/{name}/sign-out?{urlencode({'return_to': page})}"
    )
    _expect(status, 303, f"GET /auth/providers/{name}/sign-out", body)
    location: str = headers["Location"]
    endpoint = mock_oidc.sign_out_url_of(mock_oidc.DEFAULT_PORT, provider.authorize_params)
    if not location.startswith(f"{endpoint}?"):
        raise CheckError(f"The sign-out sent the browser to {location}, not to {endpoint}.")
    count = len(mock.logouts)
    status, headers, body = browser.get(location)
    _expect(status, 302, "the logout endpoint of the mock provider", body)
    if headers["Location"] != page or len(mock.logouts) != count + 1:
        raise CheckError(f"The logout endpoint sent the browser to {headers['Location']}.")
    query = mock.logouts[-1]
    if query.get("client_id") != mock_oidc.DEFAULT_CLIENT_ID:
        raise CheckError(f"The logout request has the client ID {query.get('client_id')}.")
    log(f"{name}: the sign-out ends the session at the provider ({provider.sign_out.return_param})")
    status, _, body = browser.get(
        f"{APP_URL}/auth/providers/{name}/sign-out?{urlencode({'return_to': 'https://x.test/'})}"
    )
    _expect(status, 422, "the sign-out with a return_to of another origin", body)


def check_provider(
    name: str, provider: Provider, mock: mock_oidc.MockProvider, first: bool
) -> None:
    if mock.identity_provider:
        log(f"{name}: the mock user pool of Amazon Cognito with {mock.identity_provider}")
    email = f"{name}.user@example.com"
    status, _, body = sign_in(Browser(), name, mock, email)
    if not provider.create_users:
        _expect(status, 403, f"the sign-in of an unknown user with {name}", body)
        log(f"{name}: the app refuses an unknown user (403)")
        return
    _expect(status, 200, f"the callback of {name}", body)
    me = me_of(body)
    if email not in me.values():
        raise CheckError(f"GET /auth/me gave {me}, not the user {email}.")
    log(f"{name}: a new user signs in, and GET /auth/me gives the user")
    if first:
        status, headers, body = sign_in(Browser(), name, mock, email, return_to=f"{FRONT_END}/home")
        _expect(status, 303, f"the callback of {name} with return_to", body)
        page, _, fragment = headers["Location"].partition("#")
        if page != f"{FRONT_END}/home" or "access_token" not in parse_qs(fragment):
            raise CheckError(f"The callback sent the browser to {headers['Location']}.")
        log(f"{name}: the callback gives the token to the page of return_to")


def wait_for(url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + float(os.environ.get("APPGEN_SMOKE_TIMEOUT", "180"))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CheckError("The app stopped.")
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise CheckError(f"{url} did not answer.")


@contextmanager
def started(app: Path, providers: dict[str, Provider], temp: Path) -> Generator[None]:
    """Start the app with the mock provider as each provider, and stop it at the end."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env |= {
        "DATABASE_URL": f"sqlite+aiosqlite:///{temp / 'local.db'}",
        "AUTH_SECRET": "check-provider-sign-in",
        "CORS_ORIGINS": json.dumps([FRONT_END]),
        "PUBLIC_URL": APP_URL,
        "LOG_JSON": "false",
    }
    for name, provider in providers.items():
        port = mock_oidc.DEFAULT_PORT
        env[f"{name.upper()}_ISSUER"] = mock_oidc.issuer_of(port, provider.authorize_params)
        if provider.sign_out is not None and provider.sign_out.endpoint is not None:
            sign_out_url = mock_oidc.sign_out_url_of(port, provider.authorize_params)
            env[f"{name.upper()}_SIGN_OUT_URL"] = sign_out_url
        env[provider.client_id_env] = mock_oidc.DEFAULT_CLIENT_ID
        env[provider.client_secret_env] = mock_oidc.DEFAULT_CLIENT_SECRET
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=app, env=env, check=True)
    command = ["uv", "run", "fastapi", "run", "app/main.py", "--port", str(APP_PORT)]
    output = temp / "app.log"
    with output.open("w") as out:
        process = subprocess.Popen(
            command, cwd=app, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
    try:
        wait_for(f"{APP_URL}/health", process)
        yield
    except CheckError:
        print(output.read_text(), flush=True)
        raise
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("definition", type=Path)
    parser.add_argument("app", type=Path, help="The folder of the generated FastAPI app.")
    args = parser.parse_args()
    definition = load_definition(args.definition)
    auth, access = definition.auth, definition.access
    if auth is None or not auth.providers:
        parser.error(f"{args.definition} has no providers in auth.providers.")
    try:
        with (
            tempfile.TemporaryDirectory(prefix="appgen-provider-sign-in.") as temp,
            mock_oidc.serving() as plain,
            started(args.app.resolve(), auth.providers, Path(temp)),
        ):
            for index, (name, provider) in enumerate(auth.providers.items()):
                pool = "identity_provider" in provider.authorize_params
                mock = plain.cognito if pool and plain.cognito else plain
                check_provider(name, provider, mock, first=index == 0)
                if provider.roles is not None and access is not None:
                    check_roles(name, provider, mock, access.role_field)
                if provider.sign_out is not None:
                    check_sign_out(name, provider, mock)
    except (CheckError, subprocess.CalledProcessError) as error:
        print(f"provider-sign-in: failed: {error}", file=sys.stderr)
        return 1
    log("passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
