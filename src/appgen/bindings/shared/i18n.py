"""The translations of the UI text in the front ends (React and Next.js).

Without a `translations` section, the helpers write the text as it is.
With the section, each text of the definition becomes a call of `t`,
for example `{t("Projects")}`. The function `t` of `src/shared/lib/i18n.ts`
looks up the text in the selected language at render time. `finish`
adds the import of `t` to each file that calls it.
"""

import re
from dataclasses import dataclass
from typing import Any

from appgen.bindings.shared.ui import js, jsx_attr, jsx_text
from appgen.dsl.model import AppDefinition
from appgen.gen.binding import Output

I18N_MODULE = "@/shared/lib/i18n"
_CALL = re.compile(r"(?<![\w.$])t\(")
_IMPORT = f'import {{ t }} from "{I18N_MODULE}";\n'


@dataclass(frozen=True, slots=True)
class LanguagePlan:
    """A language of the app, with its translations sorted by key."""

    code: str
    label: str
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
                element_id=translations.languages[code].id,
                text=dict(sorted(translations.languages[code].text.items())),
            )
            for code in order
        ],
    )


def text_helpers(definition: AppDefinition) -> dict[str, Any]:
    """Return the template values for the UI text: `jsx_text`, `jsx_attr`, `tr`, and `i18n`.

    The values replace the helpers of the same name in the templates.
    `tr` takes a JavaScript expression of a text, for example
    `action.label`, and returns the expression of its translation.
    """
    plan = i18n_plan(definition)
    if plan is None:
        return {"jsx_text": jsx_text, "jsx_attr": jsx_attr, "tr": _same, "i18n": None}
    return {
        "jsx_text": _translated,
        "jsx_attr": _translated,
        "tr": _call,
        "i18n": plan,
    }


def finish(path: str, content: str, definition: AppDefinition) -> str:
    """Add the import of `t` to a TypeScript file that calls it, after the directive."""
    if (
        definition.translations is None
        or not path.endswith((".ts", ".tsx"))
        or path.endswith("lib/i18n.ts")
        or _IMPORT in content
        or not _CALL.search(content)
    ):
        return content
    lines = content.splitlines(keepends=True)
    index = next((i for i, line in enumerate(lines) if line.startswith("import ")), None)
    if index is None:
        directive = [i for i, line in enumerate(lines) if line.strip() == '"use client";']
        index = directive[0] + 1 if directive else 0
    return "".join([*lines[:index], _IMPORT, *lines[index:]])


def _same(expression: str) -> str:
    return expression


def _call(expression: str) -> str:
    return f"t({expression})"


def _translated(text: Any) -> str:
    if not isinstance(text, str):
        return jsx_attr(text)
    return "{" + _call(js(text)) + "}"


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
