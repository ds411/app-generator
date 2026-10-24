"""Checks across the elements of an app definition: names, references, and field options.

The loader checks the structure of each element. The checks in this module
need more than one element, for example a relation and its target entity.
Each check is a function that yields diagnostics. `CHECKS` lists them, so
that later parts of the DSL can add their own checks.
"""

import datetime
import difflib
import re
import uuid
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from appgen.dsl.access import ALL, RecordRule
from appgen.dsl.apis import RESERVED_ENV_NAMES
from appgen.dsl.auth import (
    FORGOT_PASSWORD_PATH,
    RESET_PASSWORD_PATH,
    SIGN_IN_PATH,
    SIGN_UP_PATH,
    Auth,
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
from appgen.dsl.model import AppDefinition, Element, Entity, Field
from appgen.dsl.rules import EntityCompareRule, EntityUniqueRule
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
    for page in definition.pages.values():
        if page.path in reserved:
            yield _error(
                "duplicate-name",
                f"The path '{page.path}' is the {reserved[page.path]} page of the apps.",
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
    if access is None:
        if sign_up.default_role is not None:
            yield _error(
                "invalid-option",
                "'default_role' needs the section 'access'.",
                sign_up,
                at="default_role",
            )
    elif sign_up.default_role is not None:
        if sign_up.default_role not in access.roles:
            yield _missing(sign_up, "default_role", "role", sign_up.default_role, access.roles)
    else:
        role = entity.fields.get(access.role_field)
        if role is not None and role.default is None:
            yield _error(
                "missing-key",
                "The sign-up needs 'default_role': the role field has no default.",
                sign_up,
                hint=f"Add for example 'default_role: {next(iter(access.roles))}'.",
            )


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
            first = owners.setdefault(name, rule.owner)
            if first != rule.owner:
                yield _error(
                    "invalid-value",
                    f"All owner rules of '{name}' must use the same relation: '{first}'.",
                    rule,
                    at="owner",
                )


def _check_record_rule(
    definition: AppDefinition, users: str, name: str, rule: RecordRule
) -> Iterator[Diagnostic]:
    """The entity exists, and its owner is a many-to-one relation to the user entity."""
    entity = definition.entities.get(name)
    if entity is None:
        yield _missing(rule, "", "entity", name, definition.entities)
        return
    if len(set(rule.operations)) != len(rule.operations):
        yield _error(
            "duplicate-name", "The names in 'operations' must be unique.", rule, at="operations"
        )
    relation = entity.relations.get(rule.owner)
    if relation is None:
        yield _missing(rule, "owner", "relation", rule.owner, entity.relations)
    elif relation.kind != "many_to_one" or relation.target != users:
        yield _error(
            "unsuitable-field",
            f"The owner must be a many-to-one relation of '{name}' to the user entity '{users}'.",
            rule,
            at="owner",
        )


def check_apis(definition: AppDefinition) -> Iterator[Diagnostic]:
    """Each document is valid, and has the operations and the security scheme of its API."""
    envs: dict[str, str] = {}
    for api in definition.apis.values():
        names = [("base_url_env", api.base_url_env)]
        if api.security is not None:
            names.append(("security", api.security.env))
        for key, env in names:
            if env in RESERVED_ENV_NAMES:
                yield _error(
                    "reserved-name",
                    f"The apps use the environment variable '{env}' for their own settings.",
                    api,
                    at=key,
                    hint="Use a name with the name of the API, for example 'HOLIDAYS_API_URL'.",
                )
                continue
            first = envs.setdefault(env, f"{api.id}.{key}")
            if first != f"{api.id}.{key}":
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
            yield _error(
                "unsuitable-security",
                f"The security scheme '{security.scheme}' is not an API key in a header or a "
                "query parameter, or a bearer token.",
                api,
                at="security",
                hint="The clients support only these schemes. Call the API from hand-written "
                "code to use another scheme.",
            )
    for operation in definition.operations.values():
        if len(set(operation.apis)) != len(operation.apis):
            yield _error(
                "duplicate-name", "The names in 'apis' must be unique.", operation, at="apis"
            )
        for name in operation.apis:
            if name not in definition.apis:
                yield _missing(operation, "apis", "API", name, definition.apis)


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


def _default_fits(field: Field) -> bool:
    value = field.default
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
