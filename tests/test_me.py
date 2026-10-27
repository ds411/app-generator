"""The value `$me`, the signed-in user (M36): the DSL, the checks, and the apps."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition, load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "courses.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: desk, title: Desk }
    entities:
      User:
        fields:
          email: { type: email, required: true, unique: true }
          name: { type: string }
      Team:
        fields:
          name: { type: string }
      Ticket:
        crud: { views: [table], forms: [create] }
        fields:
          title: { type: string, required: true }
          rank: { type: integer }
        relations:
          agent: { kind: many_to_one, target: User }
          watchers: { kind: many_to_many, target: User }
          team: { kind: many_to_one, target: Team }
      Queue:
        fields:
          name: { type: string }
          mine: { type: integer, computed: count(tickets), filter: { agent: {total} } }
        relations:
          tickets: { kind: one_to_many, target: Ticket, inverse: queue }
    ui:
      views:
        my_tickets:
          kind: table
          entity: Ticket
          columns: { title: {}, agent: {} }
          filters:
            agent: { kind: select, field: {select}, default: $me }
            watchers: { kind: select, field: watchers, multiple: true, default: [$me] }
      forms:
        new_ticket:
          entity: Ticket
          operation: create_ticket
          fields: { title: {}, agent: {}, watchers: {} }
          defaults: { {default}: $me, watchers: $me }
      dashboards:
        home:
          widgets:
            mine: { kind: stat, entity: Ticket, filter: { {widget}: $me } }
            others: { kind: stat, entity: Ticket, filter: { agent: { ne: $me } } }
    auth:
      user_entity: User
      username_field: email
    """
)


def definition_text(
    *,
    select: str = "agent",
    default: str = "agent",
    widget: str = "agent",
    total: str = "$me",
    auth: bool = True,
) -> str:
    """Return the base definition with the targets of `$me`, with or without `auth`."""
    text = BASE.replace("{select}", select).replace("{default}", default)
    text = text.replace("{widget}", widget).replace("{total}", total)
    # The relation to the queue of the tickets.
    text = text.replace(
        "team: { kind: many_to_one, target: Team }",
        "team: { kind: many_to_one, target: Team }\n"
        "      queue: { kind: many_to_one, target: Queue, inverse: tickets }",
    )
    return text if auth else text[: text.index("auth:")]


def diagnostics(text: str) -> list[tuple[str, str | None, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_me_is_valid_in_the_filters_the_totals_and_the_defaults() -> None:
    assert diagnostics(definition_text()) == []


def test_me_needs_the_section_auth() -> None:
    found = diagnostics(definition_text(auth=False))
    missing = [
        (code, element) for code, element, message in found if "no section 'auth'" in message
    ]
    assert sorted(missing) == [
        ("invalid-value", "entities.Queue.fields.mine"),
        ("invalid-value", "ui.dashboards.home.widgets.mine"),
        ("invalid-value", "ui.dashboards.home.widgets.others"),
        ("invalid-value", "ui.forms.new_ticket"),
        ("invalid-value", "ui.forms.new_ticket"),
        ("invalid-value", "ui.views.my_tickets.filters.agent"),
        ("invalid-value", "ui.views.my_tickets.filters.watchers"),
    ]


@pytest.mark.parametrize(
    ("option", "path", "element", "what"),
    [
        ("select", "title", "ui.views.my_tickets.filters.agent", "a field of the type 'string'"),
        ("select", "team", "ui.views.my_tickets.filters.agent", "a relation to 'Team'"),
        ("default", "title", "ui.forms.new_ticket", "a field of the type 'string'"),
        ("widget", "team", "ui.dashboards.home.widgets.mine", "a relation to 'Team'"),
    ],
)
def test_me_needs_a_relation_to_the_user_entity(
    option: str, path: str, element: str, what: str
) -> None:
    targets = {"select": "agent", "default": "agent", "widget": "agent", option: path}
    text = definition_text(
        select=targets["select"], default=targets["default"], widget=targets["widget"]
    )
    found = [(c, e, m) for c, e, m in diagnostics(text) if "$me" in m]
    assert ("unsuitable-field", element) in [(c, e) for c, e, _ in found]
    assert any(what in m for _, _, m in found)


def test_a_total_takes_me_only_for_a_relation_to_the_user_entity() -> None:
    text = definition_text().replace("filter: { agent: $me } }", "filter: { team: $me } }")
    found = diagnostics(text)
    assert ("unsuitable-field", "entities.Queue.fields.mine") in [(c, e) for c, e, _ in found]


def test_a_job_has_no_signed_in_user() -> None:
    text = definition_text() + dedent(
        """\
        jobs:
          close_tickets:
            schedule: "0 3 * * *"
            entity: Ticket
            filter: { agent: $me }
            operation: close_ticket
        operations:
          close_ticket: { kind: custom, entity: Ticket }
        """
    )
    found = diagnostics(text)
    assert any("no signed-in user" in m for _, _, m in found), found


def test_the_fixture_is_valid() -> None:
    assert validate_definition(load_definition(FIXTURE)) == []


def test_the_fastapi_app_reads_the_user_of_each_request() -> None:
    files = files_of(definition_text(), fastapi.BINDING)
    db = files["app/core/db.py"]
    assert 'SIGNED_IN: ContextVar[UUID | None] = ContextVar("signed_in", default=None)' in db
    assert 'return bindparam("me", type_=Uuid(), callable_=SIGNED_IN.get, unique=True)' in db
    auth = files["app/core/auth.py"]
    assert "async def remember_user(request: Request) -> None:" in auth
    # A request without a token has no user: the value of the request before does not stay.
    assert (
        "SIGNED_IN.set(read_token(signing_key(request), token.strip()) if bearer else None)" in auth
    )
    assert "dependencies=[Depends(remember_user)]" in files["app/main.py"]
    models = files["app/models.py"]
    assert "Ticket.agent_id == me()" in models
    dashboard = next(c for p, c in files.items() if p.endswith("dashboards/home.py"))
    assert "Ticket.agent_id == me()" in dashboard
    # Without a user, all records pass `ne`.
    assert "or_(Ticket.agent_id.is_(None), Ticket.agent_id.is_distinct_from(me()))" in dashboard


def test_the_fastapi_app_tests_the_values_of_two_users() -> None:
    files = files_of(FIXTURE.read_text(), fastapi.BINDING)
    tests = files["tests/test_me.py"]
    assert "async def test_lesson_my_submissions_counts_the_records_of_the_user(" in tests
    assert "async def test_home_my_submissions_counts_the_records_of_the_user(" in tests
    assert "for headers, expected in ((first_headers, 2), (second_headers, 1), ({}, 0)):" in tests


def test_an_app_without_me_has_no_user_of_the_request() -> None:
    files = files_of(definition_text().replace("$me", "null"), fastapi.BINDING)
    assert "remember_user" not in files["app/main.py"]
    assert "SIGNED_IN" not in files["app/core/db.py"]
    assert "tests/test_me.py" not in files


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_the_front_ends_start_with_the_values_of_the_user(binding: Binding) -> None:
    files = files_of(definition_text(), binding)
    assert any(p.startswith("src/shared/lib/me.ts") for p in files)
    view = files["src/widgets/my-tickets/ui/my-tickets-view.tsx"]
    assert "function initialFilters(me: string | null): Filters {" in view
    assert "    agent: me, // @trace ui.views.my_tickets.filters.agent" in view
    assert "    watchers: me === null ? [] : [me], // @trace" in view
    assert "  const initial = initialFilters(useMe());" in view
    assert "useState<Filters>(initial)" in view
    form = files["src/features/new-ticket-form/ui/new-ticket-form.tsx"]
    assert "    agentId: me ?? null," in form
    assert "    watchers: me === null ? [] : [me]," in form
    assert "  const me = useMe();" in form
    dashboard = files["src/widgets/home/ui/home-dashboard.tsx"]
    assert "function mine(data: DashboardData, me: string | null): number | null {" in dashboard
    assert 'matchesOp(row.agentId ?? null, "eq", me ?? "")' in dashboard
    assert "value={formatValue(mine(data, me)" in dashboard


def test_the_nextjs_layout_gives_the_user_to_the_pages() -> None:
    files = files_of(definition_text(), nextjs.BINDING)
    layout = files["app/layout.tsx"]
    assert "export default async function RootLayout(" in layout
    assert "<MeProvider me={userId}>{children}</MeProvider>" in layout
    assert "export function useMe(): string | null {" in files["src/shared/lib/me.tsx"]


def test_the_nextjs_repository_reads_the_totals_of_the_user_of_the_request() -> None:
    files = files_of(definition_text(), nextjs.BINDING)
    repository = files["src/entities/queue/api/queue-repository.ts"]
    assert "  me: requestUserId," in repository
    assert "  totals: (record, me) => ({" in repository
    assert "me === null ? sql`false` : eq(ticketTable.agentId, me)," in repository
    assert 'import { eq, sql } from "drizzle-orm";' in repository
    session = files["src/shared/auth/session.ts"]
    assert "export async function requestUserId(): Promise<string | null> {" in session
    shared = files["src/shared/db/repository.ts"]
    assert "const me = (await this.me?.()) ?? null;" in shared


def test_the_react_mock_store_reads_the_user_at_each_read() -> None:
    files = files_of(definition_text(), react.BINDING)
    api = files["src/entities/queue/api/queue-api.ts"]
    assert '["agentId", "eq", () => currentUserId() ?? ""],' in api
    store = files["src/shared/api/mock-store.ts"]
    assert 'typeof operand === "function" ? (operand as () => unknown)() : operand' in store


def test_the_react_app_with_the_fastapi_app_sends_the_token() -> None:
    text = definition_text().replace(
        "app: { name: desk, title: Desk }", "app: { name: desk, title: Desk, x-react-data: api }"
    )
    files = files_of(text, react.BINDING)
    dashboard = files["src/widgets/home/ui/home-dashboard.tsx"]
    # The FastAPI app counts the records of the user of the token.
    assert "me: string | null" not in dashboard
    assert "useMe" not in dashboard
