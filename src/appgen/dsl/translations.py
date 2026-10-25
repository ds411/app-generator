"""The translations of the UI text: more than one language for the front ends."""

import re
from typing import Literal

import pydantic

from appgen.dsl.element import Element, MemberName, Text

VALUE = re.compile(r"\{([a-z][A-Za-z0-9_]*)\}")
"""A value in a text, for example `{count}` in `{count} selected`. The app fills it in."""
LOCALE = re.compile(
    r"[A-Za-z]{2,3}(-[A-Za-z]{3}){0,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|[0-9]{3}))?"
    r"(-([A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*(-[0-9A-WY-Za-wy-z](-[A-Za-z0-9]{2,8})+)*"
    r"(-[Xx](-[A-Za-z0-9]{1,8})+)?"
)
"""A language tag (BCP 47), for example `de`, `de-CH`, or `ar-EG-u-nu-latn`."""

type Direction = Literal["ltr", "rtl"]

RTL_LANGUAGES = frozenset(
    {"ar", "arc", "azb", "ckb", "dv", "fa", "he", "iw", "ks", "lrc", "mzn", "nqo", "ps", "sd"}
    | {"syr", "ug", "ur", "yi"}
)
"""The primary languages (ISO 639) that a script from right to left writes by default."""
RTL_SCRIPTS = frozenset({"adlm", "arab", "hebr", "mand", "nkoo", "rohg", "syrc", "thaa", "yezi"})
"""The scripts (ISO 15924) from right to left, for example `Arab` in `ha-Arab`."""


def locale_direction(locale: str) -> Direction:
    """Return the direction of the text of a locale (BCP 47): `rtl` or `ltr`.

    A script subtag decides first (`az-Arab` is `rtl`, `ur-Latn` is `ltr`),
    else the primary language (`ar`, `fa`, `he`, and `ur` are `rtl`).
    """
    language, *subtags = locale.lower().replace("_", "-").split("-")
    for subtag in subtags:
        if len(subtag) == 4 and subtag.isalpha():
            return "rtl" if subtag in RTL_SCRIPTS else "ltr"
        if len(subtag) == 1:
            break
    return "rtl" if language in RTL_LANGUAGES else "ltr"


class Language(Element):
    """A language of the UI, with the translation of each text."""

    label: Text
    """The name of the language in the language itself, for example `Deutsch`."""
    text: dict[Text, Text] = pydantic.Field(default_factory=dict[str, str])
    """The translations: the key is a text of the default language, as the app shows it."""
    locale: Text | None = None
    """The locale of the dates and numbers, a language tag (BCP 47), for example `de-CH`.

    The default is the code of the language.
    """
    direction: Direction | None = None
    """The direction of the text: `ltr` (left to right) or `rtl` (right to left).

    The default comes from the locale, for example `rtl` for `ar`, `fa`, `he`, and `ur`.
    """

    def locale_tag(self, code: str) -> str:
        """Return the locale of the language: `locale`, or the code."""
        return self.locale or code

    def text_direction(self, code: str) -> Direction:
        """Return the direction of the text: `direction`, or the direction of the locale."""
        return self.direction or locale_direction(self.locale_tag(code))


class Translations(Element):
    """The languages of the UI. The text of the definition is in the default language."""

    default: MemberName
    """The code of the language of the definition, for example `en`. It is a key of `languages`."""
    languages: dict[MemberName, Language] = pydantic.Field(min_length=2)
    """The languages by code, for example `en` and `de`."""
