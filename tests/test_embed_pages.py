"""Pages that other websites show in a frame: `pages.*.embed` (ADR 0032)."""

import re
from pathlib import Path

import pytest

from appgen.bindings.react.helpers import frame_rules
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.gen import find_binding, generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "project-tracker" / "app.yaml"
ROOM_BOOKING = ROOT / "examples" / "room-booking" / "app.yaml"

ROOMS = """\
  rooms:
    path: /rooms
    title: Rooms
    entity: Room
    content: { view: room_table }
"""


def room_booking(rooms: str) -> str:
    """Return the room booking example with another page `rooms`."""
    text = ROOM_BOOKING.read_text()
    start = text.index("  rooms:\n    path: /rooms\n")
    end = text.index("  room_detail:\n")
    return text[:start] + rooms + text[end:]


def codes(rooms: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(room_booking(rooms), str(ROOM_BOOKING))
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(binding: str) -> dict[str, str]:
    result = generate(load_definition(EXAMPLE), find_binding(binding))
    return {f.path: f.content for f in result.files}


@pytest.fixture(scope="module")
def nextjs() -> dict[str, str]:
    return files_of("nextjs")


@pytest.fixture(scope="module")
def react() -> dict[str, str]:
    return files_of("react")


def test_a_public_page_takes_https_origins() -> None:
    rooms = ROOMS + "    embed: [https://www.example.com, https://intranet.example.com:8443]\n"

    assert codes(rooms) == []
    page = load_definition_text(room_booking(rooms), str(ROOM_BOOKING)).pages["rooms"]
    assert page.embed == ["https://www.example.com", "https://intranet.example.com:8443"]


def test_a_page_that_is_not_public_takes_no_embed() -> None:
    text = room_booking(ROOMS + "    embed: [https://www.example.com]\n")
    text = text.replace("  public_pages: [rooms]\n", "  public_pages: []\n")

    found = validate_definition(load_definition_text(text, str(ROOM_BOOKING)))

    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "pages.rooms")]
    assert "auth.public_pages" in (found[0].hint or "")


def test_a_page_with_embed_has_no_layout() -> None:
    rooms = ROOMS + "    layout: app_shell\n    embed: [https://www.example.com]\n"
    text = room_booking(rooms)
    layout = re.search(r"\n  layouts:\n    (\w+):", text)
    assert layout is not None
    text = text.replace("layout: app_shell", f"layout: {layout.group(1)}")

    found = validate_definition(load_definition_text(text, str(ROOM_BOOKING)))

    assert [(d.code, d.element_id) for d in found] == [("invalid-option", "pages.rooms")]
    assert "'layout'" in (found[0].hint or "")


@pytest.mark.parametrize(
    "origin",
    [
        "http://www.example.com",
        "https://www.example.com/",
        "https://www.example.com/booking",
        "https://WWW.example.com",
        "https://*.example.com",
        "www.example.com",
    ],
)
def test_an_origin_is_an_https_origin(origin: str) -> None:
    assert codes(ROOMS + f"    embed: [{origin!r}]\n") == [("invalid-value", "pages.rooms")]


def test_an_origin_is_in_the_list_one_time() -> None:
    rooms = ROOMS + "    embed: [https://www.example.com, https://www.example.com]\n"

    assert codes(rooms) == [("duplicate-value", "pages.rooms")]


def test_the_list_of_origins_is_not_empty() -> None:
    with pytest.raises(DefinitionError):
        load_definition_text(room_booking(ROOMS + "    embed: []\n"), str(ROOM_BOOKING))


def test_the_nextjs_app_shows_the_page_without_the_app_shell(nextjs: dict[str, str]) -> None:
    assert "app/(embed)/embed/holidays/page.tsx" in nextjs
    assert "app/(app-shell)/embed/holidays/page.tsx" not in nextjs
    layout = nextjs["app/(embed)/layout.tsx"]
    assert "// @trace pages.holiday_widget file" in layout
    assert "<main " in layout and "widgets/layouts" not in layout
    search = nextjs["src/features/search-pages/ui/page-search.tsx"]
    assert '&& name !== "holidayWidget"' in search


def test_the_nextjs_app_sends_the_origins_of_the_page(nextjs: dict[str, str]) -> None:
    config = nextjs["next.config.ts"]

    rule = r'\{ source: "([^"]+)", headers: \[\{ key: FRAME_HEADER, value: "([^"]+)"'
    rules = re.findall(rule, config)
    # The last rule of a path wins: the rule of all paths comes first.
    assert rules == [
        ("/:path*", "frame-ancestors 'self'"),
        ("/embed/holidays", "frame-ancestors 'self' https://partner.example"),
    ]
    assert "// @trace pages.holiday_widget\n" in config


def test_the_react_app_shows_the_page_without_the_app_shell(react: dict[str, str]) -> None:
    router = react["src/app/router.tsx"]
    embed = router.index("element: <EmbedLayout />")
    shell = router.index("<AppShellLayout>")
    assert '{ path: "/embed/holidays", element: <HolidayWidgetPage /> }' in router[embed:shell]
    assert "<HolidayWidgetPage />" not in router[shell:]
    assert "export function EmbedLayout()" in react["src/app/layout/embed-layout.tsx"]
    search = react["src/features/search-pages/ui/page-search.tsx"]
    assert '&& name !== "holidayWidget"' in search


def test_the_nginx_configuration_sends_the_origins_of_the_page(react: dict[str, str]) -> None:
    nginx = react["nginx.conf"]

    assert "map $request_uri $frame_ancestors {" in nginx
    assert "    default \"'self'\";\n" in nginx
    assert '    "~^/embed/holidays/?(\\?|$)" "\'self\' https://partner.example";\n' in nginx
    location = nginx[nginx.index("    location / {") :]
    header = 'add_header Content-Security-Policy "frame-ancestors $frame_ancestors" always;'
    assert header in location


def test_the_pattern_of_nginx_matches_the_uris_of_the_page() -> None:
    text = (
        room_booking(ROOMS)
        .replace(
            '  room_detail:\n    path: "/rooms/{id}"\n',
            '  room_detail:\n    path: "/rooms/{id}"\n    embed: [https://www.example.com]\n',
        )
        .replace("  public_pages: [rooms]\n", "  public_pages: [rooms, room_detail]\n")
    )
    definition = load_definition_text(text, str(ROOM_BOOKING))
    assert validate_definition(definition) == []

    [(pattern, ancestors)] = frame_rules(definition)

    assert ancestors == "'self' https://www.example.com"
    # nginx reads the pattern as a PCRE expression: Python reads it the same.
    regex = re.compile(pattern.removeprefix("~"))
    for uri in ("/rooms/42", "/rooms/42/", "/rooms/42?tab=1"):
        assert regex.search(uri), uri
    for uri in ("/rooms", "/rooms/", "/rooms/42/bookings", "/rooms/42x/y", "/other/rooms/42"):
        assert not regex.search(uri), uri


def test_an_app_without_embed_sends_self_only() -> None:
    definition = load_definition(ROOM_BOOKING)
    nextjs = {f.path: f.content for f in generate(definition, find_binding("nextjs")).files}
    react = {f.path: f.content for f in generate(definition, find_binding("react")).files}

    assert "app/(embed)/layout.tsx" not in nextjs
    assert nextjs["next.config.ts"].count("{ source: ") == 1
    assert "src/app/layout/embed-layout.tsx" not in react
    assert "EmbedLayout" not in react["src/app/router.tsx"]
    map_block = react["nginx.conf"].split("map $request_uri $frame_ancestors {", 1)[1]
    assert map_block.split("}", 1)[0] == "\n    default \"'self'\";\n"
