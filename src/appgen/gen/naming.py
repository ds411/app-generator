"""Convert definition names to the naming conventions of a language.

The DSL names are snake case (`due_date`) or Pascal case for entities
(`ProjectTask`), see ADR 0002. The templates use these functions as
Jinja2 filters, for example `{{ name | camel }}`.
"""

import re

_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[A-Z]|\d+")


def words(name: str) -> list[str]:
    """Return the words of a name in lower case: `ProjectTask` and `project_task` give the same."""
    return [word.lower() for part in re.split(r"[_\-\s]+", name) for word in _WORD.findall(part)]


def camel(name: str) -> str:
    """Return the name in camel case, for example `dueDate`."""
    parts = words(name)
    return parts[0] + "".join(word.capitalize() for word in parts[1:]) if parts else ""


def pascal(name: str) -> str:
    """Return the name in Pascal case, for example `DueDate`."""
    return "".join(word.capitalize() for word in words(name))


def kebab(name: str) -> str:
    """Return the name in kebab case, for example `due-date`."""
    return "-".join(words(name))


def snake(name: str) -> str:
    """Return the name in snake case, for example `due_date`."""
    return "_".join(words(name))


def constant(name: str) -> str:
    """Return the name in upper snake case, for example `DUE_DATE`."""
    return snake(name).upper()


NAMING_FILTERS = {
    "camel": camel,
    "pascal": pascal,
    "kebab": kebab,
    "snake": snake,
    "constant": constant,
}
