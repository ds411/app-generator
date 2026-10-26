"""The notices of the front ends: the data access and the bell of the top bar (ADR 0041)."""

import re
import sys
from pathlib import Path

import pytest

from appgen.bindings import nextjs, react
from appgen.bindings.shared.i18n import app_texts
from appgen.bindings.shared.notices import notice_links
from appgen.dsl import load_definition, load_definition_text
from appgen.gen.binding import Binding
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

sys.path.insert(0, str(Path(__file__).parent))
from test_notifications import BASE

ROOT = Path(__file__).parent.parent
ROOM_BOOKING = ROOT / "examples" / "room-booking" / "app.yaml"
RECORD_RULES = ROOT / "tests" / "fixtures" / "record-rules.yaml"
BOTH = pytest.mark.parametrize("binding", [nextjs.BINDING, react.BINDING], ids=["nextjs", "react"])


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def example_files(path: Path, binding: Binding) -> dict[str, str]:
    return {f.path: f.content for f in generate(load_definition(path), binding).files}


def test_the_nextjs_repository_adds_the_notices_in_the_transaction() -> None:
    files = files_of(BASE, nextjs.BINDING)
    schema = files["src/shared/db/schema/notices.ts"]
    assert '"notices",' in schema
    assert 'userId: uuid("user_id")' in schema
    assert '.references(() => personTable.id, { onDelete: "cascade" })' in schema
    assert 'export * from "./notices";' in files["src/shared/db/schema/index.ts"]
    repository = files["src/entities/task/api/task-repository.ts"]
    assert (
        "const projectTeamMembersPath: PathStep[] = [\n"
        "  [taskTable, taskTable.id, taskTable.projectId],\n"
        "  [projectTable, projectTable.id, projectTable.teamId],\n"
        "  [personTeamsTable, personTeamsTable.teamId, personTeamsTable.personId],\n"
        "];"
    ) in repository
    assert 'if (changed(row, before, ["assigneeId"])) {' in repository
    assert "const users = [row.assigneeId];" in repository
    assert (
        "project: await recordText(tx, projectTable, projectTable.id, projectTable.name, "
        "row.projectId),"
    ) in repository
    assert "const users = await pathUsers(tx, id, projectTeamMembersPath);" in repository
    assert (
        'if (before !== undefined && row.status === "done" && before.status === "open") {'
    ) in repository
    assert (
        "const users = [row.assigneeId, ...(await pathUsers(tx, id, projectTeamMembersPath))];"
    ) in repository
    assert "  notify: taskNotify,\n" in repository
    # The repository reads the row before a change, and calls the notices after the change log.
    base = files["src/shared/db/repository.ts"]
    assert "await this.addNotices(tx, id, before[0]);" in base
    assert "await this.addNotices(tx, String(row.id), undefined);" in base
    # The user of the change gets no notice: the actions run as the signed-in user.
    assert 'import { actingUserId } from "./acting-user";' in files["src/shared/db/notices.ts"]
    assert "id !== actorId" in files["src/shared/db/notices.ts"]
    actions = files["src/shared/api/notice-actions.ts"]
    assert "noticesPage(await requireUser(), query)" in actions
    assert "readNotice(await requireUser(), id)" in actions
    assert "readAllNotices(await requireUser())" in actions


def test_a_nextjs_entity_with_the_table_of_the_notices_is_an_error() -> None:
    text = BASE.replace("  Comment:\n", "  Notices:\n", 1).replace(
        "target: Comment, inverse: task", "target: Notices, inverse: task"
    )
    definition = load_definition_text(text, "app.yaml")
    with pytest.raises(GenerationError, match="has the table 'notices', or its module"):
        generate(definition, nextjs.BINDING)


def test_the_react_mock_store_adds_the_notices_after_a_change() -> None:
    files = files_of(BASE, react.BINDING)
    api = files["src/entities/task/api/task-api.ts"]
    assert 'import { addNotices, changed, textValue } from "@/shared/api/notices";' in api
    assert 'pathIds, recordValue } from "@/shared/api";' in api
    assert "taskApi.withNotices((record, before) => {" in api
    assert 'if (changed(record, before, ["assigneeId"])) {' in api
    assert (
        'addNotices("task_assigned", "Task", record.id, [record.assigneeId], {\n'
        "      title: textValue(record.title),\n"
        '      project: textValue(recordValue("Project", record.projectId, "name")),\n'
    ) in api
    path = (
        'pathIds(record, [{ key: "projectId", target: "Project" }, '
        '{ key: "teamId", target: "Team" }, { key: "members", target: "Person" }])'
    )
    assert f'addNotices("task_added", "Task", record.id, {path}, {{' in api
    assert f'addNotices("task_closed", "Task", record.id, [record.assigneeId, ...{path}], {{' in api
    notices = files["src/shared/api/notices.ts"]
    assert "window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(items));" in notices
    assert 'const STORAGE_KEY = "tracker.notices";' in notices
    assert "const actorId = currentUserId();" in notices
    store = files["src/shared/api/mock-store.ts"]
    assert "this.addNotices?.(record, before);" in store
    assert "export function pathIds(record: object, path: readonly PathStep[]): string[] {" in store


def test_the_react_app_with_the_fastapi_app_reads_the_notices_endpoints() -> None:
    text = BASE.replace("title: Tracker }", "title: Tracker, x-react-data: api }", 1)
    files = files_of(text, react.BINDING)
    notices = files["src/shared/api/notices.ts"]
    assert 'apiRequest("GET", `/notices?${params.toString()}`)' in notices
    assert "`/notices/${encodeURIComponent(id)}/read`" in notices
    assert 'await apiRequest("POST", "/notices/read");' in notices
    assert "withNotices" not in files["src/entities/task/api/task-api.ts"]


@BOTH
def test_the_top_bar_shows_the_bell_of_the_notices(binding: Binding) -> None:
    files = example_files(ROOM_BOOKING, binding)
    # The layout of the top bar, and in React the frame of the pages without a layout.
    layouts = [c for p, c in files.items() if "layout" in p and "<SignOutButton />" in c]
    assert len(layouts) == (2 if binding is react.BINDING else 1)
    for layout in layouts:
        assert 'import { NoticeBell } from "@/features/notices";' in layout
        assert re.search(r"<NoticeBell />\n *<SignOutButton />", layout)
    assert "src/shared/ui/popover.tsx" in files
    texts = files["src/features/notices/model/notice-texts.ts"]
    assert (
        '  "booking_cancelled": "The booking {title} is cancelled.", '
        "// @trace notifications.booking_cancelled"
    ) in texts
    assert '  "Booking": ["bookingDetail", "id"],' in texts
    bell = files["src/features/notices/ui/notice-bell.tsx"]
    assert "notices.list({ unread: true, pageSize: 1 })" in bell
    assert "await notices.read(notice.id);" in bell
    assert "await notices.readAll();" in bell


def test_the_detail_page_of_an_entity_is_the_link_of_its_notices() -> None:
    assert notice_links(load_definition(ROOM_BOOKING)) == {"Booking": ("booking_detail", "id")}
    assert notice_links(load_definition_text(BASE, "app.yaml")) == {}


def test_the_react_frame_of_the_pages_without_a_layout_shows_the_bell() -> None:
    files = files_of(BASE, react.BINDING)
    assert re.search(
        r"<NoticeBell />\n *<SignOutButton />", files["src/app/layout/root-layout.tsx"]
    )
    # Without pages, a notice has no link.
    assert (
        "export function noticeHref(_notice: Notice): string | null {\n  return null;"
        in (files["src/features/notices/model/notice-texts.ts"])
    )


@BOTH
def test_the_bell_writes_the_text_in_the_selected_language(binding: Binding) -> None:
    text = ROOM_BOOKING.read_text() + (
        "translations:\n"
        "  default: en\n"
        "  languages:\n"
        "    en: { label: English }\n"
        "    de:\n"
        "      label: Deutsch\n"
        "      text:\n"
        '        "The booking {title} is cancelled.": "Die Buchung {title} ist storniert."\n'
    )
    definition = load_definition_text(text, str(ROOM_BOOKING))
    files = {f.path: f.content for f in generate(definition, binding).files}
    texts = files["src/features/notices/model/notice-texts.ts"]
    assert "return t(text, notice.values);" in texts
    assert 'import { t } from "@/shared/lib/i18n";' in texts
    assert "The booking {title} is cancelled." in app_texts(definition, binding)
    assert "Notices: {count} unread" in app_texts(definition, binding)


@BOTH
def test_the_front_ends_cover_the_notifications(binding: Binding) -> None:
    assert "notification" not in binding.excludes
    assert "notification" in binding.covers
