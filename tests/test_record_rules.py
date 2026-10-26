"""The record rules with field conditions and owner paths (ADR 0025, #332, #333, #334)."""

from pathlib import Path

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

FIXTURE = Path(__file__).parent / "fixtures" / "record-rules.yaml"
TEXT = FIXTURE.read_text(encoding="utf-8")
TASK_RULE = """          owner: project.team.members
          where: { status: [open, in_progress] }
"""
TASK = "access.roles.member.records.Task"


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, str(FIXTURE))
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def with_task_rule(rule: str) -> str:
    """Return the fixture with another rule of the members on the tasks."""
    assert TASK_RULE in TEXT
    return TEXT.replace(TASK_RULE, rule)


def files(binding: Binding, text: str = TEXT) -> dict[str, str]:
    definition = load_definition_text(text, str(FIXTURE))
    return {f.path: f.content for f in generate(definition, binding).files}


def test_the_rules_with_conditions_and_paths_are_valid() -> None:
    definition = load_definition(FIXTURE)
    assert validate_definition(definition) == []
    assert definition.access is not None
    rule = definition.access.roles["member"].records["Task"]
    assert rule.owner == "project.team.members"
    assert rule.conditions() == {"status": ["open", "in_progress"]}
    reviewer = definition.access.roles["reviewer"].records["Task"]
    assert reviewer.owner is None
    assert reviewer.conditions() == {"status": ["done"]}


def test_a_rule_needs_an_owner_or_a_condition() -> None:
    assert codes(with_task_rule("          operations: [read]\n")) == [("missing-key", TASK)]


@pytest.mark.parametrize(
    ("where", "code"),
    [
        ("{ state: open }", "unknown-reference"),
        ("{ status: closed }", "invalid-value"),
        ("{ status: [open, 3] }", "invalid-value"),
        ("{ priority: 9 }", "invalid-value"),
        ("{ priority: [2, 2] }", "duplicate-name"),
        ("{ title: 7 }", "invalid-value"),
        ('{ due: "2026-01-01" }', "unsuitable-field"),
        ("{ score: 1 }", "unsuitable-field"),
    ],
)
def test_the_validator_reports_a_condition_that_does_not_suit(where: str, code: str) -> None:
    text = with_task_rule(f"          where: {where}\n").replace(
        "      priority: { type: integer, min: 1, max: 5, default: 3 }\n",
        "      priority: { type: integer, min: 1, max: 5, default: 3 }\n"
        "      due: { type: date }\n"
        "      score: { type: integer, computed: priority * 2 }\n",
    )
    assert codes(text) == [(code, TASK)]


def test_a_condition_has_at_least_one_value() -> None:
    with pytest.raises(DefinitionError):
        load_definition_text(with_task_rule("          where: { status: [] }\n"), "app.yaml")


@pytest.mark.parametrize(
    ("owner", "code"),
    [
        ("project.team.leader", "unknown-reference"),
        ("project.name", "unsuitable-field"),
        ("project.team", "unsuitable-field"),
        ("project.tasks.project.team.members", "unsuitable-field"),
    ],
)
def test_the_validator_reports_an_owner_path_that_does_not_suit(owner: str, code: str) -> None:
    assert codes(with_task_rule(f"          owner: {owner}\n")) == [(code, TASK)]


def test_the_rules_of_an_entity_with_an_owner_use_one_owner() -> None:
    text = TEXT.replace(
        "        Task: { where: { status: done } }\n",
        "        Task: { owner: project.team.members, where: { status: done } }\n",
    )
    assert codes(text) == []
    text = TEXT.replace(
        "        Project: { where: { archived: false } }\n",
        "        Project: { owner: tasks.project.team.members }\n",
    )
    assert ("unsuitable-field", "access.roles.reviewer.records.Project") in codes(text)


def test_the_fastapi_table_has_the_conditions_and_the_owners() -> None:
    access = files(fastapi.BINDING)["app/core/access.py"]
    assert (
        "        # @trace access.roles.member.records.Task\n"
        '        "Task": RecordRule(\n'
        '            actions=frozenset({"change", "read"}),\n'
        "            owner=True,\n"
        '            where={"status": ("open", "in_progress")},\n'
        "        ),\n"
    ) in access
    project = '"Project": RecordRule(actions=frozenset({"change", "read"}), '
    project += 'where={"archived": (False,)}),'
    assert project in access


def test_the_fastapi_repository_filters_by_the_path_with_exists_subqueries() -> None:
    app = files(fastapi.BINDING)
    tasks = app["app/features/tasks/repository.py"]
    assert (
        "    return Task.project.has(Project.team.has(Team.members.any(Person.id == user)))\n"
    ) in tasks
    assert "        statement = statement.where(getattr(Task, name).in_(values))\n" in tasks
    # A create and a change check the record with the same filter.
    assert "    statement = owned(select(Task.id).where(Task.id == record.id), scope)\n" in tasks
    assert '        raise ProblemError(403, "Your role may not give a record these values.")\n' in (
        tasks
    )
    # Only a direct owner is set to the user.
    assert "_owner(" not in tasks
    projects = app["app/features/projects/repository.py"]
    assert "    return Project.team.has(Team.members.any(Person.id == user))\n" in projects


def test_the_fastapi_app_hides_the_embedded_records_of_the_rules() -> None:
    app = files(fastapi.BINDING)
    # The read schema allows a hidden project of a task.
    assert "    project: ProjectRead | None\n" in app["app/features/tasks/schemas.py"]
    tasks = app["app/features/tasks/repository.py"]
    assert "            item.project = None\n" in tasks
    teams = app["app/features/teams/repository.py"]
    assert (
        "        item.projects = [target for target in item.projects if target.id in shown]\n"
    ) in teams
    read_team = app["app/features/teams/read_team.py"]
    assert "    await repository.hide(session, [result], scope)\n" in read_team
    list_teams = app["app/features/teams/list_teams.py"]
    assert "    await repository.hide(session, items, scope)\n" in list_teams
    tests = app["tests/test_access.py"]
    assert "async def test_the_role_reviewer_sees_no_hidden_project_in_the_tasks(" in tests
    assert "async def test_the_role_reviewer_sees_no_hidden_projects_in_the_teams(" in tests


def test_the_fastapi_tests_cover_each_rule() -> None:
    tests = files(fastapi.BINDING)["tests/test_access.py"]
    for role, slice_name in (
        ("member", "projects"),
        ("member", "tasks"),
        ("reviewer", "projects"),
        ("reviewer", "tasks"),
    ):
        assert f"async def test_the_record_rule_limits_the_role_{role}_to_its_{slice_name}(" in (
            tests
        )
    # The owner of a task comes through a many-to-many relation.
    assert "    team = await make_team(session, member_ids=[user_id])\n" in tests


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=lambda b: b.name)
def test_the_table_of_the_permissions_is_the_one_source_of_the_rules(binding: Binding) -> None:
    table = files(binding)["src/shared/lib/permissions.ts"]
    assert (
        '    "Task": { actions: ["change", "read"], owner: true, '
        'where: { status: ["open", "in_progress"] } }, '
        "// @trace access.roles.member.records.Task\n"
    ) in table
    assert (
        '    "Project": { actions: ["change", "read"], where: { archived: [false] } }, '
        "// @trace access.roles.reviewer.records.Project\n"
    ) in table


def test_the_nextjs_repository_follows_the_owner_path() -> None:
    app = files(nextjs.BINDING)
    tasks = app["src/entities/task/api/task-repository.ts"]
    assert "  belongsTo: (user) =>\n    inArray(\n      taskTable.projectId,\n" in tasks
    # The last step is a many-to-many relation: its join table has the user.
    assert ".where(eq(personTeamsTable.personId, user))" in tasks
    assert "  owner:" not in tasks
    projects = app["src/entities/project/api/project-repository.ts"]
    assert "    inArray(\n      projectTable.teamId," in projects
    shared = app["src/shared/db/repository.ts"]
    assert "inArray(this.column(key), [...values])" in shared
    assert "await this.checkScope(tx, String(row.id), options.scope ?? null);" in shared
    assert 'throw new ForbiddenError("Your role may not give a record these values.");' in shared
    actions = app["src/entities/task/api/task-actions.ts"]
    assert ("return taskRepository.create(taskInputSchema.parse(input), { scope });") in actions
    page = app["app/(app-shell)/tasks/[id]/page.tsx"]
    assert 'taskRepository.exists(id, await recordScope("Task", "read"))' in page


def test_the_react_mock_store_follows_the_owner_path() -> None:
    app = files(react.BINDING)
    api = app["src/entities/task/api/task-api.ts"]
    assert (
        "    path: [\n"
        '      { key: "projectId", target: "Project" }, '
        "// @trace entities.Task.relations.project\n"
        '      { key: "teamId", target: "Team" }, // @trace entities.Project.relations.team\n'
        '      { key: "members", target: "Person" }, // @trace entities.Team.relations.members\n'
        "    ],\n"
    ) in api
    # Only an owner of one many-to-one relation gives a new record to the user.
    assert "owner:" not in api
    store = app["src/shared/api/mock-store.ts"]
    assert "return hasValuesOf(scope, record) && (!scope.owner" in store
    assert "throw new RecordRuleError();" in store


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=lambda b: b.name)
def test_the_form_sets_a_condition_with_one_value(binding: Binding) -> None:
    form = files(binding)["src/features/new-task-form/ui/new-task-form.tsx"]
    assert 'const scope = useAccess().scopeOf("Task");' in form
    assert '    status: fixedValue<Values["status"]>(scope, "status") ?? "open",\n' in form
    assert '        {fixedValue(scope, "status") === undefined && (\n' in form
    # An owner path does not hide a field: the user selects the project.
    assert "scope?.owner" not in form
