"""The translations of the UI text: more than one language for the front ends."""

import re

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

    def locale_tag(self, code: str) -> str:
        """Return the locale of the language: `locale`, or the code."""
        return self.locale or code


class Translations(Element):
    """The languages of the UI. The text of the definition is in the default language."""

    default: MemberName
    """The code of the language of the definition, for example `en`. It is a key of `languages`."""
    languages: dict[MemberName, Language] = pydantic.Field(min_length=2)
    """The languages by code, for example `en` and `de`."""
