"""The change log of the records in the front ends: the history tab and the restore (ADR 0040)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import nextjs, react
from appgen.dsl import DefinitionError, load_definition, load_definition_text, validate_definition
from appgen.dsl.ui.views import DetailView
from appgen.gen.binding import Binding
from appgen.gen.generator import generate

ROOT = Path(__file__).parent.parent
ROOM_BOOKING = ROOT / "examples" / "room-booking" / "app.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    storage: { kind: local }
    entities:
      Task:
        crud: { views: [table, detail], forms: [create, update] }
        history: true
        fields:
          title: { type: string, required: true }
          points: { type: integer, min: 0, max: 100 }
          score: { type: integer, computed: points * 2 }
          due_on: { type: date }
          scan: { type: file }
        relations:
          project: { kind: many_to_one, target: Project }
      Project:
        crud: { views: [table, detail], forms: [create, update] }
        fields:
          name: { type: string, required: true }
        relations:
          tasks: { kind: one_to_many, target: Task, inverse: project }
    pages:
      task: { path: "/tasks/{id}", title: Task, entity: Task, content: { view: task_detail } }
      project:
        path: "/projects/{id}"
        title: Project
        entity: Project
        content: { view: project_detail }
    """
)

TAB = dedent(
    """\
    ui:
      views:
        project_detail:
          kind: detail
          entity: Project
          sections:
            about: { fields: [name] }
          tabs:
            log: { label: Log, history: true }
    """
)


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_the_crud_detail_view_of_an_entity_with_history_has_a_history_tab() -> None:
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.ui is not None
    task = definition.ui.views["task_detail"]
    project = definition.ui.views["project_detail"]
    assert isinstance(task, DetailView) and isinstance(project, DetailView)
    assert list(task.tabs) == ["history"]
    assert task.tabs["history"].history is True
    assert project.tabs == {}
    assert validate_definition(definition) == []


def test_a_history_tab_needs_the_change_log_of_its_entity() -> None:
    definition = load_definition_text(BASE + TAB, "app.yaml")
    [diagnostic] = validate_definition(definition)
    assert diagnostic.code == "invalid-option"
    assert diagnostic.element_id == "ui.views.project_detail.tabs.log"
    assert "Add 'history: true' to the entity 'Project'." in (diagnostic.hint or "")

    kept = "    history: true\n    fields:\n      name:"
    text = BASE.replace("    fields:\n      name:", kept)
    assert validate_definition(load_definition_text(text + TAB, "app.yaml")) == []


def test_a_history_tab_has_no_other_content() -> None:
    text = BASE + TAB.replace("history: true }", "history: true, custom: true }")
    with pytest.raises(DefinitionError) as caught:
        load_definition_text(text, "app.yaml")
    [diagnostic] = caught.value.diagnostics
    assert "history: true" in diagnostic.message
    assert diagnostic.element_id == "ui.views.project_detail.tabs.log"


def test_the_nextjs_app_keeps_the_change_log_in_its_server_actions() -> None:
    files = files_of(BASE, nextjs.BINDING)
    schema = files["src/shared/db/schema/history-entries.ts"]
    assert 'pgTable(\n  "history_entries",' in schema
    assert 'export * from "./history-entries";' in files["src/shared/db/schema/index.ts"]
    assert "export async function addEntry(" in files["src/shared/db/history.ts"]
    repository = files["src/entities/task/api/task-repository.ts"]
    assert '["title", "title"],' in repository
    assert '["due_on", "dueOn"],' in repository
    assert '["project", "projectId"],' in repository
    assert '"score"' not in repository and '"scan"' not in repository
    assert "history: taskHistoryMembers," in repository
    shared = files["src/shared/db/repository.ts"]
    assert 'await this.log(tx, String(row.id), "created", undefined);' in shared
    assert 'await this.log(tx, id, "deleted", rows[0]);' in shared
    actions = files["src/entities/task/api/task-actions.ts"]
    assert "export async function listTaskHistoryAction(" in actions
    assert "export async function restoreTaskHistoryEntryAction(" in actions
    assert 'taskRepository.update(record.id, patch, "restored")' in actions
    api = files["src/entities/task/api/task-api.ts"]
    assert 'export const taskHistory: HistoryApi<Task> = createHistoryApi("Task", {' in api
    assert "listProjectHistoryAction" not in files["src/entities/project/api/project-actions.ts"]


def test_the_detail_view_shows_the_entries_with_their_labels_and_a_restore() -> None:
    files = files_of(BASE, nextjs.BINDING)
    view = files["src/widgets/task-detail/ui/task-detail-view.tsx"]
    assert 'import { projectApi, taskApi, taskHistory, type Task } from "@/entities/' not in view
    assert "taskHistory" in view.split('from "@/entities/task";')[0].splitlines()[-1]
    assert 'due_on: { label: "Due on", format: "date" },' in view
    assert 'project: { label: "Project" },' in view
    assert "const item = await projectApi.get(id);" in view
    assert '            restore="update_task"\n' in view
    assert "export function HistoryList<" in files["src/shared/ui/history-list.tsx"]


def test_an_app_without_history_has_no_change_log() -> None:
    text = BASE.replace("    history: true\n", "", 1)
    for binding in (nextjs.BINDING, react.BINDING):
        files = files_of(text, binding)
        assert "src/shared/ui/history-list.tsx" not in files
        assert "src/shared/db/history.ts" not in files
        assert "HistoryApi" not in files["src/shared/api/types.ts"]


def test_the_react_mock_store_keeps_the_entries_in_memory() -> None:
    files = files_of(BASE, react.BINDING)
    api = files["src/entities/task/api/task-api.ts"]
    assert "export const taskHistory: HistoryApi<Task> = taskApi.history(" in api
    assert '    ["due_on", "dueOn"],\n' in api
    assert "export const taskApi = new MockStore" in api
    store = files["src/shared/api/mock-store.ts"]
    assert "  history(\n    members: readonly HistoryMember[]," in store
    assert 'this.log(id, "deleted", record, undefined);' in store
    assert 'return this.update(id, patch as Partial<TInput>, "restored");' in store
    assert "taskHistory" in files["src/widgets/task-detail/ui/task-detail-view.tsx"]


def test_the_react_app_with_the_fastapi_app_reads_the_history_endpoints() -> None:
    text = BASE.replace("title: Tracker }", "title: Tracker, x-react-data: api }", 1)
    files = files_of(text, react.BINDING)
    store = files["src/shared/api/http-store.ts"]
    assert '"/history", query' in store
    assert "/history/${encodeURIComponent(entryId)}/restore" in store
    api = files["src/entities/task/api/task-api.ts"]
    assert "export const taskHistory: HistoryApi<Task> = taskApi.history();" in api


def test_the_room_booking_apps_keep_the_user_and_check_the_access() -> None:
    definition = load_definition(ROOM_BOOKING)
    files = {f.path: f.content for f in generate(definition, react.BINDING).files}
    api = files["src/entities/booking/api/booking-api.ts"]
    assert "  { current: currentUserId, label: userLabel },\n" in api
    assert '    list: () => requireOperation("read_booking"),\n' in api
    assert '    restore: () => requireOperation("update_booking"),\n' in api
    auth = files["src/shared/auth/index.ts"]
    assert "export function userLabel(id: string): string | null {" in auth
    assert "const { canCall } = useAccess();" in files["src/shared/ui/history-list.tsx"]
    files = {f.path: f.content for f in generate(definition, nextjs.BINDING).files}
    assert (
        "const data = await asUser(await sessionUserId(), body);"
        in files["src/shared/api/server.ts"]
    )
    assert "inArray(memberTable.id, ids)" in files["src/shared/db/history.ts"]


def test_the_front_ends_cover_the_change_log() -> None:
    for binding in (nextjs.BINDING, react.BINDING):
        assert "history" in binding.covers
        assert "history" not in binding.excludes
