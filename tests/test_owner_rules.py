"""The owner rules of the roles: `access.roles.*.records.*` and the FastAPI app (ADR 0018)."""

from pathlib import Path
from textwrap import dedent

from appgen.bindings import fastapi
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.gen.generator import generate

EXAMPLE = Path(__file__).parent.parent / "examples" / "room-booking" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Person:
        fields:
          email: { type: email, required: true, unique: true }
          role: { type: enum, values: [admin, member] }
        relations:
          tasks: { kind: one_to_many, target: Task, inverse: assignee }
      Task:
        fields:
          title: { type: string, required: true }
        relations:
          assignee: { kind: many_to_one, target: Person, inverse: tasks }
          reviewer: { kind: many_to_one, target: Person }
          project: { kind: many_to_one, target: Project }
      Project:
        fields:
          name: { type: string, required: true }
    operations:
      list_tasks: { kind: list, entity: Task }
    auth:
      user_entity: Person
      username_field: email
    access:
      role_field: role
      roles:
        admin: { operations: ["*"] }
        member:
          operations: [list_tasks]
          records:
            Task: { owner: assignee }
    """
)


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def test_an_owner_rule_is_valid_and_applies_to_reads_and_changes() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert validate_definition(definition) == []
    assert definition.access is not None
    rule = definition.access.roles["member"].records["Task"]
    assert rule.operations == ["read", "change"]
    assert definition.find("access.roles.member.records.Task") is rule


def test_the_owner_is_a_many_to_one_relation_to_the_user_entity() -> None:
    assert codes(BASE.replace("owner: assignee", "owner: project")) == [
        ("unsuitable-field", "access.roles.member.records.Task")
    ]
    assert codes(BASE.replace("owner: assignee", "owner: author")) == [
        ("unknown-reference", "access.roles.member.records.Task")
    ]
    assert codes(BASE.replace("Task: { owner: assignee }", "Job: { owner: assignee }")) == [
        ("unknown-reference", "access.roles.member.records.Job")
    ]


def test_the_rules_of_an_entity_use_one_relation() -> None:
    text = BASE.replace(
        'admin: { operations: ["*"] }',
        'admin: { operations: ["*"], records: { Task: { owner: reviewer } } }',
    )
    assert codes(text) == [("invalid-value", "access.roles.member.records.Task")]


def test_the_operations_of_a_rule_are_read_and_change() -> None:
    assert (
        codes(BASE.replace("{ owner: assignee }", "{ owner: assignee, operations: [change] }"))
        == []
    )
    assert codes(
        BASE.replace("{ owner: assignee }", "{ owner: assignee, operations: [read, read] }")
    ) == [("duplicate-name", "access.roles.member.records.Task")]


def test_the_fastapi_app_filters_the_records_of_the_owner() -> None:
    definition = load_definition(EXAMPLE)
    files = {f.path: f.content for f in generate(definition, fastapi.BINDING).files}
    access = files["app/core/access.py"]
    assert '        "Booking": frozenset({"change", "read"}),' in access
    assert "def owner_of(entity: str, action: str)" in access
    repository = files["app/features/bookings/repository.py"]
    assert "    return statement.where(Booking.organizer_id == owner)\n" in repository
    assert "    if record is None or (owner is not None and record.organizer_id != owner):\n" in (
        repository
    )
    assert '        values["organizer_id"] = owner\n' in repository
    listing = files["app/features/bookings/list_bookings.py"]
    assert 'Owner = Annotated[UUID | None, Depends(owner_of("Booking", "read"))]' in listing
    assert "    statement = repository.owned(select(Booking), owner)\n" in listing
    update = files["app/features/bookings/update_booking.py"]
    assert 'Depends(owner_of("Booking", "change"))' in update
    custom = files["app/features/bookings/cancel_booking_gen.py"]
    assert "    record = await repository.get(session, id, owner)\n" in custom
    # The rooms have no owner rule: their code does not change.
    assert "owner" not in files["app/features/rooms/repository.py"]
    tests = files["tests/test_access.py"]
    assert "async def test_an_owner_rule_limits_the_role_member_to_its_bookings(" in tests
    assert "async def test_the_role_admin_without_an_owner_rule_sees_all_bookings(" in tests
