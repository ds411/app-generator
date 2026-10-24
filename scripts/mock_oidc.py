"""A mock OpenID Connect provider for the checks of the sign-in with a provider (ADR 0020).

The mock provider signs in each user at once, without a page: its
authorization endpoint sends the browser back to the app with a code.
The user is the email address in the parameter `login_hint` of the
authorization request, or else `mock.user@example.com`. The ID tokens
have the claims `sub`, `email`, `email_verified`, and `name`, and an RS256
signature with a key that the provider makes when it starts.

The provider checks the client ID and the client secret (the basic
scheme or the form), the redirect URI, the one-time code, and the PKCE
verifier (S256). It uses only the standard library: the RSA key and the
signatures are in pure Python.

Run it from the repository root:

    uv run scripts/mock_oidc.py [--port 9430] [--client-id ID] [--client-secret SECRET]

The issuer is `http://127.0.0.1:<port>`. Stop it with Ctrl-C.
`scripts/check_provider_sign_in.py` starts it in a thread.
"""

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

DEFAULT_PORT = 9430
DEFAULT_CLIENT_ID = "mock-client"
DEFAULT_CLIENT_SECRET = "mock-client-secret"
DEFAULT_EMAIL = "mock.user@example.com"
TOKEN_SECONDS = 300
# The DER prefix of a SHA-256 digest in a PKCS #1 v1.5 signature (RFC 8017, section 9.2).
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % d for d in range(3, int(p**0.5) + 1, 2))]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _is_prime(n: int, rounds: int = 40) -> bool:
    """The Miller-Rabin test."""
    if any(n % p == 0 for p in SMALL_PRIMES):
        return n in SMALL_PRIMES
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    for _ in range(rounds):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        # The two top bits make the product of two primes have 2 * bits bits.
        n = secrets.randbits(bits) | (3 << (bits - 2)) | 1
        if _is_prime(n):
            return n


@dataclass(frozen=True)
class RsaKey:
    """An RSA key for the RS256 signatures of the ID tokens."""

    n: int
    e: int
    d: int

    @classmethod
    def generate(cls, bits: int = 2048) -> RsaKey:
        e = 65537
        while True:
            p, q = _prime(bits // 2), _prime(bits // 2)
            phi = (p - 1) * (q - 1)
            if p != q and phi % e != 0:
                return cls(n=p * q, e=e, d=pow(e, -1, phi))

    @property
    def size(self) -> int:
        return (self.n.bit_length() + 7) // 8

    def sign(self, message: bytes) -> bytes:
        """Return the RSASSA-PKCS1-v1_5 signature of a message with SHA-256."""
        digest = SHA256_PREFIX + hashlib.sha256(message).digest()
        padded = b"\x00\x01" + b"\xff" * (self.size - len(digest) - 3) + b"\x00" + digest
        return pow(int.from_bytes(padded), self.d, self.n).to_bytes(self.size)

    def jwk(self, kid: str) -> dict[str, str]:
        """Return the public key as a JSON Web Key."""
        n = self.n.to_bytes(self.size)
        e = self.e.to_bytes((self.e.bit_length() + 7) // 8)
        return {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": _b64(n), "e": _b64(e)}


@dataclass
class MockProvider:
    """The state of the mock provider: the key, the client, and the open codes."""

    issuer: str
    client_id: str = DEFAULT_CLIENT_ID
    client_secret: str = DEFAULT_CLIENT_SECRET
    key: RsaKey = field(default_factory=RsaKey.generate)
    codes: dict[str, dict[str, str]] = field(default_factory=dict[str, dict[str, str]])
    lock: threading.Lock = field(default_factory=threading.Lock)

    def metadata(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        }

    def authorize(self, query: dict[str, str]) -> tuple[int, dict[str, Any] | str]:
        """Sign in the user at once. Return the URL of the callback, or an error."""
        if query.get("client_id") != self.client_id:
            return 400, {"error": "unauthorized_client"}
        if query.get("response_type") != "code" or "openid" not in query.get("scope", "").split():
            return 400, {"error": "invalid_request"}
        if query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
            return 400, {"error": "invalid_request", "error_description": "PKCE S256 is needed."}
        redirect_uri = query.get("redirect_uri", "")
        if not redirect_uri.startswith(("http://", "https://")):
            return 400, {"error": "invalid_request", "error_description": "No redirect_uri."}
        code = secrets.token_urlsafe(24)
        with self.lock:
            self.codes[code] = {
                "redirect_uri": redirect_uri,
                "challenge": query["code_challenge"],
                "nonce": query.get("nonce", ""),
                "email": query.get("login_hint") or DEFAULT_EMAIL,
            }
        answer = {"code": code} | ({"state": query["state"]} if "state" in query else {})
        separator = "&" if "?" in redirect_uri else "?"
        return 302, f"{redirect_uri}{separator}{urlencode(answer)}"

    def token(self, form: dict[str, str], authorization: str | None) -> tuple[int, dict[str, Any]]:
        """Change a code for an ID token."""
        client_id, client_secret = form.get("client_id"), form.get("client_secret")
        if authorization and authorization.startswith("Basic "):
            decoded = base64.b64decode(authorization.removeprefix("Basic ")).decode()
            user, _, password = decoded.partition(":")
            client_id, client_secret = unquote(user), unquote(password)
        if client_id != self.client_id or not hmac.compare_digest(
            client_secret or "", self.client_secret
        ):
            return 401, {"error": "invalid_client"}
        if form.get("grant_type") != "authorization_code":
            return 400, {"error": "unsupported_grant_type"}
        with self.lock:
            flow = self.codes.pop(form.get("code", ""), None)
        verifier = form.get("code_verifier", "")
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        if (
            flow is None
            or form.get("redirect_uri") != flow["redirect_uri"]
            or not hmac.compare_digest(challenge, flow["challenge"])
        ):
            return 400, {"error": "invalid_grant"}
        return 200, {
            "access_token": secrets.token_urlsafe(24),
            "token_type": "Bearer",
            "expires_in": TOKEN_SECONDS,
            "id_token": self.id_token(flow["email"], flow["nonce"]),
        }

    def id_token(self, email: str, nonce: str) -> str:
        now = int(time.time())
        name = email.partition("@")[0].replace(".", " ").title()
        claims = {
            "iss": self.issuer,
            "sub": hashlib.sha256(email.encode()).hexdigest()[:24],
            "aud": self.client_id,
            "iat": now,
            "exp": now + TOKEN_SECONDS,
            "nonce": nonce,
            "email": email,
            "email_verified": True,
            "name": name,
        }
        header = {"alg": "RS256", "typ": "JWT", "kid": "mock-key"}
        parts = [json.dumps(part, separators=(",", ":")).encode() for part in (header, claims)]
        signing_input = ".".join(_b64(part) for part in parts).encode()
        return f"{signing_input.decode()}.{_b64(self.key.sign(signing_input))}"


def _handler(provider: MockProvider) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _answer(self, status: int, body: dict[str, Any] | str) -> None:
            if isinstance(body, str):
                self.send_response(status)
                self.send_header("Location", body)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/.well-known/openid-configuration":
                self._answer(200, provider.metadata())
            elif url.path == "/jwks":
                self._answer(200, {"keys": [provider.key.jwk("mock-key")]})
            elif url.path == "/authorize":
                self._answer(*provider.authorize(query))
            else:
                self._answer(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/token":
                self._answer(404, {"error": "not_found"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            form = {k: v[0] for k, v in parse_qs(body).items()}
            self._answer(*provider.token(form, self.headers.get("Authorization")))

    return Handler


@contextmanager
def serving(
    port: int = DEFAULT_PORT,
    client_id: str = DEFAULT_CLIENT_ID,
    client_secret: str = DEFAULT_CLIENT_SECRET,
) -> Generator[MockProvider]:
    """Run the mock provider in a thread, and stop it at the end."""
    provider = MockProvider(f"http://127.0.0.1:{port}", client_id, client_secret)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(provider))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield provider
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument("--client-secret", default=DEFAULT_CLIENT_SECRET)
    args = parser.parse_args()
    with serving(args.port, args.client_id, args.client_secret) as provider:
        print(f"mock-oidc: the issuer {provider.issuer} is ready.", flush=True)
        with suppress(KeyboardInterrupt):
            threading.Event().wait()


if __name__ == "__main__":
    main()
