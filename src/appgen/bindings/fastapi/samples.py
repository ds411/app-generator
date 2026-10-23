"""Sample strings that match a regular expression, for the generated tests.

The generated tests need valid values for string fields with a
`pattern`. This module makes them from the parse tree of the pattern. It
knows literals, character classes, groups, alternatives, and repeats.
That covers the patterns of most definitions. For other patterns, the
app author gives a value with the `x-example` key of the field.
"""

import importlib
import re
import string
from typing import Any

# The private parser of the standard library gives the parse tree of a
# pattern. It is stable across the Python versions that appgen supports.
sre: Any = importlib.import_module("re._constants")
_parser: Any = importlib.import_module("re._parser")

_PRINTABLE = string.ascii_letters + string.digits + "-_"
_CATEGORIES: dict[Any, str] = {
    sre.CATEGORY_DIGIT: string.digits,
    sre.CATEGORY_WORD: string.ascii_letters + string.digits + "_",
    sre.CATEGORY_SPACE: " ",
    sre.CATEGORY_NOT_DIGIT: string.ascii_letters,
    sre.CATEGORY_NOT_WORD: "-",
    sre.CATEGORY_NOT_SPACE: _PRINTABLE,
}


class PatternError(ValueError):
    """The module cannot make a sample for a pattern."""


def pattern_samples(
    pattern: str, count: int, min_length: int = 0, max_length: int | None = None
) -> list[str]:
    """Return up to `count` different strings that match a pattern, in a fixed order.

    The strings also have a length from `min_length` to `max_length`.
    """
    try:
        tree = _parser.parse(pattern)
    except re.error as error:
        raise PatternError(f"The pattern {pattern!r} is not valid: {error}") from None
    samples: list[str] = []
    for repeat in (1, 3, 6, 12):
        for variant in range(count * 4):
            sample = _render(tree, variant, repeat)
            fits = min_length <= len(sample) <= (max_length or len(sample))
            if fits and re.fullmatch(pattern, sample) and sample not in samples:
                samples.append(sample)
            if len(samples) == count:
                return samples
    if not samples:
        raise PatternError(f"No sample matches the pattern {pattern!r}.")
    return samples


def _render(tree: Any, variant: int, repeat: int) -> str:
    """Return one string for a parse tree.

    The variant changes the first free choice. An open repeat, for
    example `+`, takes `repeat` items, or more if its minimum is higher.
    """
    out: list[str] = []
    state = {"variant": variant, "repeat": repeat}
    for op, arg in tree:
        out.append(_node(op, arg, state))
    return "".join(out)


def _sub(tree: Any, state: dict[str, int]) -> str:
    variant = state["variant"]
    state["variant"] = 0
    return _render(tree, variant, state["repeat"])


def _choose(options: str, state: dict[str, int]) -> str:
    variant = state["variant"]
    state["variant"] = 0
    return options[variant % len(options)]


def _node(op: Any, arg: Any, state: dict[str, int]) -> str:
    if op is sre.LITERAL:
        return chr(arg)
    if op is sre.NOT_LITERAL:
        return _choose("".join(c for c in _PRINTABLE if ord(c) != arg), state)
    if op is sre.ANY:
        return _choose(_PRINTABLE, state)
    if op is sre.IN:
        return _choose(_class(arg), state)
    if op in (sre.MAX_REPEAT, sre.MIN_REPEAT, sre.POSSESSIVE_REPEAT):
        low, high, item = arg
        times = max(low, state["repeat"])
        times = min(times, high) if high is not sre.MAXREPEAT else times
        return "".join(_sub(item, state) for _ in range(times))
    if op is sre.SUBPATTERN:
        return _sub(arg[-1], state)
    if op is sre.ATOMIC_GROUP:
        return _sub(arg, state)
    if op is sre.BRANCH:
        branches = arg[1]
        variant = state["variant"]
        state["variant"] = 0
        return _render(branches[variant % len(branches)], variant // len(branches), state["repeat"])
    if op in (sre.AT, sre.ASSERT, sre.ASSERT_NOT):
        return ""
    raise PatternError(f"The pattern element {op} is not supported.")


def _class(items: Any) -> str:
    chars: list[str] = []
    negate = False
    for op, arg in items:
        if op is sre.NEGATE:
            negate = True
        elif op is sre.LITERAL:
            chars.append(chr(arg))
        elif op is sre.RANGE:
            chars.extend(chr(c) for c in range(arg[0], arg[1] + 1))
        elif op is sre.CATEGORY:
            chars.extend(_CATEGORIES.get(arg, ""))
        else:
            raise PatternError(f"The class element {op} is not supported.")
    if negate:
        chars = [c for c in _PRINTABLE if c not in chars]
    if not chars:
        raise PatternError("A character class has no characters.")
    return "".join(dict.fromkeys(chars))
