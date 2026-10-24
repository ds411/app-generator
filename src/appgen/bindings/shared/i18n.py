"""The translations of the UI text in the front ends (React and Next.js).

Without a `translations` section, the helpers write the text as it is.
With the section, each text of the definition and each fixed text of the
templates becomes a call of `t`, for example `{t("Projects")}`. The
function `t` of `src/shared/lib/i18n.ts` looks up the text in the
selected language at render time. A text can hold values, for example
`t("Page {page} of {count}", { page, count })`. `finish` adds the import
of `t` to each file that calls it.

`app_texts` renders an app in memory, and returns each text that the
helpers write as a call of `t`: the keys that a language can translate.
"""

import json
import re
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from appgen.bindings.shared.ui import js, jsx_attr, jsx_text
from appgen.dsl.model import AppDefinition
from appgen.dsl.translations import VALUE
from appgen.gen.binding import Binding, Output

I18N_MODULE = "@/shared/lib/i18n"
_CALL = re.compile(r"(?<![\w.$])t\(")
_IMPORT = f'import {{ t }} from "{I18N_MODULE}";\n'
_MODULE_IMPORT = re.compile(rf'^import \{{ ([^}}]*) \}} from "{I18N_MODULE}";?$', re.MULTILINE)
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')

_texts: ContextVar[set[str] | None] = ContextVar("appgen_i18n_texts", default=None)


@dataclass(frozen=True, slots=True)
class LanguagePlan:
    """A language of the app, with its translations sorted by key."""

    code: str
    label: str
    locale: str
    """The locale of the dates and numbers (BCP 47): `locale`, or the code."""
    element_id: str
    text: dict[str, str]


@dataclass(frozen=True, slots=True)
class I18nPlan:
    """The languages of the app. The first language is the default language."""

    element_id: str
    default: str
    languages: list[LanguagePlan]


def i18n_plan(definition: AppDefinition) -> I18nPlan | None:
    """Return the languages of a definition, or None if it has no translations."""
    translations = definition.translations
    if translations is None:
        return None
    order = [translations.default] + [
        c for c in translations.languages if c != translations.default
    ]
    return I18nPlan(
        element_id=translations.id,
        default=translations.default,
        languages=[
            LanguagePlan(
                code=code,
                label=translations.languages[code].label,
                locale=translations.languages[code].locale_tag(code),
                element_id=translations.languages[code].id,
                text=dict(sorted(translations.languages[code].text.items())),
            )
            for code in order
        ],
    )


def text_helpers(definition: AppDefinition) -> dict[str, Any]:
    """Return the template values for the UI text.

    - `jsx_text(text)` and `jsx_attr(text)` replace the helpers of the
      same name: a JSX child and a JSX attribute value.
    - `tr(expression)` takes a JavaScript expression of a text, for
      example `action.label`, and returns the expression of its
      translation.
    - `text(value)` writes a text that a module holds as a JavaScript
      literal, for a component that translates it with `tr`.
    - `jsx_format(text, **values)` and `js_format(text, **values)` write a
      text with values, for example `jsx_format("Page {page} of {count}",
      page="page", count="pageCount")`: a JSX child and a JavaScript
      expression. Without translations, the values are in the text, as
      JSX expressions or in a template literal.
    - `i18n` is the plan of the languages, or None.
    """
    plan = i18n_plan(definition)
    if plan is None:
        return {
            "jsx_text": jsx_text,
            "jsx_attr": jsx_attr,
            "tr": _same,
            "text": js,
            "jsx_format": _jsx_format,
            "js_format": _js_format,
            "i18n": None,
        }
    return {
        "jsx_text": _translated,
        "jsx_attr": _translated,
        "tr": _call,
        "text": text_js,
        "jsx_format": _jsx_format_call,
        "js_format": _js_format_call,
        "i18n": plan,
    }


@contextmanager
def _recording() -> Generator[set[str]]:
    texts: set[str] = set()
    token = _texts.set(texts)
    try:
        yield texts
    finally:
        _texts.reset(token)


def app_texts(definition: AppDefinition, binding: Binding) -> list[str]:
    """Return the texts that the app of a front-end binding translates, sorted.

    The generator renders the app in memory. Each text that the helpers
    write as a call of `t`, or as a text for `tr`, is a key that a
    language can translate. A definition without translations has no
    such text.
    """
    from appgen.gen.generator import generate

    if definition.translations is None:
        return []
    with _recording() as texts:
        generate(definition, binding)
    return sorted(texts)


def _record(text: str) -> None:
    texts = _texts.get()
    if texts is not None and text:
        texts.add(text)


def finish(path: str, content: str, definition: AppDefinition) -> str:
    """Add the import of `t` to a TypeScript file that calls it.

    A file that imports other names of the module gets `t` in the same
    import. Else the import goes before the first import, else after the
    directive, else after the comments of the header (the traces).
    """
    if (
        definition.translations is None
        or not path.endswith((".ts", ".tsx"))
        or path.endswith("lib/i18n.ts")
        or _IMPORT in content
        or not _CALL.search(content)
    ):
        return content
    found = _MODULE_IMPORT.search(content)
    if found is not None:
        names = {name.strip() for name in found[1].split(",")} | {"t"}
        names_text = ", ".join(sorted(names, key=str.lower))
        return content[: found.start(1)] + names_text + content[found.end(1) :]
    lines = content.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.startswith("import ")), None)
    if index is not None:
        return "".join([*lines[:index], _IMPORT, *lines[index:]])
    directive = [i for i, line in enumerate(lines) if line.strip() == '"use client";']
    if directive:
        return "".join([*lines[: directive[0] + 1], _IMPORT, *lines[directive[0] + 1 :]])
    index = next((i for i, line in enumerate(lines) if not line.startswith("//")), len(lines))
    return "".join([*lines[:index], _IMPORT, "\n", *lines[index:]])


def _same(expression: str) -> str:
    return expression


def _call(expression: str) -> str:
    for literal in _STRING.findall(expression):
        _record(json.loads(literal))
    return f"t({expression})"


def _translated(text: Any) -> str:
    if not isinstance(text, str):
        return jsx_attr(text)
    return "{" + _call(js(text)) + "}"


def text_js(value: Any) -> str:
    """Return a text as a JavaScript literal, for a component that translates it with `t`.

    `app_texts` records the text. Python code that writes JavaScript uses
    it, as the templates use the helper `text`.
    """
    if isinstance(value, str):
        _record(value)
    return js(value)


def _parts(text: str, values: dict[str, str]) -> list[str]:
    """Split a text at its values: the text parts at even and the value names at odd indexes."""
    parts = VALUE.split(text)
    if set(parts[1::2]) != set(values):
        raise ValueError(f"The values {sorted(values)} do not agree with the text {text!r}.")
    return parts


def _jsx_format(text: str, **values: str) -> str:
    parts = _parts(text, values)
    return "".join(part if i % 2 == 0 else "{" + values[part] + "}" for i, part in enumerate(parts))


def _js_format(text: str, **values: str) -> str:
    parts = _parts(text, values)
    body = "".join(
        part.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        if i % 2 == 0
        else "${" + values[part] + "}"
        for i, part in enumerate(parts)
    )
    return f"`{body}`"


def _js_format_call(text: str, **values: str) -> str:
    _parts(text, values)
    _record(text)
    entries = ", ".join(n if e == n else f"{n}: {e}" for n, e in sorted(values.items()))
    return f"t({js(text)}, {{ {entries} }})"


def _jsx_format_call(text: str, **values: str) -> str:
    return "{" + _js_format_call(text, **values) + "}"


def i18n_rules() -> tuple[Output, ...]:
    """Return the output rules of the translations: the `t` function and the language switch."""
    return tuple(
        Output(template=template, path=path, when="i18n")
        for template, path in (
            ("ui/lib/i18n.ts.j2", "src/shared/lib/i18n.ts"),
            ("ui/lib/language-provider.tsx.j2", "src/shared/lib/language-provider.tsx"),
            ("ui/features/switch-language/index.ts.j2", "src/features/switch-language/index.ts"),
            (
                "ui/features/switch-language/language-switch.tsx.j2",
                "src/features/switch-language/ui/language-switch.tsx",
            ),
        )
    )
