"""The classes of a side in the templates of the front ends, and their logical classes.

A front end shows a language from right to left with `dir="rtl"` on the
`html` element (ADR 0010). The logical classes of Tailwind CSS follow the
direction of the text: `ms-2` is a margin at the start of the line, at
the left in `ltr` and at the right in `rtl`. A class of a side, for
example `ml-2`, `left-0`, or `text-right`, stays at its side in `rtl`.
So the templates use the logical classes, except the classes in
`ALLOWED`. `scripts/vendor_shadcn.py` changes the classes of the shadcn/ui
components with `logical_classes`, and a test finds a class of a side in
the templates.
"""

import re

_TOKEN = re.compile(r"[^\s\"'`]+")
"""A candidate class: the text between white space and quotes."""
_SIDE = re.compile(
    r"(?P<sign>!?-?)(?:"
    r"(?P<box>[mp])(?P<box_side>[lr])-(?P<box_value>.+)"
    r"|(?P<inset>left|right)-(?P<inset_value>.+)"
    r"|text-(?P<text>left|right)"
    r"|border-(?P<border>[lr])(?P<border_value>-.+)?"
    r"|rounded-(?P<corner>[lr]|[tb][lr])(?P<corner_value>-.+)?"
    r"|(?P<slide>slide-(?:in-from|out-to))-(?P<slide_side>left|right)(?P<slide_value>-.+)?"
    r"|(?P<float>float|clear)-(?P<float_side>left|right)"
    r")"
)
"""A utility of a side, for example `ml-2`, `-right-4`, `border-l`, or `rounded-tr-md`."""
_TRAILING = ",;)}"

_START_END = {"l": "s", "r": "e", "left": "start", "right": "end"}
_CORNERS = {"l": "s", "r": "e", "tl": "ss", "tr": "se", "bl": "es", "br": "ee"}

ALLOWED: dict[str, str] = {
    "left-[50%]": "It centers a dialog with translate-x-[-50%]: the same in both directions.",
    "left-1/2": "It centers the dot of a radio button with -translate-x-1/2.",
    "after:left-1/2": "It centers the line of the sidebar rail in the rail.",
    "data-[side=left]:slide-in-from-right-2": "The popper side is a side of the screen.",
    "data-[side=right]:slide-in-from-left-2": "The popper side is a side of the screen.",
}
"""The classes of a side that the templates keep, with the reason."""


def _utility(token: str) -> tuple[str, str]:
    """Split a class into its variants (with the last colon) and its utility.

    A colon in brackets is part of a variant, for example in
    `[[data-side=left]_&]:-right-2`.
    """
    depth = 0
    split = 0
    for index, char in enumerate(token):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == ":" and depth == 0:
            split = index + 1
    return token[:split], token[split:]


def logical_class(token: str) -> str | None:
    """Return the logical class of a class of a side, or None for another class.

    For example `ms-auto` for `ml-auto`, `sm:text-start` for
    `sm:text-left`, and `group-data-[side=left]:-end-4` for
    `group-data-[side=left]:-right-4`.
    """
    variants, utility = _utility(token)
    match = _SIDE.fullmatch(utility)
    if match is None:
        return None
    sign = match["sign"]
    if match["box"]:
        logical = f"{match['box']}{_START_END[match['box_side']]}-{match['box_value']}"
    elif match["inset"]:
        logical = f"{_START_END[match['inset']]}-{match['inset_value']}"
    elif match["text"]:
        logical = f"text-{_START_END[match['text']]}"
    elif match["border"]:
        logical = f"border-{_START_END[match['border']]}{match['border_value'] or ''}"
    elif match["corner"]:
        logical = f"rounded-{_CORNERS[match['corner']]}{match['corner_value'] or ''}"
    elif match["slide"]:
        side = _START_END[match["slide_side"]]
        logical = f"{match['slide']}-{side}{match['slide_value'] or ''}"
    else:
        logical = f"{match['float']}-{_START_END[match['float_side']]}"
    return f"{variants}{sign}{logical}"


def side_classes(text: str) -> list[str]:
    """Return the classes of a side in a text that `ALLOWED` does not have, in order."""
    found: list[str] = []
    for match in _TOKEN.finditer(text):
        token = match[0].rstrip(_TRAILING)
        if token not in ALLOWED and logical_class(token) is not None:
            found.append(token)
    return found


def logical_classes(text: str) -> str:
    """Change each class of a side in a text to its logical class, except the `ALLOWED` classes."""

    def change(match: re.Match[str]) -> str:
        whole = match[0]
        token = whole.rstrip(_TRAILING)
        logical = None if token in ALLOWED else logical_class(token)
        return whole if logical is None else logical + whole[len(token) :]

    return _TOKEN.sub(change, text)
