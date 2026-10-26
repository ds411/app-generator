"""The manual order of a table and a board (ADR 0039): the checks, the code of the front
ends, and the sort key of the FastAPI list endpoint."""

from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate

BASE = dedent(
    """\
    version: 0
    app: { name: plans, title: Plans }
    entities:
      Step:
        display_field: title
        crud: { forms: [create] }
        fields:
          title: { type: string, required: true }
          stage: { type: enum, values: [todo, done], default: todo }
          rank: { type: integer, min: 0 }
    ui:
      views:
        step_table:
          kind: table
          entity: Step
          columns: { title: {}, rank: {} }
          order_field: rank
        step_board:
          kind: board
          entity: Step
          group_by: stage
          order_field: rank
    pages:
      steps: { path: /steps, title: Steps, content: { view: step_table } }
      board: { path: /board, title: Board, content: { view: step_board } }
    """
)
API = BASE.replace("title: Plans }", "title: Plans, x-react-data: api }")
TABLE = "src/widgets/step-table/ui/step-table-view.tsx"
BOARD = "src/widgets/step-board/ui/step-board-view.tsx"


def codes(text: str) -> list[tuple[str, str | None, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id, d.message) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_table_and_a_board_take_an_order_field() -> None:
    assert codes(BASE) == []


@pytest.mark.parametrize(
    ("old", "new", "code", "words"),
    [
        (
            "order_field: rank\n    step_board",
            "order_field: ranks\n    step_board",
            "unknown-reference",
            "ranks",
        ),
        (
            "order_field: rank\n    step_board",
            "order_field: title\n    step_board",
            "unsuitable-field",
            "integer",
        ),
        (
            "rank: { type: integer, min: 0 }",
            "rank: { type: integer, min: 2 }",
            "unsuitable-field",
            "'min'",
        ),
        (
            "rank: { type: integer, min: 0 }",
            "rank: { type: integer, unique: true }",
            "unsuitable-field",
            "'unique'",
        ),
        (
            "rank: { type: integer, min: 0 }",
            "rank: { type: integer, max: 99 }",
            "unsuitable-field",
            "'max'",
        ),
        (
            "rank: { type: integer, min: 0 }",
            "rank: { type: integer, sequence: {} }",
            "unsuitable-field",
            "'sequence'",
        ),
    ],
)
def test_the_checks_of_an_order_field(old: str, new: str, code: str, words: str) -> None:
    found = codes(BASE.replace(old, new, 1))
    assert code in [c for c, _, _ in found]
    assert any(words in (message or "") for _, _, message in found)


def test_an_order_field_takes_no_sort_and_needs_an_update_operation() -> None:
    text = BASE.replace(
        "order_field: rank\n    step_board",
        "order_field: rank\n      sort: { field: title }\n    step_board",
    )
    assert [(c, e) for c, e, _ in codes(text)] == [("invalid-option", "ui.views.step_table")]
    # A list and a read operation only: no update.
    text = BASE.replace("crud: { forms: [create] }", "crud: [list, read]")
    found = [(c, e) for c, e, _ in codes(text)]
    assert ("invalid-option", "ui.views.step_table") in found
    assert ("invalid-option", "ui.views.step_board") in found


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_a_table_moves_its_rows(binding: Binding) -> None:
    files = files_of(BASE, binding)
    table = files[TABLE]
    assert 'import { orderChanges, placeItem, writeOrder } from "@/shared/lib/order";' in table
    assert "return sortBy(rows, (row) => row.rank);" in table
    assert "const list = rows;" in table
    assert (
        "const order = placeItem(list, record, overId)"
        ".map((row) => ({ id: row.id, value: row.rank }));"
    ) in table
    assert (
        "await writeOrder(orderChanges(order, id), "
        "(change) => stepApi.update(change.id, { rank: change.value }));"
    ) in table
    assert "onMove={(id, overId) => void move(id, overId)}" in table
    data_table = files["src/shared/ui/data-table.tsx"]
    assert (
        "const movable = onMove !== undefined && (server ? server.sorting : sorting).length === 0;"
        in data_table
    )
    assert 'aria-label="Move the row"' in data_table
    order = files["src/shared/lib/order.ts"]
    assert (
        "export function orderChanges(list: readonly OrderItem[], id: string): OrderChange[] {"
        in order
    )
    assert "const STEP = 1024;" in order


@pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])
def test_a_board_moves_its_cards_in_their_column(binding: Binding) -> None:
    board = files_of(BASE, binding)[BOARD]
    assert (
        "const move = async (record: Step, value: string, overId: string | null = null) => {"
        in board
    )
    assert "if (record.stage !== value) await moveRecord(record, value);" in board
    assert "const list = rows.filter((row) => row.stage === value);" in board
    assert "drop(column.value, row.id);" in board
    assert "return sortBy(rows, (row) => row.rank);" in board


def test_without_an_order_field_the_views_do_not_move_rows() -> None:
    text = BASE.replace("      order_field: rank\n", "")
    assert codes(text) == []
    files = files_of(text, react.BINDING)
    assert "src/shared/lib/order.ts" not in files
    assert "onMove" not in files["src/shared/ui/data-table.tsx"]
    assert "overCard" not in files[BOARD]


def test_with_the_api_a_move_loads_all_records_of_the_view() -> None:
    files = files_of(API, react.BINDING)
    table = files[TABLE]
    assert 'const VIEW_SORT: string[] = ["rank"];' in table
    assert "const list = await stepApi.all(query.params ?? {}, VIEW_SORT);" in table
    board = files[BOARD]
    assert 'const list = await stepApi.all({ ...params, "stage": value }, VIEW_SORT);' in board
    # The cards of the board do not read related records.
    assert "const { columns } = resource.data;" in board


def test_the_list_endpoint_sorts_by_the_order_field() -> None:
    text = BASE.replace("columns: { title: {}, rank: {} }", "columns: { title: {} }")
    code = files_of(text, fastapi.BINDING)["app/features/steps/list_steps.py"]
    assert '    "rank": Step.rank,\n' in code


ACCESS = dedent(
    """\
    auth: { user_entity: Member, username_field: email }
    access:
      role_field: role
      roles:
        viewer: { operations: [list_steps], pages: ["*"] }
        editor: { operations: ["*"], pages: ["*"] }
    """
)
MEMBER = (
    "  Member:\n"
    "    fields:\n"
    "      email: { type: email, required: true, unique: true }\n"
    "      role: { type: enum, values: [viewer, editor] }\n"
)


def test_a_role_that_may_not_update_cannot_move() -> None:
    text = BASE.replace("entities:\n", "entities:\n" + MEMBER, 1) + ACCESS
    assert codes(text) == []
    files = files_of(text, react.BINDING)
    table = files[TABLE]
    assert 'const canMove = useAccess().canCall("update_step");' in table
    assert "onMove={canMove ? (id, overId) => void move(id, overId) : undefined}" in table
    assert 'const canMove = useAccess().canCall("update_step");' in files[BOARD]
