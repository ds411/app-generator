"""The front ends show only what the role of the user allows (ADR 0012, #274)."""

from pathlib import Path

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import load_definition
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "room-booking" / "app.yaml"
NO_ACCESS = ROOT / "examples" / "project-tracker" / "app.yaml"
FRONT_ENDS = [nextjs.BINDING, react.BINDING]


def files(path: Path, binding: Binding) -> dict[str, str]:
    return {f.path: f.content for f in generate(load_definition(path), binding).files}


@pytest.mark.parametrize("binding", FRONT_ENDS, ids=lambda b: b.name)
def test_one_table_has_the_permissions_of_the_roles(binding: Binding) -> None:
    app = files(EXAMPLE, binding)
    table = app["src/shared/lib/permissions.ts"]
    assert '  "admin": ["*"], // @trace access.roles.admin\n' in table
    # The pages have their names of the UI code.
    assert '"roomDetail", "bookings", "bookingCalendar", "bookingDetail", "amenities"]' in table
    assert 'const PUBLIC_PAGES: readonly PageName[] = ["rooms"];' in table
    assert 'const PUBLIC_OPERATIONS: readonly string[] = ["list_rooms"];' in table
    assert "export function roleMayOpenPage(role: string | null, page: PageName)" in table
    assert "const { canOpenPage } = useAccess();" in app["src/shared/lib/router.tsx"]


def test_the_nextjs_root_layout_gives_the_role_to_the_ui() -> None:
    app = files(EXAMPLE, nextjs.BINDING)
    layout = app["app/layout.tsx"]
    assert "export default async function RootLayout(" in layout
    assert "const role = await currentRole();" in layout
    # The example has an owner rule: the forms need the ID of the user too.
    assert "<AccessProvider role={role} userId={userId}>" in layout
    access = app["src/shared/auth/access.ts"]
    assert "if (!roleMayCall(role, operation)) {" in access
    assert "export async function currentRole(): Promise<string | null> {" in access
    assert (
        'await requirePage("roomDetail", "/rooms/{id}", await params);'
        in app["app/(app-shell)/rooms/[id]/page.tsx"]
    )
    assert '"use client";' in app["src/shared/lib/access.tsx"]
    assert '"use client";' not in app["src/shared/lib/permissions.ts"]


def test_the_react_app_reads_the_role_of_the_session() -> None:
    app = files(EXAMPLE, react.BINDING)
    auth = app["src/shared/auth/index.ts"]
    assert "export function currentRole(): string | null {" in auth
    assert "return roleMayOpenPage(currentRole(), page);" in auth
    assert "const role = currentRole();" in app["src/shared/lib/access.ts"]
    assert '<RequireAuth page="roomDetail">' in app["src/app/router.tsx"]


@pytest.mark.parametrize("binding", FRONT_ENDS, ids=lambda b: b.name)
def test_the_menu_and_the_actions_show_only_what_the_role_allows(binding: Binding) -> None:
    app = files(EXAMPLE, binding)
    menu = app["src/widgets/navigation/ui/main-menu.tsx"]
    # A group of items shows only if the role may open one of its pages.
    assert '      {(canOpenPage("dashboard") || canOpenPage("bookings") ||' in menu
    assert '            {canOpenPage("members") && (\n' in menu
    actions = app["src/shared/ui/actions.tsx"]
    assert "const shown = actions.filter(allowed);" in actions
    assert "if (!allowed(action)) return null;" in actions
    page_actions = app["src/widgets/page-actions/ui/rooms-actions.tsx"]
    assert '    operation: "create_room",\n' in page_actions
    board = app["src/widgets/booking-board/ui/booking-board-view.tsx"]
    assert 'const canMove = useAccess().canCall("update_booking");' in board
    assert "draggable={canMove}" in board
    # The link of the not-found page always shows.
    assert '<Link href="/" always>' in app["src/pages/not-found/ui/not-found-page.tsx"]


@pytest.mark.parametrize("binding", FRONT_ENDS, ids=lambda b: b.name)
def test_an_app_without_access_has_no_checks_in_the_ui(binding: Binding) -> None:
    app = files(NO_ACCESS, binding)
    assert "src/shared/lib/permissions.ts" not in app
    assert not [path for path, content in app.items() if "useAccess" in content]
    assert "export function Link(props: LinkProps) {" in app["src/shared/lib/router.tsx"] or (
        "export function Link({ href, ...props }: LinkProps) {" in app["src/shared/lib/router.tsx"]
    )
