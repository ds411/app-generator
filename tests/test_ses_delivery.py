"""The delivery of the emails with Amazon SES: `auth.delivery: ses` (#491).

The apps send the messages of the sign-in and the emails of the notices
(ADR 0044) with SES.
"""

import ast
import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from appgen.bindings import fastapi, nextjs
from appgen.bindings.nextjs.versions import SES_PACKAGES
from appgen.cli import app
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "room-booking" / "app.yaml"
TEXT = EXAMPLE.read_text().replace("  delivery: smtp\n", "  delivery: ses\n")
FILES = ROOT / "tests" / "fixtures" / "files.yaml"


def files(binding: Binding, text: str = TEXT, path: Path = EXAMPLE) -> dict[str, str]:
    definition = load_definition_text(text, str(path))
    return {f.path: f.content for f in generate(definition, binding).files}


def knative_files(binding: Binding) -> dict[str, str]:
    """Return the files of the example with both deployment targets."""
    key = f"x-{binding.name}-deploy"
    return files(binding, TEXT.replace("app:\n", f"app:\n  {key}: [kubernetes, knative]\n", 1))


def test_the_delivery_with_ses_is_valid_and_needs_an_email_field() -> None:
    definition = load_definition_text(TEXT, str(EXAMPLE))
    assert validate_definition(definition) == []
    assert definition.auth is not None and definition.auth.delivery == "ses"
    address = definition.address_field()
    assert address is not None
    entity = definition.entities[definition.auth.user_entity]
    text = TEXT.replace(f"      {address}: {{ type: email", f"      {address}: {{ type: string")
    without = load_definition_text(text, str(EXAMPLE))
    assert entity.fields[address].type == "email"

    found = [d for d in validate_definition(without) if d.element_id == "auth"]

    assert [d.code for d in found] == ["unsuitable-field"]
    assert found[0].message.startswith("The delivery 'ses' needs a field of the type 'email'")


def test_the_fastapi_app_sends_the_messages_with_boto3_in_a_thread() -> None:
    app_files = files(fastapi.BINDING)
    assert "app/core/messages_ext.py" not in app_files
    assert "from app.core.mail import deliver_message\n" in app_files["app/core/auth.py"]
    mail = app_files["app/core/mail.py"]
    ast.parse(mail)
    assert "# @trace auth.password_reset file\n" in mail
    assert "# @trace auth.sign_up.verify_email file\n" in mail
    assert '    return boto3.client(\n        "sesv2",\n' in mail
    assert "        await asyncio.to_thread(send_email, settings, email)\n" in mail
    assert "# @trace notifications.booking_confirmed file\n" in mail
    assert "smtplib" not in mail
    job = app_files["app/jobs/notice_emails.py"]
    assert "from app.core.mail import deliver_email, new_email\n" in job
    assert "At the first error of Amazon SES, the run\n" in job
    job_tests = app_files["tests/jobs/test_notice_emails.py"]
    ast.parse(job_tests)
    assert '            "ses_from": "no-reply@example.com",\n' in job_tests
    assert "smtp" not in job_tests
    config = app_files["app/core/config.py"]
    assert '    ses_from: str = ""\n' in config
    assert '    aws_region: str = ""\n' in config
    assert "smtp_host" not in config
    pyproject = app_files["pyproject.toml"]
    assert '    "boto3>=1.43",\n' in pyproject
    assert '    "types-boto3-lite[sesv2]>=1.43",\n' in pyproject
    assert "AWS_REGION=\nSES_FROM=\n" in app_files[".env.example"]
    assert "SMTP_HOST" not in app_files[".env.example"]
    assert "SES_FROM=no-reply@example.com\n" in app_files["deploy/kubernetes/config.env"]
    secrets = app_files["deploy/kubernetes/secret.example.env"]
    assert "SMTP" not in secrets and "SES" not in secrets and "AWS" not in secrets
    assert "`ses:SendEmail`" in app_files["README.md"]
    tests = app_files["tests/test_mail.py"]
    ast.parse(tests)
    assert "from botocore.stub import Stubber\n" in tests
    assert "async def test_an_email_that_ses_rejects_gives_an_error_without_the_text(" in tests
    assert "async def test_a_message_goes_to_ses(" in tests
    knative = knative_files(fastapi.BINDING)["deploy/knative/service.yaml"]
    assert "            - name: SES_FROM\n" in knative
    assert "smtp-password" not in knative


def test_the_types_of_boto3_have_both_services_with_files_in_s3() -> None:
    marker = "  username_field: email\n"
    text = FILES.read_text().replace(marker, f"{marker}  password_reset: {{}}\n  delivery: ses\n")
    definition = load_definition_text(text, str(FILES))
    assert validate_definition(definition) == []

    pyproject = files(fastapi.BINDING, text, FILES)["pyproject.toml"]

    assert pyproject.count('"boto3>=1.43"') == 1
    assert '    "types-boto3-lite[s3,sesv2]>=1.43",\n' in pyproject


def test_the_nextjs_app_sends_the_messages_with_the_aws_sdk() -> None:
    app_files = files(nextjs.BINDING)
    assert "src/shared/auth/messages.ext.ts" not in app_files
    for path in ("src/shared/auth/actions.ts", "src/shared/auth/email-verification.ts"):
        assert 'import { deliverMessage } from "./mail";\n' in app_files[path]
    mail = app_files["src/shared/auth/mail.ts"]
    assert "// @trace auth.password_reset file\n" in mail
    assert 'import { SendEmailCommand, SESv2Client } from "@aws-sdk/client-sesv2";\n' in mail
    assert "    await sesClient().send(command);\n" in mail
    assert "// @trace notifications.booking_confirmed file\n" in mail
    job = app_files["src/app/jobs/notice-emails.ts"]
    assert 'import { type Email, sendEmail } from "@/shared/auth/mail";\n' in job
    assert "At the first error of Amazon SES, the run stops" in job
    package = json.loads(app_files["package.json"])
    name = "@aws-sdk/client-sesv2"
    assert package["dependencies"][name] == SES_PACKAGES[name]
    assert "nodemailer" not in package["dependencies"]
    assert "AWS_REGION=\nSES_FROM=\n" in app_files[".env.example"]
    assert "      SES_FROM: ${SES_FROM:-}\n" in app_files["compose.yaml"]
    assert "SES_FROM=no-reply@example.com\n" in app_files["deploy/kubernetes/config.env"]
    assert "SMTP" not in app_files["deploy/kubernetes/secret.example.env"]
    assert "`ses:SendEmail`" in app_files["README.md"]
    knative = knative_files(nextjs.BINDING)["deploy/knative/service.yaml"]
    assert "            - name: SES_FROM\n" in knative
    assert "smtp-password" not in knative


@pytest.mark.parametrize("binding", ["fastapi", "nextjs"])
def test_the_check_reports_no_gap_of_the_delivery(tmp_path: Path, binding: str) -> None:
    source = tmp_path / "app.yaml"
    source.write_text(TEXT)
    out = tmp_path / "out"
    runner = CliRunner()
    generated = runner.invoke(app, ["generate", str(source), "-b", binding, "-o", str(out)])
    assert generated.exit_code == 0, generated.output
    result = runner.invoke(app, ["check", str(source), str(out), "-f", "json"])
    report = json.loads(result.output)
    assert report["invalid"] == []
    gaps = {g["id"] for g in report["gaps"]}
    assert not {"auth.password_reset", "auth.sign_up.verify_email"} & gaps


def mock_ses() -> ModuleType:
    """Load `scripts/mock_ses.py`: the folder `scripts` is not a package."""
    spec = importlib.util.spec_from_file_location("mock_ses", ROOT / "scripts" / "mock_ses.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _send(port: int, key: str, to: str) -> tuple[int, dict[str, object], str | None]:
    """Send a request of `SendEmail` with an authorization header of an access key ID."""
    body = {
        "FromEmailAddress": "no-reply@example.com",
        "Destination": {"ToAddresses": [to]},
        "Content": {
            "Simple": {
                "Subject": {"Data": "Hello"},
                "Body": {"Text": {"Data": "Open http://localhost/a?token=x"}},
            }
        },
    }
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={key}/20261027/us-east-1/ses/aws4_request, "
        f"SignedHeaders=content-type;host;x-amz-date, Signature={'0' * 64}"
    )
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v2/email/outbound-emails",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": authorization},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read()), None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), error.headers.get("x-amzn-ErrorType")


def test_the_mock_ses_server_keeps_each_message(tmp_path: Path) -> None:
    module = mock_ses()
    out = tmp_path / "messages.jsonl"
    out.write_text("an old line\n")
    key = module.ACCESS_KEY_ID
    with module.serving(port=0, out=out) as outbox:
        sent = _send(outbox.port, key, "a@example.com")
        wrong_key = _send(outbox.port, "AKIAOTHER", "a@example.com")
        rejected = _send(outbox.port, key, f"b@{module.REJECTED_DOMAIN}")
        env = module.app_env(outbox.port)
        assert len(outbox.messages) == 1

    assert sent == (200, {"MessageId": "mock-ses-1"}, None)
    assert (wrong_key[0], wrong_key[2]) == (403, "UnrecognizedClientException")
    assert (rejected[0], rejected[2]) == (400, "MessageRejected")
    (line,) = out.read_text().splitlines()
    message = json.loads(line)
    assert message["to"] == ["a@example.com"]
    assert message["subject"] == "Hello"
    assert message["text"] == "Open http://localhost/a?token=x"
    assert env["AWS_ENDPOINT_URL_SESV2"].endswith(f":{outbox.port}")
    assert env["AWS_ACCESS_KEY_ID"] == key
