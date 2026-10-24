"""The translations of the UI text: more than one language for the front ends."""

import re

import pydantic

from appgen.dsl.element import Element, MemberName, Text

VALUE = re.compile(r"\{([a-z][A-Za-z0-9_]*)\}")
"""A value in a text, for example `{count}` in `{count} selected`. The app fills it in."""


class Language(Element):
    """A language of the UI, with the translation of each text."""

    label: Text
    """The name of the language in the language itself, for example `Deutsch`."""
    text: dict[Text, Text] = pydantic.Field(default_factory=dict[str, str])
    """The translations: the key is a text of the default language, as the app shows it."""


class Translations(Element):
    """The languages of the UI. The text of the definition is in the default language."""

    default: MemberName
    """The code of the language of the definition, for example `en`. It is a key of `languages`."""
    languages: dict[MemberName, Language] = pydantic.Field(min_length=2)
    """The languages by code, for example `en` and `de`."""
