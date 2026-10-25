from pathlib import Path

import pytest

from appgen.bindings.shared.sides import ALLOWED, logical_class, logical_classes, side_classes

BINDINGS = Path(__file__).parent.parent / "src" / "appgen" / "bindings"
FRONT_ENDS = ("shared", "react", "nextjs")


def front_end_sources() -> list[Path]:
    """The templates and the Python modules that write the code of the front ends."""
    files = [p for name in FRONT_ENDS for p in (BINDINGS / name).rglob("*") if p.is_file()]
    return sorted(
        p
        for p in files
        if p.suffix in (".j2", ".py") and p.name != "sides.py" and "__pycache__" not in p.parts
    )


@pytest.mark.parametrize(
    ("side", "logical"),
    [
        ("ml-auto", "ms-auto"),
        ("-mr-2", "-me-2"),
        ("pl-8", "ps-8"),
        ("sm:pr-2.5", "sm:pe-2.5"),
        ("left-0", "start-0"),
        ("-right-4", "-end-4"),
        ("group-data-[side=left]:-right-4", "group-data-[side=left]:-end-4"),
        (
            "[[data-side=left][data-collapsible=offcanvas]_&]:-right-2",
            "[[data-side=left][data-collapsible=offcanvas]_&]:-end-2",
        ),
        ("text-left", "text-start"),
        ("sm:text-right", "sm:text-end"),
        ("border-l", "border-s"),
        ("border-r-0", "border-e-0"),
        ("rounded-l-md", "rounded-s-md"),
        ("rounded-tr-md", "rounded-se-md"),
        ("data-[state=open]:slide-in-from-left", "data-[state=open]:slide-in-from-start"),
        ("slide-out-to-right-2", "slide-out-to-end-2"),
        ("float-right", "float-end"),
        ("ms-auto", None),
        ("border-b", None),
        ("translate-x-px", None),
        ("left", None),
        ("rounded-lg", None),
        ("text-lg", None),
    ],
)
def test_a_class_of_a_side_has_a_logical_class(side: str, logical: str | None) -> None:
    assert logical_class(side) == logical


def test_logical_classes_change_the_classes_in_a_text_and_keep_the_allowed_classes() -> None:
    text = 'cn("ml-auto size-4", open && "pr-2", "left-[50%] translate-x-[-50%]")'
    assert (
        logical_classes(text)
        == 'cn("ms-auto size-4", open && "pe-2", "left-[50%] translate-x-[-50%]")'
    )
    assert side_classes(text) == ["ml-auto", "pr-2"]
    assert side_classes("// The menu at the left side of the page.") == []


def test_the_front_ends_use_no_class_of_a_side() -> None:
    found = [
        f"{path.relative_to(BINDINGS)}:{number}: {token} (use {logical_class(token)})"
        for path in front_end_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for token in side_classes(line)
    ]
    assert found == [], (
        "Use the logical classes, so that a language from right to left shows the layout "
        "from right to left. Add a class that must stay at its side to "
        "appgen.bindings.shared.sides.ALLOWED, with the reason."
    )


def test_each_allowed_class_is_in_use_and_has_a_reason() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in front_end_sources())
    tokens = set(text.replace('"', " ").replace("`", " ").split())
    assert [token for token in ALLOWED if token not in tokens] == []
    assert all(reason.endswith(".") for reason in ALLOWED.values())
