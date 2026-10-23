"""Python names for the elements of an app definition.

The case conversions come from `appgen.gen.naming`. This module adds the
rules that only Python needs: plurals for tables and URL paths, and safe
attribute names.
"""

import keyword
import re

from appgen.gen.naming import snake

# Names that a model attribute cannot have, because they hide a name of
# SQLAlchemy, of Pydantic, or a type name that the generated modules use.
_RESERVED = frozenset(
    {
        "bool",
        "construct",
        "copy",
        "dict",
        "dt",
        "fields",
        "float",
        "int",
        "json",
        "list",
        "metadata",
        "registry",
        "schema",
        "str",
        "validate",
    }
)


def plural(name: str) -> str:
    """Return the English plural of a name in snake case, with simple rules."""
    head, _, last = snake(name).rpartition("_")
    if re.search(r"[^aeiou]y$", last):
        last = last[:-1] + "ies"
    elif re.search(r"(s|x|z|ch|sh)$", last):
        last += "es"
    else:
        last += "s"
    return f"{head}_{last}" if head else last


def singular(name: str) -> str:
    """Return the English singular of a plural name in snake case, with simple rules."""
    if name.endswith("ies"):
        return name[:-3] + "y"
    if re.search(r"(ss|x|z|ch|sh)es$", name):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def attribute(name: str) -> str:
    """Return a safe Python attribute name for a definition name.

    A name that is a Python keyword, or that hides a name of SQLAlchemy or
    Pydantic, gets a final underscore, for example `from_` for `from`.
    """
    if keyword.iskeyword(name) or name in _RESERVED or name.startswith("model_"):
        return f"{name}_"
    return name
