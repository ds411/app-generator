"""The front ends apply the owner rules (ADR 0018, #273)."""

from pathlib import Path

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import load_definition_text
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
EXAMPLE = (ROOT / "examples" / "room-booking" / "app.yaml").read_text(encoding="utf-8")
FRONT_ENDS = [nextjs.BINDING, react.BINDING]
OWNER_TRACE = "// @trace entities.Booking.relations.organizer"


def files(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, str(ROOT / "examples" / "room-booking" / "app.yaml"))
    return {f.path: f.content for f in generate(definition, binding).files}


def with_api(text: str) -> str:
    """Return the example with the data of the FastAPI app in the React app."""
    return text.replace("  name: room-booking\n", "  name: room-booking\n  x-react-data: api\n", 1)


def without_rules(text: str) -> str:
    """Return the example without its owner rule."""
    rule = "      records:\n        Booking: { owner: organizer }\n"
    assert rule in text
    return text.replace(rule, "")


@pytest.mark.parametrize("binding", FRONT_ENDS, ids=lambda b: b.name)
def test_the_table_of_the_permissions_has_the_owner_rules(binding: Binding) -> None:
    table = files(EXAMPLE, binding)["src/shared/lib/permissions.ts"]

    assert (
        '  "member": {\n'
        '    "Booking": ["change", "read"], // @trace access.roles.member.records.Booking\n'
        "  },\n"
    ) in table
    assert (
        "export function ownerRuleApplies(role: string | null, entity: string, "
        "action: RecordAction): boolean {"
    ) in table


def test_the_nextjs_actions_use_only_the_records_of_the_user() -> None:
    app = files(EXAMPLE, nextjs.BINDING)

    actions = app["src/entities/booking/api/booking-actions.ts"]
    owner = 'await recordOwner("Booking", "read")'
    assert f"bookingRepository.list(parseListQuery<Booking>(query), {owner})" in actions
    assert f"bookingRepository.get(idSchema.parse(id), {owner})" in actions
    # A create and a change give the record to the user.
    assert "const values = owner === null ? input : { ...input, organizerId: owner };" in actions
    assert (
        "bookingRepository.update(idSchema.parse(id), bookingPatchSchema.parse(values), owner)"
        in actions
    )
    assert (
        'bookingRepository.remove(idSchema.parse(id), await recordOwner("Booking", "change"))'
        in actions
    )
    assert OWNER_TRACE in actions
    # An entity without a rule has the actions without an owner.
    assert "recordOwner" not in app["src/entities/room/api/room-actions.ts"]

    repository = app["src/entities/booking/api/booking-repository.ts"]
    assert f'  owner: "organizerId", {OWNER_TRACE}\n' in repository
    shared = app["src/shared/db/repository.ts"]
    assert "const where = and(this.where(query), this.owned(owner));" in shared
    assert "return and(eq(this.table.id, id), this.owned(owner));" in shared

    access = app["src/shared/auth/access.ts"]
    assert (
        "export async function recordOwner(entity: string, action: RecordAction): "
        "Promise<string | null> {"
    ) in access


def test_a_nextjs_record_of_another_user_does_not_exist() -> None:
    app = files(EXAMPLE, nextjs.BINDING)

    page = app["app/(app-shell)/bookings/[id]/page.tsx"]
    assert 'bookingRepository.exists(id, await recordOwner("Booking", "read"))' in page
    operation = app["src/features/cancel-booking/api/cancel-booking.gen.ts"]
    assert (
        'bookingRepository.get(idSchema.parse(id), await recordOwner("Booking", "change"))'
        in operation
    )
    layout = app["app/layout.tsx"]
    assert "const userId = await sessionUserId();" in layout
    assert "<AccessProvider role={role} userId={userId}>" in layout


def test_the_react_mock_store_uses_only_the_records_of_the_user() -> None:
    app = files(EXAMPLE, react.BINDING)

    api = app["src/entities/booking/api/booking-api.ts"]
    assert (
        '  { key: "organizerId", ownerOf: (action) => recordOwner("Booking", action) }, '
        f"{OWNER_TRACE}\n"
    ) in api
    assert "recordOwner" not in app["src/entities/room/api/room-api.ts"]
    store = app["src/shared/api/mock-store.ts"]
    assert 'this.records.filter((record) => this.owns(record, "read"))' in store
    assert "if (!record || !this.owns(record, action)) {" in store
    assert "...this.ownerValues(), id: crypto.randomUUID()" in store
    auth = app["src/shared/auth/index.ts"]
    assert (
        "export function recordOwner(entity: string, action: RecordAction): string | null {" in auth
    )


def test_the_react_app_with_the_api_leaves_the_records_to_the_api() -> None:
    app = files(with_api(EXAMPLE), react.BINDING)

    assert "recordOwner" not in app["src/entities/booking/api/booking-api.ts"]
    assert "recordOwner" not in app["src/shared/auth/index.ts"]
    assert "src/shared/api/mock-store.ts" not in app
    # The form hides the owner all the same.
    form = app["src/features/new-booking-form/ui/new-booking-form.tsx"]
    assert 'const owner = useAccess().ownerOf("Booking");' in form


@pytest.mark.parametrize("binding", FRONT_ENDS, ids=lambda b: b.name)
def test_the_form_hides_the_owner_from_a_user_of_the_rule(binding: Binding) -> None:
    app = files(EXAMPLE, binding)

    form = app["src/features/new-booking-form/ui/new-booking-form.tsx"]
    assert 'import { useAccess } from "@/shared/lib/access";' in form
    assert 'const owner = useAccess().ownerOf("Booking");' in form
    assert "initialValues(undefined, routeParams, owner)" in form
    assert "    organizerId: owner,\n" in form
    assert (
        "        {owner === null && (\n          <Field data-invalid={Boolean(errors.organizerId)}>"
    ) in form
    access = app["src/shared/lib/" + ("access.tsx" if binding is nextjs.BINDING else "access.ts")]
    assert 'ownerRuleApplies(role, entity, "change") ? userId : null' in access
    # A form of another entity has no owner.
    assert "useAccess" not in app["src/features/new-room-form/ui/new-room-form.tsx"]


@pytest.mark.parametrize("binding", FRONT_ENDS, ids=lambda b: b.name)
def test_an_app_without_owner_rules_has_no_owner_code(binding: Binding) -> None:
    app = files(without_rules(EXAMPLE), binding)

    names = ("recordOwner", "ownerOf", "ownerRuleApplies", "OWNER_RULES", "ownerColumn")
    assert [path for path, text in app.items() if any(n in text for n in names)] == []
