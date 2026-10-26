"""Tests of the messages of the FastAPI app in the language of the request (ADR 0010)."""

import ast
import re
from http import HTTPStatus
from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi, react
from appgen.bindings.fastapi.i18n import language_test
from appgen.bindings.fastapi.pysource import raise_problem, string
from appgen.bindings.shared.i18n import I18nPlan, LanguagePlan
from appgen.dsl import AppDefinition, load_definition, load_definition_text
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"
ROOM_BOOKING = ROOT / "examples" / "room-booking" / "app.yaml"
TITLES = {
    HTTPStatus(s).phrase for s in (400, 401, 403, 404, 405, 409, 413, 415, 422, 500, 501, 502)
}
"""The titles of the problem details that the API gives, as `t(HTTPStatus(status).phrase)`."""


def room_booking_in_two_languages() -> AppDefinition:
    # The rate limit in Redis has the messages of an unavailable store.
    redis = "app:\n  x-fastapi-rate-limit-store: redis\n"
    text = ROOM_BOOKING.read_text().replace("app:\n", redis, 1) + dedent(
        """\
        translations:
          default: en
          languages:
            en: { label: English }
            de:
              label: Deutsch
              locale: de-DE
              text:
                The user name or the password is not correct.: Das Passwort ist nicht korrekt.
        """
    )
    return load_definition_text(text, str(ROOM_BOOKING))


def files_of(definition: AppDefinition) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, fastapi.BINDING).files}


def test_the_api_selects_the_language_of_the_request() -> None:
    files = files_of(load_definition(EXAMPLE))

    i18n = files["app/core/i18n.py"]
    assert '    # @trace translations.languages.de\n    "de": "de",\n' in i18n
    assert 'DEFAULT = "en"' in i18n
    assert '        "Not Found": "Nicht gefunden",\n' in i18n
    assert "class LanguageMiddleware:" in i18n
    main = files["app/main.py"]
    assert "from app.core.i18n import LanguageMiddleware" in main
    # The middleware runs before the rate limit and after the log of the request.
    assert main.index("RateLimitMiddleware, limiter") < main.index("LanguageMiddleware)")
    assert main.index("LanguageMiddleware)") < main.index("RequestLogMiddleware)")
    assert '"app/core/i18n.py" = ["RUF001"]' in files["pyproject.toml"]
    assert "## Languages" in files["README.md"]


def test_the_problem_details_use_the_translations() -> None:
    files = files_of(load_definition(EXAMPLE))

    errors = files["app/core/errors.py"]
    assert "title=t(HTTPStatus(status).phrase)," in errors
    assert 'return problem_response(request, 422, t("The request is not valid."), items)' in errors
    assert 'return t("Use {count} or more characters.", count=context["min_length"])' in errors
    assert "msg=_input_message(item)" in errors
    repository = files["app/features/projects/repository.py"]
    assert "from app.core.i18n import t\n" in repository
    assert (
        'raise ProblemError(404, t("No {entity} has the ID {id}.", entity="Project", id=id))'
        in repository
    )
    assert "raise ProblemError(409, t(CONFLICT)) from error" in files["app/core/db.py"]
    assert 't("Cannot sort by' in files["app/core/pagination.py"]
    assert 'title=t("Too Many Requests"),' in files["app/core/rate_limit.py"]


def test_the_rules_the_workflows_and_the_sign_in_translate_their_messages() -> None:
    files = files_of(room_booking_in_two_languages())

    bookings = files["app/features/bookings/repository.py"]
    assert 'raise ProblemError(422, t("The end must be after the start."))' in bookings
    assert 'raise ProblemError(409, t("The room has another booking at this time."))' in bookings
    # The owner rule of the organizer also gives a translated 404.
    assert 't("No {entity} has the ID {id}.", entity="Booking", id=id)' in bookings
    workflows = files["app/core/workflows.py"]
    assert "t(message)" in workflows
    assert "\"The {field} cannot change from '{before}' to '{after}'.\"" in workflows
    auth = files["app/core/auth.py"]
    assert 'raise ProblemError(401, t("The user name or the password is not correct."))' in auth
    assert 'raise ProblemError(401, t("Sign in to use this endpoint."))' in auth
    access = files["app/core/access.py"]
    assert 'raise ProblemError(403, t("Your role may not do this operation."))' in access
    assert 'title=t("Service Unavailable"),' in files["app/core/rate_limit.py"]
    providers = files["app/core/providers.py"]
    assert 't("The sign-in has no valid flow. Sign in again."))\n' in providers
    assert 't("The ID token is not valid: {error}", error=error)) from error' in providers
    assert (
        "Translate the reason with `app.core.i18n.t"
        in files["app/features/bookings/validation_ext.py"]
    )
    # The generated test checks the message of a failed sign-in in two languages.
    test = files["tests/test_i18n.py"]
    assert '("de", "Das Passwort ist nicht korrekt."),' in test
    assert 'assert match_language("de-zz") == SECOND' in test


def test_an_api_without_translations_has_no_language() -> None:
    files = files_of(load_definition(ROOM_BOOKING))

    assert "app/core/i18n.py" not in files
    assert "tests/test_i18n.py" not in files
    assert not [path for path, content in files.items() if "app.core.i18n" in content]
    assert "LanguageMiddleware" not in files["app/main.py"]
    assert "per-file-ignores" not in files["pyproject.toml"]
    bookings = files["app/features/bookings/repository.py"]
    assert 'raise ProblemError(404, f"No Booking has the ID {id}.")' in bookings
    assert 'raise ProblemError(422, "The end must be after the start.")' in bookings


def test_the_react_api_client_asks_for_the_selected_language() -> None:
    text = EXAMPLE.read_text().replace("app:\n", "app:\n  x-react-data: api\n", 1)
    definition = load_definition_text(text, str(EXAMPLE))
    files = {f.path: f.content for f in generate(definition, react.BINDING).files}

    http = files["src/shared/api/http.ts"]
    assert 'import { getLocale, t } from "@/shared/lib/i18n";' in http
    assert 'headers["Accept-Language"] = getLocale();' in http
    plain = load_definition_text(
        ROOM_BOOKING.read_text().replace("app:\n", "app:\n  x-react-data: api\n", 1),
        str(ROOM_BOOKING),
    )
    plain_http = {f.path: f.content for f in generate(plain, react.BINDING).files}
    assert "Accept-Language" not in plain_http["src/shared/api/http.ts"]


def test_a_message_without_translations_is_a_literal_or_an_f_string() -> None:
    def problem(text: str, translated: bool = False, indent: int = 8, **values: str) -> str:
        return raise_problem(404, text, values, indent=indent, translated=translated)

    assert problem("No {entity} has the ID {id}.", entity='"Project"', id="id") == (
        'raise ProblemError(404, f"No Project has the ID {id}.")'
    )
    assert problem("The {x} is {y}.", x='"a"', y='"b"') == 'raise ProblemError(404, "The a is b.")'
    # A text without values keeps its braces.
    assert problem("Use {start}.") == 'raise ProblemError(404, "Use {start}.")'
    assert problem("A {b} {C}", b="value") == 'raise ProblemError(404, f"A {value} {{C}}")'
    assert problem("No {entity} has the ID {id}.", True, entity='"Project"', id="id") == (
        'raise ProblemError(404, t("No {entity} has the ID {id}.", entity="Project", id=id))'
    )


def test_a_long_message_has_the_format_of_ruff() -> None:
    long = "The end of the booking must be after the start of the booking, else it has no time."
    assert raise_problem(422, long, {}, indent=8, translated=False) == (
        f'raise ProblemError(\n            422,\n            "{long}",\n        )'
    )
    assert raise_problem(422, long, {}, indent=8, translated=True) == (
        "raise ProblemError(\n"
        "            422,\n"
        "            t(\n"
        f'                "{long}",\n'
        "            ),\n"
        "        )"
    )
    entity = '"ProjectMilestoneThing"'
    assert raise_problem(
        404,
        "No {entity} has the ID {id}.",
        {"entity": entity, "id": "id"},
        indent=8,
        translated=True,
    ) == (
        "raise ProblemError(\n"
        "            404,\n"
        '            t("No {entity} has the ID {id}.", entity="ProjectMilestoneThing", id=id),\n'
        "        )"
    )


def test_a_python_string_has_the_quotes_of_ruff() -> None:
    assert string("Plain") == '"Plain"'
    assert string("Grüße") == '"Grüße"'
    assert string("It's") == '"It\'s"'
    assert string('Say "hi"') == "'Say \"hi\"'"
    assert string('It\'s "a" b') == "'It\\'s \"a\" b'"
    assert string('a\\"b') == "'a\\\\\"b'"
    assert ast.literal_eval(string('a\\"b')) == 'a\\"b'


def plan(*languages: tuple[str, str]) -> I18nPlan:
    return I18nPlan(
        element_id="translations",
        default=languages[0][0],
        languages=[
            LanguagePlan(code=code, label=code, locale=locale, element_id=code, text={})
            for code, locale in languages
        ],
    )


def test_the_language_test_takes_tags_that_select_one_language() -> None:
    simple = language_test(plan(("en", "en"), ("de", "de")))
    assert simple is not None
    assert (simple.second.code, simple.second_tag, simple.near_tag, simple.unknown_tag) == (
        "de",
        "de",
        "de-zz",
        "qaa",
    )
    # The primary language en selects en first, so the test has no near tag.
    british = language_test(plan(("en", "en"), ("en_gb", "en-GB")))
    assert british is not None
    assert (british.second_tag, british.near_tag) == ("en-gb", None)
    # A tag of the second language that the first language has selects the first language.
    assert language_test(plan(("en", "de"), ("de", "de"))) is None
    private = language_test(plan(("qaa", "qaa"), ("de", "de")))
    assert private is not None
    assert private.unknown_tag == "qab"


def api_texts(files: dict[str, str]) -> set[str]:
    """Return the texts of the calls of `t` in the Python files, also by a constant."""
    texts: set[str] = set()
    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        tree = ast.parse(content)
        constants = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
            ):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    texts.add(arg.value)
                elif isinstance(arg, ast.Name) and arg.id in constants:
                    texts.add(constants[arg.id])
    return texts


def definition_messages(definition: AppDefinition) -> set[str]:
    rules = {
        str(rule.message)
        for entity in definition.entities.values()
        for rule in entity.rules.values()
        if getattr(rule, "message", None)
    }
    return rules | {w.message for w in definition.workflows.values() if w.message}


def test_the_docs_list_the_messages_of_the_api() -> None:
    texts = set(TITLES)
    fixtures = ROOT / "tests" / "fixtures"
    security = load_definition(fixtures / "account-security.yaml")
    files_path = fixtures / "files.yaml"
    # The webhooks of the inbound emails (ADR 0030) have a message of their own.
    inbound = fixtures / "inbound-email.yaml"
    languages = dedent(
        """\
        translations:
          default: en
          languages:
            en: { label: English }
            de: { label: Deutsch }
        """
    )
    files = load_definition_text(files_path.read_text() + languages, str(files_path))
    email = load_definition_text(inbound.read_text() + languages, str(inbound))
    definitions = (room_booking_in_two_languages(), security, files, email)
    for definition in (load_definition(EXAMPLE), *definitions):
        texts |= api_texts(files_of(definition)) - definition_messages(definition)
    docs = (ROOT / "docs" / "dsl.md").read_text(encoding="utf-8")
    section = docs[docs.index("### Messages of the FastAPI app") :]
    section = section[: re.search(r"\n##", section[1:]).end()]  # pyright: ignore[reportOptionalMemberAccess]
    listed = set(re.findall(r"`([^`]+)`", section.split("\n\n", 2)[2])) - {"type"}
    assert sorted(texts - listed) == []
    assert sorted(listed - texts) == []
