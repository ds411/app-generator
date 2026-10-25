"""Checks across the elements of an app definition: names, references, and field options.

The loader checks the structure of each element. The checks in this module
need more than one element, for example a relation and its target entity.
Each check is a function that yields diagnostics. `CHECKS` lists them, so
that later parts of the DSL can add their own checks.
"""

import datetime
import difflib
import json
import operator
import re
import uuid
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, cast

from appgen.dsl.access import ALL, RecordRule
from appgen.dsl.apis import PUBLIC_ENV_PREFIXES, RESERVED_ENV_NAMES, Api, ApiSecurity
from appgen.dsl.auth import (
    FORGOT_PASSWORD_PATH,
    PROVIDER_PATHS,
    RESET_PASSWORD_PATH,
    SECOND_FACTOR_PATH,
    SIGN_IN_PATH,
    SIGN_UP_PATH,
    VERIFY_EMAIL_PATH,
    Auth,
    Provider,
    SecondFactor,
    SignUp,
)
from appgen.dsl.currencies import CURRENCY_CODES
from appgen.dsl.diagnostics import DefinitionError, Diagnostic, Location
from appgen.dsl.expressions import (
    Binary,
    Call,
    Expression,
    ExpressionError,
    FieldRef,
    Negate,
    parse_expression,
)
from appgen.dsl.loader import load_definition
from appgen.dsl.model import AppDefinition, Element, Entity, Field, Relation
from appgen.dsl.openapi import SecurityScheme, query_value
from appgen.dsl.rules import EntityCompareRule, EntityUniqueRule
from appgen.dsl.seed import EntitySeed, SeedRecord, is_record_key, normal_value
from appgen.dsl.translations import LOCALE, VALUE
from appgen.dsl.ui.checks import (
    FORMAT_TYPES,
    check_ui_dashboards,
    check_ui_forms,
    check_ui_references,
    check_ui_states,
    check_ui_tokens,
    check_ui_views,
)
from appgen.dsl.ui.fields import FieldPathError, resolve_path

type Check = Callable[[AppDefinition], Iterator[Diagnostic]]

STRING_TYPES = frozenset({"string", "text", "email", "url"})
NUMBER_TYPES = frozenset({"integer", "decimal"})
SINGLE_KINDS = frozenset({"many_to_one", "one_to_one"})
OWNER_KINDS = frozenset({"many_to_one", "many_to_many"})
"""The kinds of the last relation of the owner of a record rule (ADR 0025)."""
CONDITION_TYPES = frozenset({"string", "text", "email", "url", "integer", "boolean", "enum"})
"""The field types that a condition of a record rule can use (ADR 0025)."""
INVERSE_KINDS = {
    "many_to_one": "one_to_many",
    "one_to_many": "many_to_one",
    "one_to_one": "one_to_one",
    "many_to_many": "many_to_many",
}
CUSTOM_ONLY_KEYS = ("params", "returns", "apis")


def validate_definition(definition: AppDefinition) -> list[Diagnostic]:
    """Run all checks on a loaded definition. Return all diagnostics, in source order."""
    diagnostics = [diagnostic for check in CHECKS for diagnostic in check(definition)]
    return sorted(diagnostics, key=lambda d: d.location)


def check_file(path: Path | str) -> tuple[AppDefinition | None, list[Diagnostic]]:
    """Load and validate a definition file.

    Return the definition (None if it does not load) and all diagnostics.
    """
    try:
        definition = load_definition(path)
    except DefinitionError as error:
        return None, error.diagnostics
    return definition, validate_definition(definition)


def check_names(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Names must be unique in their scope, also without regard to case."""
    yield from _unique_names(definition.entities.values(), "entity")
    yield from _unique_names(definition.operations.values(), "operation")
    yield from _unique_names(definition.pages.values(), "page")
    for entity in definition.entities.values():
        members = [*entity.fields.values(), *entity.relations.values()]
        yield from _unique_names(members, "field or relation")
        for member in members:
            if _name(member) == "id":
                yield _error(
                    "reserved-name",
                    "The name 'id' is reserved for the primary key of each entity.",
                    member,
                    hint="Use another name. Each entity has an implicit 'id' field.",
                )
        for name, relation in entity.relations.items():
            column = f"{name}_id"
            if relation.kind in SINGLE_KINDS and column in entity.fields:
                yield _error(
                    "duplicate-name",
                    f"The field '{column}' has the same name as the foreign key of "
                    f"the relation '{name}'.",
                    entity.fields[column],
                    hint="Rename the field or the relation.",
                )
    paths: dict[str, Element] = {}
    for page in definition.pages.values():
        first = paths.setdefault(page.path, page)
        if first is not page:
            yield _error(
                "duplicate-path",
                f"The path '{page.path}' is also the path of '{first.id}'.",
                page,
                at="path",
            )


def check_references(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Each reference to an entity, a field, or a relation must resolve."""
    entities = definition.entities
    for entity in entities.values():
        if entity.display_field is not None and entity.display_field not in entity.fields:
            yield _missing(entity, "display_field", "field", entity.display_field, entity.fields)
        for relation in entity.relations.values():
            if relation.target not in entities:
                yield _missing(relation, "target", "entity", relation.target, entities)
    for operation in definition.operations.values():
        if operation.entity not in entities:
            yield _missing(operation, "entity", "entity", operation.entity, entities)
        if operation.returns != "none" and operation.returns not in entities:
            yield _missing(operation, "returns", "entity", operation.returns, [*entities, "none"])
    for page in definition.pages.values():
        if page.entity is not None and page.entity not in entities:
            yield _missing(page, "entity", "entity", page.entity, entities)


def check_relations(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Relation options must fit the kind, and the inverse must be the other side."""
    for entity_name, entity in definition.entities.items():
        for name, relation in entity.relations.items():
            if relation.kind not in SINGLE_KINDS:
                for key in ("required", "on_delete"):
                    if key in relation.model_fields_set:
                        yield _error(
                            "invalid-option",
                            f"'{key}' is only for 'many_to_one' and 'one_to_one' relations.",
                            relation,
                            at=key,
                        )
            if relation.required and relation.on_delete == "set_null":
                yield _error(
                    "invalid-option",
                    "A required relation cannot use 'on_delete: set_null'.",
                    relation,
                    at="on_delete",
                    hint="Use 'cascade' or 'restrict', or remove 'required'.",
                )
            target = definition.entities.get(relation.target)
            if target is None:
                continue
            if relation.inverse is None:
                if relation.kind == "one_to_many":
                    yield _error(
                        "missing-inverse",
                        "A 'one_to_many' relation needs an 'inverse': the 'many_to_one' "
                        f"relation on '{relation.target}' that holds the foreign key.",
                        relation,
                        hint=f"Add a 'many_to_one' relation to '{entity_name}' on "
                        f"'{relation.target}', and name it in 'inverse'.",
                    )
                continue
            inverse = target.relations.get(relation.inverse)
            if inverse is None:
                yield _missing(relation, "inverse", "relation", relation.inverse, target.relations)
                continue
            if inverse.target not in definition.entities:
                # check_references reports the target of the inverse.
                continue
            expected_kind = INVERSE_KINDS[relation.kind]
            if inverse.target != entity_name or inverse.kind != expected_kind:
                yield _error(
                    "invalid-inverse",
                    f"The inverse '{relation.target}.{relation.inverse}' must be a "
                    f"'{expected_kind}' relation to '{entity_name}'.",
                    relation,
                    at="inverse",
                )
            elif inverse.inverse not in (None, name) and inverse.inverse in entity.relations:
                yield _error(
                    "invalid-inverse",
                    f"The inverse '{relation.target}.{relation.inverse}' names "
                    f"'{inverse.inverse}' as its inverse, not '{name}'.",
                    relation,
                    at="inverse",
                )


def check_operations(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Only custom operations have params and a return type."""
    for operation in definition.operations.values():
        if operation.kind == "custom":
            continue
        for key in CUSTOM_ONLY_KEYS:
            if key in operation.model_fields_set:
                yield _error(
                    "invalid-option",
                    f"'{key}' is only for 'custom' operations.",
                    operation,
                    at=key,
                )


def check_fields(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The options of each field must fit its type."""
    for entity in definition.entities.values():
        for field in entity.fields.values():
            yield from _check_field(field)
    for operation in definition.operations.values():
        for param in operation.params.values():
            yield from _check_field(param)
            for key in ("unique", "computed"):
                if getattr(param, key):
                    yield _error(
                        "invalid-option", f"'{key}' is only for entity fields.", param, at=key
                    )


def check_computed(definition: AppDefinition) -> Iterator[Diagnostic]:
    """A computed field is a number, and its expression refers to fields that suit it."""
    for entity_name, entity in definition.entities.items():
        for field in entity.computed_fields.values():
            assert field.computed is not None
            if field.type not in NUMBER_TYPES:
                yield _error(
                    "invalid-option",
                    f"A computed field must be an 'integer' or a 'decimal', not '{field.type}'.",
                    field,
                    at="computed",
                )
                continue
            for key in ("required", "unique", "default"):
                if key in field.model_fields_set:
                    yield _error(
                        "invalid-option",
                        f"'{key}' is not an option of a computed field.",
                        field,
                        at=key,
                    )
            try:
                expression = parse_expression(field.computed)
            except ExpressionError as error:
                yield _error(
                    "invalid-value",
                    f"The expression is not valid: {error}",
                    field,
                    at="computed",
                )
                continue
            yield from _check_expression(definition, entity_name, field, expression, False)


def _check_expression(
    definition: AppDefinition, entity: str, field: Field, expression: Expression, date: bool
) -> Iterator[Diagnostic]:
    match expression:
        case FieldRef(path):
            try:
                target = resolve_path(definition, entity, path)
            except FieldPathError as error:
                yield _error("unknown-reference", str(error), field, at="computed")
                return
            member = target.member
            types = {"date", "datetime"} if date else NUMBER_TYPES
            if not isinstance(member, Field) or member.type not in types:
                what = "a date or a date-time" if date else "an 'integer' or a 'decimal' field"
                yield _error(
                    "unsuitable-field",
                    f"The path '{path}' must give {what}.",
                    field,
                    at="computed",
                )
            elif member.computed is not None:
                yield _error(
                    "unsuitable-field",
                    f"The path '{path}' gives a computed field. Use the fields of its expression.",
                    field,
                    at="computed",
                )
        case Call(name, args):
            for arg in args:
                if not isinstance(arg, FieldRef):
                    yield _error(
                        "invalid-value",
                        f"The arguments of '{name}' must be field paths of dates or date-times.",
                        field,
                        at="computed",
                    )
                else:
                    yield from _check_expression(definition, entity, field, arg, True)
        case Binary(_, left, right):
            yield from _check_expression(definition, entity, field, left, False)
            yield from _check_expression(definition, entity, field, right, False)
        case Negate(operand):
            yield from _check_expression(definition, entity, field, operand, False)
        case _:
            pass


_COMPARE_GROUPS = (
    NUMBER_TYPES,
    frozenset({"date"}),
    frozenset({"datetime"}),
    frozenset({"string", "text", "email", "url", "enum"}),
)
"""The groups of field types that a compare rule can compare with each other."""


def check_rules(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The rules of an entity refer to its stored fields, and the fields suit the rule."""
    for entity in definition.entities.values():
        stored = entity.stored_fields
        singles = {n for n, r in entity.relations.items() if r.kind in SINGLE_KINDS}
        for rule in entity.rules.values():
            if isinstance(rule, EntityCompareRule):
                found = [
                    _rule_field(rule, key, getattr(rule, key), stored) for key in ("field", "other")
                ]
                for diagnostic in found:
                    if isinstance(diagnostic, Diagnostic):
                        yield diagnostic
                a, b = found
                if (
                    isinstance(a, Field)
                    and isinstance(b, Field)
                    and not any(a.type in g and b.type in g for g in _COMPARE_GROUPS)
                ):
                    yield _error(
                        "unsuitable-field",
                        f"A compare rule cannot compare a '{a.type}' with a '{b.type}'.",
                        rule,
                        at="other",
                    )
            elif isinstance(rule, EntityUniqueRule):
                yield from _rule_members(rule, "fields", rule.fields, stored, singles)
            else:
                ends = [
                    _rule_field(rule, key, getattr(rule, key), stored) for key in ("start", "end")
                ]
                for key, found in zip(("start", "end"), ends, strict=True):
                    if isinstance(found, Diagnostic):
                        yield found
                    elif found.type not in ("date", "datetime"):
                        yield _error(
                            "unsuitable-field",
                            f"The {key} of a 'no_overlap' rule must be a date or a date-time.",
                            rule,
                            at=key,
                        )
                a, b = ends
                if isinstance(a, Field) and isinstance(b, Field) and a.type != b.type:
                    yield _error(
                        "unsuitable-field",
                        "The start and the end of a 'no_overlap' rule must have the same type.",
                        rule,
                        at="end",
                    )
                yield from _rule_members(rule, "scope", rule.scope, stored, singles)


def _rule_field(rule: Element, key: str, name: str, stored: dict[str, Field]) -> Field | Diagnostic:
    found = stored.get(name)
    if found is None:
        return _missing(rule, key, "field", name, stored)
    return found


def _rule_members(
    rule: Element, key: str, names: list[str], stored: dict[str, Field], singles: set[str]
) -> Iterator[Diagnostic]:
    if len(set(names)) != len(names):
        yield _error("duplicate-name", f"The names in '{key}' must be unique.", rule, at=key)
    for name in names:
        if name not in stored and name not in singles:
            yield _missing(rule, key, "field or relation", name, [*stored, *singles])


def check_translations(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The default language exists and has no text, and each language has all keys."""
    translations = definition.translations
    if translations is None:
        return
    languages = translations.languages
    if translations.default not in languages:
        yield _missing(translations, "default", "language", translations.default, languages)
        return
    for code, language in languages.items():
        if not LOCALE.fullmatch(language.locale_tag(code)):
            yield _error(
                "translation-locale",
                f"The locale '{language.locale}' of '{code}' is not a language tag (BCP 47)."
                if language.locale
                else f"The code '{code}' is not a language tag (BCP 47), and the language has no "
                "locale.",
                language,
                at="locale" if language.locale else None,
                hint="Give a language tag, for example 'de' or 'pt-BR'."
                if language.locale
                else f"Add a locale, for example 'locale: {_locale_hint(code)}'.",
            )
    default = languages[translations.default]
    if default.text:
        yield _error(
            "invalid-value",
            "The default language takes its text from the definition.",
            default,
            at="text",
            hint="Remove 'text' from the default language.",
        )
    others = {code: language for code, language in languages.items() if language is not default}
    keys = {key for language in others.values() for key in language.text}
    for code, language in others.items():
        missing = [key for key in sorted(keys) if key not in language.text]
        if missing:
            names = ", ".join(f"'{key}'" for key in missing)
            yield _error(
                "missing-translation",
                f"The language '{code}' has no translation of {names}.",
                language,
                at="text",
                hint="Each language translates the same keys.",
            )
        for key, value in sorted(language.text.items()):
            names = sorted(set(VALUE.findall(key)))
            if names == sorted(set(VALUE.findall(value))):
                continue
            values = ", ".join(f"{{{name}}}" for name in names)
            yield _error(
                "translation-values",
                f"The translation of '{key}' in '{code}' must have the values {values}."
                if names
                else f"The translation of '{key}' in '{code}' must have no values in braces.",
                language,
                at="text",
                hint="Keep each value in braces of the text, and add no other value.",
            )


def _locale_hint(code: str) -> str:
    """Return a language tag for a code, for example `pt-BR` for `pt_br`."""
    first, *rest = code.split("_")
    tag = "-".join([first, *(part.upper() if len(part) == 2 else part.title() for part in rest)])
    return tag if LOCALE.fullmatch(tag) else "pt-BR"


def check_workflows(definition: AppDefinition) -> Iterator[Diagnostic]:
    """A workflow uses a stored enum field of its entity, and its states are values of the field."""
    seen: dict[tuple[str, str], str] = {}
    for workflow in definition.workflows.values():
        entity = definition.entities.get(workflow.entity)
        if entity is None:
            yield _missing(workflow, "entity", "entity", workflow.entity, definition.entities)
            continue
        found = _rule_field(workflow, "field", workflow.field, entity.stored_fields)
        if isinstance(found, Diagnostic):
            yield found
            continue
        if found.type != "enum" or not found.values:
            yield _error(
                "unsuitable-field",
                f"The field of a workflow must be an enum, not a '{found.type}'.",
                workflow,
                at="field",
            )
            continue
        first = seen.setdefault((workflow.entity, workflow.field), workflow.id)
        if first != workflow.id:
            yield _error(
                "duplicate-name",
                f"The field '{workflow.entity}.{workflow.field}' has two workflows.",
                workflow,
                at="field",
                hint=f"The other workflow is '{first}'.",
            )
        values = found.values
        if workflow.initial is not None and workflow.initial not in values:
            yield _missing(workflow, "initial", "value", workflow.initial, values)
        for transition in workflow.transitions.values():
            for value in transition.from_:
                if value not in values:
                    yield _missing(transition, "from", "value", value, values)
            if transition.to not in values:
                yield _missing(transition, "to", "value", transition.to, values)
            elif transition.to in transition.from_:
                yield _error(
                    "invalid-value",
                    f"A transition cannot change the field from '{transition.to}' to itself.",
                    transition,
                    at="to",
                )


def check_auth(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The user entity has a required, unique user name, and the public parts exist."""
    auth = definition.auth
    if auth is None:
        return
    entity = definition.entities.get(auth.user_entity)
    if entity is None:
        yield _missing(auth, "user_entity", "entity", auth.user_entity, definition.entities)
    else:
        found = _rule_field(auth, "username_field", auth.username_field, entity.stored_fields)
        if isinstance(found, Diagnostic):
            yield found
        elif found.type not in ("string", "email") or not found.required or not found.unique:
            yield _error(
                "unsuitable-field",
                "The user name must be a required, unique 'string' or 'email' field.",
                auth,
                at="username_field",
            )
    if entity is not None and auth.sign_up is not None:
        yield from _check_sign_up(definition, auth, auth.sign_up, entity)
    if entity is not None and auth.second_factor is not None:
        yield from _check_second_factor(definition, auth, auth.second_factor, entity)
    yield from _check_password_off(auth)
    # The settings of the issuers, and the variables of the API clients, also use names.
    variables = {f"{name.upper()}_ISSUER" for name in auth.providers}
    for api in definition.apis.values():
        variables.add(api.base_url_env)
        if api.security is not None:
            variables.update(env for _, env in api.security.variables)
    for provider in auth.providers.values():
        for key in ("client_id_env", "client_secret_env"):
            variable: str = getattr(provider, key)
            if variable in RESERVED_ENV_NAMES:
                yield _error(
                    "reserved-name",
                    f"The apps use the environment variable '{variable}' for their own settings.",
                    provider,
                    at=key,
                    hint="Use a name with the provider name, for example 'COMPANY_CLIENT_ID'.",
                )
            elif variable in variables:
                yield _error(
                    "duplicate-name",
                    f"The environment variable '{variable}' has two uses.",
                    provider,
                    at=key,
                    hint="Give each client ID and each client secret its own variable.",
                )
            variables.add(variable)
        if entity is not None:
            yield from _check_provider(definition, auth, provider, entity)
    for name in auth.public_pages:
        if name not in definition.pages:
            yield _missing(auth, "public_pages", "page", name, definition.pages)
    for name in auth.public_operations:
        if name not in definition.operations:
            yield _missing(auth, "public_operations", "operation", name, definition.operations)
    reserved = {SIGN_IN_PATH: "sign-in"}
    if auth.sign_up is not None:
        reserved[SIGN_UP_PATH] = "sign-up"
    if auth.password_reset is not None:
        reserved[FORGOT_PASSWORD_PATH] = "forgot password"
        reserved[RESET_PASSWORD_PATH] = "password reset"
    if auth.sign_up is not None and auth.sign_up.verify_email is not None:
        reserved[VERIFY_EMAIL_PATH] = "email verification"
    if auth.second_factor is not None:
        reserved[SECOND_FACTOR_PATH] = "second factor"
    for page in definition.pages.values():
        if page.path in reserved:
            yield _error(
                "duplicate-name",
                f"The path '{page.path}' is the {reserved[page.path]} page of the apps.",
                page,
                at="path",
                hint="Give the page another path.",
            )
        elif auth.providers and page.path.startswith(PROVIDER_PATHS):
            yield _error(
                "duplicate-name",
                f"The paths under '{PROVIDER_PATHS}' are the provider sign-in of the apps.",
                page,
                at="path",
                hint="Give the page another path.",
            )


def _check_sign_up(
    definition: AppDefinition, auth: Auth, sign_up: SignUp, entity: Entity
) -> Iterator[Diagnostic]:
    """The sign-up asks for each required field, and gives a new user a role that exists."""
    access = definition.access
    role_field = access.role_field if access is not None else None
    if len(set(sign_up.fields)) != len(sign_up.fields):
        yield _error(
            "duplicate-name", "The names in 'fields' must be unique.", sign_up, at="fields"
        )
    for name in sign_up.fields:
        found = entity.fields.get(name)
        if found is None:
            yield _missing(sign_up, "fields", "field", name, entity.stored_fields)
        elif found.computed is not None or name == role_field:
            yield _error(
                "unsuitable-field",
                f"The sign-up cannot ask for the field '{name}': "
                + ("the app computes it." if found.computed is not None else "it is the role."),
                sign_up,
                at="fields",
                hint="A new user gets the role 'default_role'." if name == role_field else None,
            )
        elif found.type == "json":
            yield _error(
                "unsuitable-field",
                f"The sign-up form has no widget for the 'json' field '{name}'.",
                sign_up,
                at="fields",
            )
    for name, field in entity.stored_fields.items():
        if (
            field.required
            and field.default is None
            and name not in sign_up.fields
            and name != role_field
        ):
            yield _error(
                "missing-key",
                f"The sign-up must ask for the required field '{name}' of '{auth.user_entity}'.",
                sign_up,
                at="fields",
                hint=f"Add '{name}' to 'fields'.",
            )
    for name, relation in entity.relations.items():
        if relation.required and relation.kind == "many_to_one":
            yield _error(
                "unsuitable-field",
                f"The sign-up cannot set the required relation '{name}' of '{auth.user_entity}'.",
                sign_up,
                hint="Make the relation optional, or turn off the sign-up.",
            )
    yield from _check_default_role(definition, sign_up, sign_up.default_role, entity, "sign-up")
    if sign_up.verify_email is not None and definition.address_field() is None:
        yield _error(
            "unsuitable-field",
            "The email verification needs a required field of the type 'email' "
            f"in '{auth.user_entity}' for the address.",
            sign_up.verify_email,
            hint="Make the user name an 'email' field, or add a required 'email' field.",
        )


def _check_second_factor(
    definition: AppDefinition, auth: Auth, second_factor: SecondFactor, entity: Entity
) -> Iterator[Diagnostic]:
    """The second factor has a method, and its required roles exist (ADR 0024).

    A new user of the sign-up starts a session at once, so the role of the
    sign-up cannot need the second factor without `verify_email`: then the
    user turns the factor on at the first sign-in.
    """
    if not second_factor.totp:
        yield _error(
            "missing-key",
            "The second factor needs a method.",
            second_factor,
            at="totp",
            hint="Set 'totp: true': the codes of an authenticator app.",
        )
    if not second_factor.required_roles:
        return
    access = definition.access
    if access is None:
        yield _error(
            "invalid-option",
            "'required_roles' needs the section 'access'.",
            second_factor,
            at="required_roles",
        )
        return
    if len(set(second_factor.required_roles)) != len(second_factor.required_roles):
        yield _error(
            "duplicate-name",
            "The names in 'required_roles' must be unique.",
            second_factor,
            at="required_roles",
        )
    for name in second_factor.required_roles:
        if name not in access.roles:
            yield _missing(second_factor, "required_roles", "role", name, access.roles)
    sign_up = auth.sign_up
    if sign_up is None or sign_up.verify_email is not None:
        return
    role = entity.fields.get(access.role_field)
    default = sign_up.default_role or (str(role.default) if role and role.default else None)
    if default in second_factor.required_roles:
        yield _error(
            "invalid-option",
            f"A new user of the sign-up gets the role '{default}', which must use the "
            "second factor, but the sign-up starts a session at once.",
            second_factor,
            at="required_roles",
            hint="Turn on 'sign_up.verify_email': then a new user turns on the second "
            "factor at the first sign-in.",
        )


def _check_default_role(
    definition: AppDefinition,
    element: Element,
    default_role: str | None,
    entity: Entity,
    what: str,
) -> Iterator[Diagnostic]:
    """A new user of a sign-up or of a provider gets a role that exists."""
    access = definition.access
    if access is None:
        if default_role is not None:
            yield _error(
                "invalid-option",
                "'default_role' needs the section 'access'.",
                element,
                at="default_role",
            )
    elif default_role is not None:
        if default_role not in access.roles:
            yield _missing(element, "default_role", "role", default_role, access.roles)
    else:
        role = entity.fields.get(access.role_field)
        if role is not None and role.default is None:
            yield _error(
                "missing-key",
                f"The {what} needs 'default_role': the role field has no default.",
                element,
                hint=f"Add for example 'default_role: {next(iter(access.roles))}'.",
            )


def _check_password_off(auth: Auth) -> Iterator[Diagnostic]:
    """Without the sign-in with a password, a provider is necessary, and no password parts."""
    if auth.password:
        return
    if not auth.providers:
        yield _error(
            "missing-key",
            "Without the sign-in with a password ('password: false'), the app needs a provider.",
            auth,
            at="password",
            hint="Add an OpenID Connect provider in 'providers'.",
        )
    parts = (
        ("sign_up", auth.sign_up),
        ("password_reset", auth.password_reset),
        ("second_factor", auth.second_factor),
    )
    for key, part in parts:
        if part is not None:
            yield _error(
                "invalid-option",
                f"'{key}' needs the sign-in with a password.",
                part,
                hint="Remove 'password: false', or remove '" + key + "'.",
            )


def _check_provider(
    definition: AppDefinition, auth: Auth, provider: Provider, entity: Entity
) -> Iterator[Diagnostic]:
    """A provider asks for `openid`, and with `create_users` gives each required field."""
    if "openid" not in provider.scopes:
        yield _error(
            "invalid-value",
            "The scopes of a provider must include 'openid'.",
            provider,
            at="scopes",
        )
    if not provider.create_users:
        for key in ("default_role", "claims"):
            if getattr(provider, key):
                yield _error(
                    "invalid-option",
                    f"'{key}' needs 'create_users: true'.",
                    provider,
                    at=key,
                )
        return
    role_field = definition.access.role_field if definition.access is not None else None
    for name in provider.claims:
        found = entity.fields.get(name)
        if found is None:
            yield _missing(provider, "claims", "field", name, entity.stored_fields)
        elif found.computed is not None or name in (role_field, auth.username_field):
            if found.computed is not None:
                reason = "the app computes it."
            elif name == role_field:
                reason = "it is the role."
            else:
                reason = "'username_claim' gives it."
            yield _error(
                "unsuitable-field",
                f"A claim cannot set the field '{name}': {reason}",
                provider,
                at="claims",
            )
    for name, field in entity.stored_fields.items():
        if (
            field.required
            and field.default is None
            and name not in provider.claims
            and name not in (role_field, auth.username_field)
        ):
            yield _error(
                "missing-key",
                f"A new user needs the required field '{name}' of '{auth.user_entity}'.",
                provider,
                at="claims",
                hint=f"Add a claim for '{name}' to 'claims', for example '{name}: {name}'.",
            )
    for name, relation in entity.relations.items():
        if relation.required and relation.kind == "many_to_one":
            yield _error(
                "unsuitable-field",
                f"A provider cannot set the required relation '{name}' of '{auth.user_entity}'.",
                provider,
                hint="Make the relation optional, or remove 'create_users'.",
            )
    yield from _check_default_role(definition, provider, provider.default_role, entity, "provider")


def check_access(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The roles need `auth`, the role field is an enum of the user entity, and the names exist."""
    access = definition.access
    if access is None:
        return
    auth = definition.auth
    if auth is None:
        yield _error(
            "missing-key",
            "The section 'access' needs the section 'auth'.",
            access,
            hint="Add 'auth' with the user entity.",
        )
        return
    entity = definition.entities.get(auth.user_entity)
    if entity is None:
        return
    found = _rule_field(access, "role_field", access.role_field, entity.stored_fields)
    if isinstance(found, Diagnostic):
        yield found
    elif found.type != "enum" or not found.values:
        yield _error(
            "unsuitable-field",
            f"The role field must be an enum field of '{auth.user_entity}'.",
            access,
            at="role_field",
        )
    else:
        for name, role in access.roles.items():
            if name not in found.values:
                yield _missing(role, "", "role value", name, found.values)
    for role in access.roles.values():
        for key, names, known, what in (
            ("operations", role.operations, definition.operations, "operation"),
            ("pages", role.pages, definition.pages, "page"),
        ):
            for name in names:
                if name != ALL and name not in known:
                    yield _missing(role, key, what, name, known)
        for name, rule in role.records.items():
            yield from _check_record_rule(definition, auth.user_entity, name, rule)
    owners: dict[str, str] = {}
    for role in access.roles.values():
        for name, rule in role.records.items():
            if rule.owner is None:
                continue
            first = owners.setdefault(name, rule.owner)
            if first != rule.owner:
                yield _error(
                    "invalid-value",
                    f"All record rules of '{name}' with an owner must use the same owner: "
                    f"'{first}'.",
                    rule,
                    at="owner",
                )


def _check_record_rule(
    definition: AppDefinition, users: str, name: str, rule: RecordRule
) -> Iterator[Diagnostic]:
    """The entity exists, the owner path ends at the user entity, and the conditions suit."""
    entity = definition.entities.get(name)
    if entity is None:
        yield _missing(rule, "", "entity", name, definition.entities)
        return
    if rule.owner is None and not rule.where:
        yield _error(
            "missing-key",
            "A record rule needs 'owner', 'where', or both.",
            rule,
            hint="Add for example 'owner: <relation to the user>' or 'where: { status: open }'.",
        )
    if len(set(rule.operations)) != len(rule.operations):
        yield _error(
            "duplicate-name", "The names in 'operations' must be unique.", rule, at="operations"
        )
    if rule.owner is not None:
        yield from _check_owner_path(definition, users, name, rule, rule.owner)
    for field_name, values in rule.conditions().items():
        yield from _check_condition(entity, rule, field_name, values)


def _check_owner_path(
    definition: AppDefinition, users: str, name: str, rule: RecordRule, path: str
) -> Iterator[Diagnostic]:
    """Each step is a many-to-one or a many-to-many relation. The last step goes to the users."""
    current = name
    relation = None
    for step in path.split("."):
        entity = definition.entities.get(current)
        if entity is None:
            # check_references reports the target of the relation of the step before.
            return
        relation = entity.relations.get(step)
        if relation is None:
            if step in entity.fields:
                yield _error(
                    "unsuitable-field",
                    f"The step '{step}' of the owner is a field of '{current}', not a relation.",
                    rule,
                    at="owner",
                )
            else:
                matches = difflib.get_close_matches(step, list(entity.relations), n=1)
                yield _error(
                    "unknown-reference",
                    f"The relation '{step}' of '{current}' does not exist.",
                    rule,
                    at="owner",
                    hint=f"Did you mean '{matches[0]}'?" if matches else None,
                )
            return
        if relation.kind not in OWNER_KINDS:
            yield _error(
                "unsuitable-field",
                f"Each step of the owner must be a many-to-one or a many-to-many relation, "
                f"and '{current}.{step}' is a '{relation.kind}' relation.",
                rule,
                at="owner",
                hint="A record gets its owner from the records that it refers to.",
            )
            return
        current = relation.target
    if relation is not None and relation.target != users:
        yield _error(
            "unsuitable-field",
            f"The owner must end with a relation to the user entity '{users}'.",
            rule,
            at="owner",
        )


def _check_condition(
    entity: Entity, rule: RecordRule, name: str, values: list[str | int | bool]
) -> Iterator[Diagnostic]:
    """The field of a condition is a stored field of a suitable type, and the values suit it."""
    field = entity.fields.get(name)
    if field is None:
        yield _missing(rule, "where", "field", name, entity.stored_fields)
        return
    if field.computed is not None:
        yield _error(
            "unsuitable-field",
            f"A condition cannot use the computed field '{name}': the records do not store it.",
            rule,
            at="where",
        )
        return
    if field.type not in CONDITION_TYPES:
        names = ", ".join(f"'{t}'" for t in sorted(CONDITION_TYPES))
        yield _error(
            "unsuitable-field",
            f"A condition cannot use the '{field.type}' field '{name}'. It is for {names}.",
            rule,
            at="where",
        )
        return
    for item in values:
        if not _value_fits(field, item):
            yield _error(
                "invalid-value",
                f"The field '{name}' does not allow the value {item!r}.",
                rule,
                at="where",
                hint=f"Use one of {field.values}." if field.type == "enum" else None,
            )
    if len({repr(v) for v in values}) != len(values):
        yield _error(
            "duplicate-name",
            f"The values of the condition '{name}' must be unique.",
            rule,
            at="where",
        )


def check_apis(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Each document is valid, and has the operations and the security scheme of its API."""
    envs: dict[str, str] = {}
    for api in definition.apis.values():
        names = [("base_url_env", api.base_url_env)]
        if api.security is not None:
            names += [
                ("security" if key == "env" else f"security.{key}", env)
                for key, env in api.security.variables
            ]
        for name, env in names:
            key = name.partition(".")[0]
            if env in RESERVED_ENV_NAMES:
                yield _error(
                    "reserved-name",
                    f"The apps use the environment variable '{env}' for their own settings.",
                    api,
                    at=key,
                    hint="Use a name with the name of the API, for example 'HOLIDAYS_API_URL'.",
                )
                continue
            secret = name in ("security", "security.client_secret_env")
            if secret and env.startswith(PUBLIC_ENV_PREFIXES):
                yield _error(
                    "reserved-name",
                    f"The front-end builds put the variable '{env}' into the code for the "
                    "browser, so it cannot keep a secret.",
                    api,
                    at=key,
                    hint="Use a name without the prefix NEXT_PUBLIC_ or VITE_.",
                )
                continue
            first = envs.setdefault(env, f"{api.id}.{name}")
            if first != f"{api.id}.{name}":
                yield _error(
                    "duplicate-name",
                    f"The environment variable '{env}' is also the variable of '{first}'.",
                    api,
                    at=key,
                )
        document = api.openapi
        if document is None:
            yield _error(
                "invalid-document",
                f"The OpenAPI document '{api.document}' is not valid: {api.document_error}",
                api,
                at="document",
            )
            continue
        known = document.operation_ids
        for operation_id, operation in api.operations.items():
            if operation_id not in known:
                matches = difflib.get_close_matches(operation_id, list(known), n=1)
                yield _error(
                    "unknown-reference",
                    f"The document '{api.document}' has no operation '{operation_id}'.",
                    operation,
                    hint=f"Did you mean '{matches[0]}'?" if matches else None,
                )
        for operation_id, problem in api.spec.problems:
            yield _error(
                "unsuitable-operation",
                f"The clients cannot call the operation '{operation_id}': {problem}",
                api.operations[operation_id],
            )
        if api.expose:
            yield from _check_exposed(api)
        security = api.security
        if security is None:
            continue
        scheme = document.security_schemes.get(security.scheme)
        if scheme is None:
            matches = difflib.get_close_matches(
                security.scheme, list(document.security_schemes), n=1
            )
            yield _error(
                "unknown-reference",
                f"The document '{api.document}' declares no security scheme '{security.scheme}'.",
                api,
                at="security",
                hint=f"Did you mean '{matches[0]}'?" if matches else None,
            )
        elif not scheme.supported:
            flows = (
                f" Its flows are {', '.join(repr(f) for f in scheme.flows)}."
                if scheme.type == "oauth2" and scheme.flows
                else ""
            )
            yield _error(
                "unsuitable-security",
                f"The security scheme '{security.scheme}' is not an API key in a header or a "
                "query parameter, a bearer token, or OAuth 2.0 with the client credentials flow."
                + flows,
                api,
                at="security",
                hint="The clients support only these schemes. Call the API from hand-written "
                "code to use another scheme.",
            )
        else:
            yield from _check_security_keys(api, security, scheme)
    for operation in definition.operations.values():
        if len(set(operation.apis)) != len(operation.apis):
            yield _error(
                "duplicate-name", "The names in 'apis' must be unique.", operation, at="apis"
            )
        for name in operation.apis:
            if name not in definition.apis:
                yield _missing(operation, "apis", "API", name, definition.apis)


def check_seed(definition: AppDefinition) -> Iterator[Diagnostic]:
    """The seed records give valid values, refer to records that exist, and keep the rules."""
    keys = {name: set(seed.records) for name, seed in definition.seed.items()}
    for name, seed in definition.seed.items():
        entity = definition.entities.get(name)
        if entity is None:
            yield _missing(seed, "", "entity", name, definition.entities)
            continue
        for record in seed.records.values():
            yield from _check_record(name, entity, record, keys)
        yield from _check_seed_rules(entity, seed)
    yield from _check_seed_one_to_one(definition)
    yield from _check_seed_targets(definition)


def _check_record(
    entity_name: str, entity: Entity, record: SeedRecord, keys: dict[str, set[str]]
) -> Iterator[Diagnostic]:
    values = record.values
    for name, value in values.items():
        field, relation = entity.fields.get(name), entity.relations.get(name)
        if field is not None:
            yield from _check_seed_value(record, name, field, value)
        elif relation is not None:
            yield from _check_seed_link(record, name, relation, value, keys)
        else:
            members = [*entity.stored_fields, *entity.relations]
            yield _error(
                "unknown-key",
                f"The entity '{entity_name}' has no field or relation '{name}'.",
                record,
                at=name,
                hint="The key of a seed record gives its ID."
                if name == "id"
                else _did_you_mean(name, members),
            )
    for name, field in entity.stored_fields.items():
        if field.required and field.default is None and values.get(name) is None:
            yield _error(
                "missing-key",
                f"The record has no value of the required field '{name}'.",
                record,
                at=name,
                hint=f"Add '{name}' to the record.",
            )
    for name, relation in entity.relations.items():
        if relation.kind == "many_to_one" and relation.required and values.get(name) is None:
            yield _error(
                "missing-key",
                f"The record has no value of the required relation '{name}'.",
                record,
                at=name,
                hint=f"Add '{name}' with the key of a seed record of '{relation.target}'.",
            )


def _check_seed_value(
    record: SeedRecord, name: str, field: Field, value: object
) -> Iterator[Diagnostic]:
    if field.computed is not None:
        yield _error(
            "unsuitable-field",
            f"The field '{name}' is computed: the apps compute its value.",
            record,
            at=name,
            hint="Remove the value.",
        )
        return
    try:
        normal = normal_value(field, value)
    except ValueError as error:
        quote = field.type in (*STRING_TYPES, "enum", "uuid") and not isinstance(value, str)
        yield _error(
            "invalid-value",
            f"The value {_show(value)} of '{name}' is not valid: {error}.",
            record,
            at=name,
            hint=f'Put the value in quotes: "{_show(value, quotes=False)}".' if quote else None,
        )
        return
    problem = _option_problem(field, normal)
    if problem is not None:
        yield _error(
            "invalid-value",
            f"The value {_show(normal)} of '{name}' is not valid: {problem}.",
            record,
            at=name,
        )


def _option_problem(field: Field, value: Any) -> str | None:
    """Return why a value in its normal form breaks an option of its field, or None."""
    if value is None:
        return None
    if isinstance(value, str) and field.type in STRING_TYPES:
        if field.min_length is not None and len(value) < field.min_length:
            return f"the text must have {field.min_length} or more characters"
        if field.max_length is not None and len(value) > field.max_length:
            return f"the text must have {field.max_length} or fewer characters"
        if field.pattern is not None and field.type == "string":
            try:
                if re.search(field.pattern, value) is None:
                    return f"the text must match the pattern {field.pattern}"
            except re.error:
                return None  # check_fields reports the pattern.
    if isinstance(value, int | float) and field.type in NUMBER_TYPES:
        if field.min is not None and value < field.min:
            return f"the value must be {_number(field.min)} or more"
        if field.max is not None and value > field.max:
            return f"the value must be {_number(field.max)} or less"
        if field.precision is not None:
            digits = field.precision - (field.scale or 0)
            if abs(value) >= 10**digits:
                return f"the value must have {digits} or fewer digits before the decimal point"
    return None


def _check_seed_link(
    record: SeedRecord, name: str, relation: Relation, value: object, keys: dict[str, set[str]]
) -> Iterator[Diagnostic]:
    if relation.kind == "one_to_many":
        yield _error(
            "unsuitable-field",
            f"The relation '{name}' is a 'one_to_many' relation, so the records of "
            f"'{relation.target}' hold it.",
            record,
            at=name,
            hint=f"Give the key of this record in '{relation.inverse}' of the records of "
            f"'{relation.target}'."
            if relation.inverse
            else None,
        )
        return
    if value is None:
        return
    many = relation.kind == "many_to_many"
    if many and not isinstance(value, list):
        yield _error(
            "invalid-value",
            f"The value of '{name}' must be a list of keys of seed records of '{relation.target}'.",
            record,
            at=name,
        )
        return
    items: list[object] = cast(list[object], value) if many else [value]
    if not all(is_record_key(item) for item in items):
        what = "a list of keys" if many else "the key"
        yield _error(
            "invalid-value",
            f"The value of '{name}' must be {what} of seed records of '{relation.target}'.",
            record,
            at=name,
        )
        return
    targets = keys.get(relation.target, set())
    seen: set[str] = set()
    for key in [str(item) for item in items]:
        if key in seen:
            yield _error(
                "duplicate-value",
                f"The key '{key}' occurs more than one time in '{name}'.",
                record,
                at=name,
            )
        seen.add(key)
        if key not in targets:
            matches = difflib.get_close_matches(key, sorted(targets), n=1)
            yield _error(
                "unknown-reference",
                f"The entity '{relation.target}' has no seed record '{key}'.",
                record,
                at=name,
                hint=f"Did you mean '{matches[0]}'?"
                if matches
                else f"Add the record to 'seed.{relation.target}.records'.",
            )


def _seed_values(entity: Entity, record: SeedRecord) -> dict[str, Any]:
    """Return the values of a record for the rules: valid values in their normal form, or None.

    A field that the record does not give has its default. A single
    relation has the key of its target.
    """
    values = record.values
    result: dict[str, Any] = {}
    for name, field in entity.stored_fields.items():
        value = values.get(name, field.default)
        try:
            result[name] = normal_value(field, value)
        except ValueError:
            result[name] = None
    for name, relation in entity.relations.items():
        value = values.get(name)
        if relation.kind in SINGLE_KINDS and is_record_key(value):
            result[name] = str(value)
    return result


def _check_seed_rules(entity: Entity, seed: EntitySeed) -> Iterator[Diagnostic]:
    """The records have unique values in the unique fields, and keep the rules of the entity."""
    records = list(seed.records.values())
    values = {record.key: _seed_values(entity, record) for record in records}
    for name, field in entity.stored_fields.items():
        if field.unique:
            yield from _check_seed_unique(records, values, [name], f"the field '{name}'", name)
    for rule_name, rule in entity.rules.items():
        if isinstance(rule, EntityUniqueRule):
            names = ", ".join(f"'{n}'" for n in rule.fields)
            yield from _check_seed_unique(
                records, values, rule.fields, f"{names} (rule '{rule_name}')", None
            )
        elif isinstance(rule, EntityCompareRule):
            for record in records:
                a = _comparable(entity, rule.field, values[record.key].get(rule.field))
                b = _comparable(entity, rule.other, values[record.key].get(rule.other))
                if a is not None and b is not None and not _SEED_OPS[rule.op](a, b):
                    yield _error(
                        "invalid-record",
                        f"The record does not keep the rule '{rule_name}': {rule.message}",
                        record,
                        at=rule.field,
                    )
        else:
            ranges: list[tuple[SeedRecord, Any, Any, list[Any]]] = []
            for record in records:
                record_values = values[record.key]
                start = _comparable(entity, rule.start, record_values.get(rule.start))
                end = _comparable(entity, rule.end, record_values.get(rule.end))
                if start is None or end is None:
                    continue
                scope = [record_values.get(name) for name in rule.scope]
                for other, other_start, other_end, other_scope in ranges:
                    if scope == other_scope and start < other_end and other_start < end:
                        yield _error(
                            "invalid-record",
                            f"The record does not keep the rule '{rule_name}': {rule.message}",
                            record,
                            at=rule.start,
                            hint=f"The time range of the record '{other.key}' overlaps.",
                        )
                        break
                ranges.append((record, start, end, scope))


def _check_seed_unique(
    records: list[SeedRecord],
    values: dict[str, dict[str, Any]],
    names: list[str],
    what: str,
    at: str | None,
) -> Iterator[Diagnostic]:
    seen: dict[str, SeedRecord] = {}
    for record in records:
        found = [values[record.key].get(name) for name in names]
        if any(value is None for value in found):
            continue
        first = seen.setdefault(json.dumps(found, sort_keys=True), record)
        if first is not record:
            yield _error(
                "duplicate-value",
                f"The record has the same value of {what} as the record '{first.key}'.",
                record,
                at=at or names[0],
                hint="Give each record its own value.",
            )


def _comparable(entity: Entity, name: str, value: Any) -> Any:
    """Return a value in a form that the compare operators can compare."""
    field = entity.fields.get(name)
    if value is None or field is None:
        return value
    if field.type == "date":
        return datetime.date.fromisoformat(value)
    if field.type == "datetime":
        return datetime.datetime.fromisoformat(value)
    return value


_SEED_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}


def _check_seed_one_to_one(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Each record has one partner or none in a `one_to_one` relation, from both sides."""
    for entity_name, seed in definition.seed.items():
        entity = definition.entities.get(entity_name)
        if entity is None:
            continue
        for name, relation in entity.relations.items():
            if relation.kind != "one_to_one":
                continue
            target = definition.seed.get(relation.target)
            inverse = definition.entities.get(relation.target)
            inverse_relation = (
                inverse.relations.get(relation.inverse)
                if inverse is not None and relation.inverse is not None
                else None
            )
            if inverse_relation is not None and inverse_relation.kind != "one_to_one":
                inverse_relation = None
            partners: dict[str, set[str]] = {key: set() for key in seed.records}
            owners: dict[str, str] = {}
            for record in seed.records.values():
                value = record.values.get(name)
                if not is_record_key(value):
                    continue
                partners[record.key].add(str(value))
                first = owners.setdefault(str(value), record.key)
                if first != record.key and inverse_relation is None:
                    yield _error(
                        "duplicate-value",
                        f"The record '{first}' also refers to '{value}' in the one-to-one "
                        f"relation '{name}'.",
                        record,
                        at=name,
                        hint="Give each record its own partner.",
                    )
            if inverse_relation is not None and target is not None and relation.inverse:
                for other in target.records.values():
                    value = other.values.get(relation.inverse)
                    if is_record_key(value) and str(value) in partners:
                        partners[str(value)].add(other.key)
            for record in seed.records.values():
                found = sorted(partners[record.key])
                if len(found) > 1:
                    names = " and ".join(f"'{key}'" for key in found)
                    yield _error(
                        "duplicate-value",
                        f"The record has two partners in the one-to-one relation '{name}': "
                        f"{names}.",
                        record,
                        at=name,
                        hint="Give the relation on one side only, or give each record one partner.",
                    )
                elif not found and relation.required:
                    yield _error(
                        "missing-key",
                        f"The record has no value of the required relation '{name}'.",
                        record,
                        at=name,
                        hint=f"Add '{name}' with the key of a seed record of '{relation.target}'.",
                    )


def _check_seed_targets(definition: AppDefinition) -> Iterator[Diagnostic]:
    """An entity whose seed has no records gives no target to a required relation."""
    for target_name, target in definition.seed.items():
        if target.records or target.mock:
            continue
        for entity_name, entity in definition.entities.items():
            seed = definition.seed.get(entity_name)
            if seed is not None and not seed.mock:
                continue
            for name, relation in entity.relations.items():
                if relation.target == target_name and relation.required:
                    yield _error(
                        "missing-key",
                        f"The generated records of '{entity_name}' need a record of "
                        f"'{target_name}' for the required relation '{name}'.",
                        target,
                        hint=f"Add a record to 'seed.{target_name}.records', or set "
                        f"'seed.{target_name}.mock'.",
                    )


def _check_security_keys(
    api: Api, security: ApiSecurity, scheme: SecurityScheme
) -> Iterator[Diagnostic]:
    """The security has the keys of its scheme: `env`, or the keys of OAuth 2.0."""
    oauth = scheme.type == "oauth2"
    needed = ("client_id_env", "client_secret_env") if oauth else ("env",)
    kind = "OAuth 2.0" if oauth else "an API key or a bearer token"
    for key in needed:
        if getattr(security, key) is None:
            yield _error(
                "missing-key",
                f"The security of the scheme '{scheme.name}' needs the key '{key}'.",
                api,
                at="security",
            )
    other = ("env",) if oauth else ("client_id_env", "client_secret_env", "scopes")
    for key in other:
        if getattr(security, key):
            yield _error(
                "invalid-option",
                f"The key '{key}' does not suit the scheme '{scheme.name}' ({kind}).",
                api,
                at="security",
                hint=f"Use {', '.join(repr(k) for k in needed)}.",
            )
    if oauth:
        for scope in security.scopes:
            if scope not in scheme.scopes:
                yield _error(
                    "unknown-reference",
                    f"The client credentials flow of the scheme '{scheme.name}' has no scope "
                    f"'{scope}'.",
                    api,
                    at="security",
                    hint=_did_you_mean(scope, scheme.scopes),
                )


def _check_exposed(api: Api) -> Iterator[Diagnostic]:
    """The endpoint of an exposed operation takes each parameter as a query parameter, and a
    JSON body, and gives a JSON answer."""
    spec = api.spec
    for operation in spec.operations:
        problems: list[str] = []
        names: set[str] = set()
        for parameter in operation.parameters:
            if parameter.name in names:
                problems.append(
                    f"two parameters have the name '{parameter.name}'. Its endpoint takes each "
                    "parameter as a query parameter."
                )
            elif not query_value(parameter.schema, spec):
                problems.append(
                    f"a query parameter cannot hold the parameter '{parameter.name}'. Its "
                    "endpoint takes each parameter as a query parameter."
                )
            names.add(parameter.name)
        if operation.body is not None and operation.body_kind != "json":
            problems.append("its body is a form. Its endpoint takes a JSON body.")
        if operation.result is not None and operation.answer != "json":
            problems.append(
                f"its answer is {operation.answer_media}, not JSON. Its endpoint gives JSON."
            )
        for problem in problems:
            yield _error(
                "unsuitable-operation",
                f"The FastAPI app cannot expose the operation '{operation.id}': {problem}",
                api.operations[operation.id],
                hint="Remove 'expose', or call the operation in a custom operation.",
            )


CHECKS: list[Check] = [
    check_names,
    check_references,
    check_relations,
    check_operations,
    check_fields,
    check_computed,
    check_rules,
    check_translations,
    check_workflows,
    check_auth,
    check_access,
    check_apis,
    check_seed,
    check_ui_tokens,
    check_ui_views,
    check_ui_forms,
    check_ui_dashboards,
    check_ui_states,
    check_ui_references,
]
"""The checks that `validate_definition` runs, in order."""


def _check_field(field: Field) -> Iterator[Diagnostic]:
    allowed = {
        "min_length": STRING_TYPES,
        "max_length": STRING_TYPES,
        "pattern": {"string"},
        "min": NUMBER_TYPES,
        "max": NUMBER_TYPES,
        "precision": {"decimal"},
        "scale": {"decimal"},
        "values": {"enum"},
        "currency": NUMBER_TYPES,
    }
    for key, types in allowed.items():
        if key in field.model_fields_set and field.type not in types:
            names = ", ".join(f"'{name}'" for name in sorted(types))
            yield _error(
                "invalid-option",
                f"'{key}' is not an option of the type '{field.type}'. It is for {names}.",
                field,
                at=key,
            )
    formats = FORMAT_TYPES[field.format] if field.format is not None else None
    if formats is not None and field.type not in formats:
        names = ", ".join(f"'{name}'" for name in sorted(formats))
        yield _error(
            "invalid-option",
            f"The format '{field.format}' does not suit the type '{field.type}'. "
            f"It is for {names}.",
            field,
            at="format",
        )
    if field.currency is not None and field.currency not in CURRENCY_CODES:
        yield _error(
            "invalid-value",
            f"'{field.currency}' is not an ISO 4217 currency code.",
            field,
            at="currency",
            hint="Use the code of an active currency, for example 'EUR' or 'USD'.",
        )
    if field.type == "enum":
        if not field.values:
            yield _error(
                "missing-key",
                "An 'enum' field needs 'values': a list of one or more names.",
                field,
                hint="Add for example 'values: [open, done]'.",
            )
        elif len(set(field.values)) != len(field.values):
            yield _error("duplicate-name", "The enum values must be unique.", field, at="values")
    for low, high in (("min_length", "max_length"), ("min", "max"), ("scale", "precision")):
        low_value, high_value = getattr(field, low), getattr(field, high)
        if low_value is not None and high_value is not None and low_value > high_value:
            yield _error(
                "invalid-option", f"'{low}' must not be greater than '{high}'.", field, at=low
            )
    if field.pattern is not None and field.type == "string":
        try:
            re.compile(field.pattern)
        except re.error as error:
            yield _error(
                "invalid-value",
                f"The pattern is not a valid regular expression: {error}.",
                field,
                at="pattern",
            )
    if field.default is not None and not _default_fits(field):
        yield _error(
            "invalid-value",
            f"The default {field.default!r} is not a valid '{field.type}' value.",
            field,
            at="default",
            hint=f"Use one of {field.values}." if field.type == "enum" else None,
        )


def _value_fits(field: Field, value: object) -> bool:
    """Return True if a value of a condition suits the type and the limits of a field."""
    if not _fits(field, value):
        return False
    if isinstance(value, str):
        low, high = field.min_length, field.max_length
        return (low is None or len(value) >= low) and (high is None or len(value) <= high)
    if isinstance(value, int) and not isinstance(value, bool):
        low, high = field.min, field.max
        return (low is None or value >= low) and (high is None or value <= high)
    return True


def _default_fits(field: Field) -> bool:
    return _fits(field, field.default)


def _fits(field: Field, value: object) -> bool:
    """Return True if a value suits the type of a field."""
    match field.type:
        case "string" | "text" | "email" | "url":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "decimal":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case "enum":
            return isinstance(value, str) and value in (field.values or [])
        case "date":
            return isinstance(value, str) and _parses(datetime.date.fromisoformat, value)
        case "datetime":
            return isinstance(value, str) and _parses(datetime.datetime.fromisoformat, value)
        case "uuid":
            return isinstance(value, str) and _parses(uuid.UUID, value)
        case "json":
            return True


def _parses(parse: Callable[[str], object], value: str) -> bool:
    try:
        parse(value)
    except ValueError:
        return False
    return True


def _unique_names(elements: Iterable[Element], what: str) -> Iterator[Diagnostic]:
    seen: dict[str, Element] = {}
    for element in elements:
        first = seen.setdefault(_name(element).lower(), element)
        if first is not element:
            yield _error(
                "duplicate-name",
                f"The {what} name '{_name(element)}' differs only in case from '{_name(first)}'.",
                element,
                hint=f"The other {what} is at {first.location}.",
            )


def _name(element: Element) -> str:
    return element.id.rpartition(".")[2]


def _missing(
    element: Element, key: str, what: str, name: str, choices: Iterable[str]
) -> Diagnostic:
    matches = difflib.get_close_matches(name, list(choices), n=1)
    return _error(
        "unknown-reference",
        f"The {what} '{name}' does not exist.",
        element,
        at=key,
        hint=f"Did you mean '{matches[0]}'?" if matches else None,
    )


def _error(
    code: str, message: str, element: Element, *, at: str | None = None, hint: str | None = None
) -> Diagnostic:
    location = element.location_of(at) if at else element.location
    return Diagnostic(
        code=code,
        message=message,
        location=location or Location("<unknown>", 1, 1),
        element_id=element.id or None,
        hint=hint,
    )


def _did_you_mean(name: str, choices: Iterable[str]) -> str | None:
    matches = difflib.get_close_matches(name, list(choices), n=1)
    return f"Did you mean '{matches[0]}'?" if matches else None


def _number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _show(value: object, *, quotes: bool = True) -> str:
    """Return a value for a message. A date that YAML read without quotes is ISO 8601 text."""
    if isinstance(value, datetime.date):
        value = value.isoformat()
    if not quotes:
        return str(value).lower() if isinstance(value, bool) else str(value)
    return repr(value)
