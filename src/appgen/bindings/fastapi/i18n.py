"""The values of the generated test of the languages of the API (ADR 0010).

The test sends requests with an `Accept-Language` header in the default
language and in a second language, and checks the language of the
response and of one message. The tags of the test must select their
language without doubt, so this module picks them from the languages.
"""

from dataclasses import dataclass

from appgen.bindings.shared.i18n import I18nPlan, LanguagePlan
from appgen.dsl.translations import VALUE

_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True, slots=True)
class LanguageTest:
    """The languages and the tags of the generated test of the languages."""

    default: LanguagePlan
    second: LanguagePlan
    """A language that is not the default language."""
    second_tag: str
    """A tag that selects the second language by its code or its locale."""
    near_tag: str | None
    """A tag that selects the second language by its primary language only, or None."""
    unknown_tag: str
    """A tag that selects no language."""

    def text(self, language: LanguagePlan, key: str, **values: object) -> str:
        """Return the translation of a text in a language, with its values, as `t` does."""
        translation = language.text.get(key, key)
        return VALUE.sub(lambda m: str(values.get(m[1], m[0])), translation)


def _tags(language: LanguagePlan) -> set[str]:
    return {language.code.lower().replace("_", "-"), language.locale.lower()}


def language_test(plan: I18nPlan) -> LanguageTest | None:
    """Return the values of the test of the languages, or None if no tag is free of doubt.

    The API takes the first language that has a tag of the header, so the
    tag of the second language must not be a tag of a language before it.
    """
    default = plan.languages[0]
    for index, second in enumerate(plan.languages[1:], start=1):
        before = plan.languages[:index]
        taken = set[str]().union(*(_tags(language) for language in before))
        tag = next((tag for tag in sorted(_tags(second)) if tag not in taken), None)
        if tag is None:
            continue
        primary = tag.split("-")[0]
        all_tags = set[str]().union(*(_tags(language) for language in plan.languages))
        near: str | None = f"{primary}-zz"
        if near in all_tags or any(t.split("-")[0] == primary for t in taken):
            near = None
        primaries = {t.split("-")[0] for t in all_tags}
        # The codes qaa to qtz are for private use (ISO 639-2).
        unknown = next(
            code
            for code in (f"q{a}{b}" for a in "abcdefghijklmnopqrst" for b in _LETTERS)
            if code not in primaries
        )
        return LanguageTest(default, second, tag, near, unknown)
    return None
