"""Webhooks with `format: email`: the inbound emails of a mail service (ADR 0030)."""

from pathlib import Path

from test_dsl_webhooks import codes, load

from appgen.dsl import load_definition, validate_definition
from appgen.dsl.webhooks import EMAIL_SCHEMES

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "inbound-email.yaml"

SUPPORT = """\
  support:
    path: /webhooks/support
    format: email
    provider: postmark
    signature: { scheme: basic, secret_env: SUPPORT_CREDENTIALS }
"""


def test_the_fixture_is_valid_and_has_each_mail_service() -> None:
    definition = load_definition(FIXTURE)

    assert validate_definition(definition) == []
    webhooks = definition.webhooks
    assert {w.provider for w in webhooks.values()} == set(EMAIL_SCHEMES)
    assert all(w.email for w in webhooks.values())
    assert webhooks["postmark"].signature.signature_header == "Authorization"
    assert webhooks["mailgun"].signature.signature_header == ""
    assert webhooks["mailgun"].signature.tolerance_seconds == 600


def test_a_valid_email_webhook_gives_no_diagnostic(tmp_path: Path) -> None:
    assert load(tmp_path, SUPPORT) == []


def test_an_email_webhook_needs_a_provider(tmp_path: Path) -> None:
    webhook = SUPPORT.replace("    provider: postmark\n", "")

    found = load(tmp_path, webhook)

    assert [(d.code, d.element_id) for d in found] == [("missing-key", "webhooks.support")]
    assert "mailgun, postmark, sendgrid" in (found[0].hint or "")


def test_the_scheme_is_a_scheme_of_the_mail_service(tmp_path: Path) -> None:
    stripe = SUPPORT.replace("scheme: basic", "scheme: stripe")
    mailgun = SUPPORT.replace("scheme: basic", "scheme: mailgun")
    sendgrid = SUPPORT.replace("provider: postmark", "provider: mailgun").replace(
        "scheme: basic", "scheme: mailgun"
    )

    found = load(tmp_path, stripe)
    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "webhooks.support")]
    assert "'basic'" in (found[0].hint or "")
    assert codes(tmp_path, mailgun) == [("invalid-option", "webhooks.support")]
    assert load(tmp_path, sendgrid) == []


def test_an_email_webhook_has_no_body_and_no_event_id(tmp_path: Path) -> None:
    webhook = SUPPORT + (
        "    body: { document: events.yaml, schema: Event }\n    event_id: { header: X-Id }\n"
    )

    found = load(tmp_path, webhook)

    assert [(d.code, d.element_id) for d in found] == [
        ("invalid-option", "webhooks.support"),
        ("invalid-option", "webhooks.support"),
    ]
    assert "'body'" in found[0].message
    assert "'Message-ID'" in found[1].message


def test_a_json_webhook_takes_no_provider_and_no_mailgun_scheme(tmp_path: Path) -> None:
    provider = SUPPORT.replace("    format: email\n", "")
    mailgun = provider.replace("    provider: postmark\n", "").replace(
        "scheme: basic", "scheme: mailgun"
    )
    basic = provider.replace("    provider: postmark\n", "")

    assert codes(tmp_path, provider) == [("invalid-option", "webhooks.support")]
    assert codes(tmp_path, mailgun) == [("invalid-option", "webhooks.support")]
    # HTTP Basic suits any sender, also one with JSON events.
    assert load(tmp_path, basic) == []


def test_the_scheme_basic_takes_no_keys_of_the_other_schemes(tmp_path: Path) -> None:
    webhook = SUPPORT.replace(
        "secret_env: SUPPORT_CREDENTIALS", "secret_env: SUPPORT_CREDENTIALS, tolerance_seconds: 60"
    )

    found = load(tmp_path, webhook)

    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "webhooks.support")]
    assert "'tolerance_seconds'" in found[0].message
