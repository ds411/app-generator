"""The emails of the notices (ADR 0044): the check, the built-in job of the FastAPI and the
Next.js apps, and the page of the settings of the front ends."""

from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs, react
from appgen.dsl import load_definition_text, validate_definition
from appgen.gen import Binding
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

BASE = dedent(
    """\
    version: 0
    app: { name: tracker, title: Tracker }
    entities:
      Person:
        crud: true
        display_field: name
        fields:
          name: { type: string, required: true }
          email: { type: email, required: true, unique: true }
      Task:
        crud: true
        display_field: title
        fields:
          title: { type: string, required: true }
          status: { type: enum, values: [open, done], default: open }
        relations:
          assignee: { kind: many_to_one, target: Person }
    workflows:
      task_status:
        entity: Task
        field: status
        transitions:
          close: { from: [open], to: done }
    auth:
      user_entity: Person
      username_field: email
      password_reset: {}
      delivery: smtp
    notifications:
      task_assigned:
        entity: Task
        event: changed
        fields: [assignee]
        receivers: [assignee]
        text: The task {title} is yours.
        description: A task gets you as its assignee.
        email: true
      task_closed:
        entity: Task
        transition: close
        receivers: [assignee]
        text: The task {title} is done.
    ui:
      views:
        task_table: { kind: table, entity: Task, columns: { title: { link: task } } }
        task_detail: { kind: detail, entity: Task }
    pages:
      tasks: { path: /tasks, title: Tasks, entity: Task, content: { view: task_table } }
      task: { path: "/tasks/{id}", title: Task, entity: Task, content: { view: task_detail } }
    """
)
WITHOUT_EMAILS = BASE.replace("    email: true\n", "")


def codes(text: str) -> list[tuple[str, str | None]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.element_id) for d in validate_definition(definition)]


def files_of(text: str, binding: Binding) -> dict[str, str]:
    definition = load_definition_text(text, "app.yaml")
    return {f.path: f.content for f in generate(definition, binding).files}


def test_the_emails_of_a_notification_need_the_delivery_smtp() -> None:
    assert codes(BASE) == []
    definition = load_definition_text(BASE, "app.yaml")
    assert definition.notifications["task_assigned"].email is True
    assert definition.notifications["task_closed"].email is False
    text = BASE.replace("  delivery: smtp\n", "")
    assert codes(text) == [("invalid-option", "notifications.task_assigned")]
    assert codes(WITHOUT_EMAILS.replace("  delivery: smtp\n", "")) == []


def test_a_page_cannot_use_the_path_of_the_settings() -> None:
    page = (
        "  settings: { path: /notice-settings, title: Settings, content: { view: task_table } }\n"
    )
    assert codes(BASE + page) == [("duplicate-name", "pages.settings")]
    assert codes(WITHOUT_EMAILS + page) == []


def test_the_fastapi_app_sends_the_emails_with_a_built_in_job() -> None:
    files = files_of(BASE, fastapi.BINDING)
    notifications = files["app/core/notifications.py"]
    assert 'EMAILS = frozenset(\n    {\n        "task_assigned",\n    }\n)\n' in notifications
    assert "class NoticeSetting(Base):" in notifications
    assert "            email=email,\n" in notifications
    notices = files["app/core/notices.py"]
    assert '    "/settings",\n' in notices
    assert '    "/settings/{notification}",\n' in notices
    job = files["app/jobs/notice_emails.py"]
    assert 'SCHEDULE = jobs.Schedule(\n    "* * * * *",\n' in job
    assert "BATCH = 100\n" in job
    assert '    "Task": ("/tasks/{id}", "id"),\n' in job
    assert 'f"{url}/notice-settings"' in job
    assert '"notice_emails": notice_emails.run,' in files["app/worker.py"]
    assert "    front_end_url: str = " in files["app/core/config.py"]
    assert "FRONT_END_URL=http://localhost:5173\n" in files[".env.example"]
    assert "FRONT_END_URL=https://app.example.com\n" in files["deploy/kubernetes/config.env"]
    migration = files["migrations/versions/0001_schema.py"]
    assert '        "notice_settings",\n' in migration
    assert '"ix_notices_email_at"' in migration
    assert "NoticeSetting" in files["app/models.py"]
    test = files["tests/jobs/test_notice_emails.py"]
    assert "async def test_a_user_that_turned_off_the_emails_gets_none(" in test
    assert 'NAME = "task_assigned"\n' in test
    assert (
        "async def test_the_emails_of_each_notification_are_on_until"
        in files["tests/test_notices.py"]
    )
    readme = files["README.md"]
    assert "| `notice_emails` | The schedule `* * * * *` |" in readme
    assert "The notifications `task_assigned` also\n  send each notice by email." in readme


def test_the_fastapi_app_without_emails_has_no_job_and_no_settings() -> None:
    files = files_of(WITHOUT_EMAILS, fastapi.BINDING)
    assert "app/jobs/notice_emails.py" not in files
    assert "NoticeSetting" not in files["app/core/notifications.py"]
    assert "/settings" not in files["app/core/notices.py"]
    assert "FRONT_END_URL" not in files[".env.example"]


def test_the_next_js_app_sends_the_emails_with_a_route_of_the_job() -> None:
    files = files_of(BASE, nextjs.BINDING)
    job = files["src/app/jobs/notice-emails.ts"]
    assert "for (const { notice, to, send } of await waitingEmails(BATCH)) {" in job
    assert "`${url}/notice-settings`" in job
    route = files["app/api/jobs/notice_emails/route.ts"]
    assert 'handleJob(request, "notice_emails", runNoticeEmails)' in route
    schema = files["src/shared/db/schema/notices.ts"]
    assert 'pgTable(\n  "notice_settings",' in schema or '"notice_settings"' in schema
    assert 'index("ix_notices_email_at").on(table.email, table.at)' in schema
    db = files["src/shared/db/notices.ts"]
    assert "export async function waitingEmails(limit: number)" in db
    assert "export async function setNoticeEmail(" in db
    actions = files["src/shared/api/notice-actions.ts"]
    assert "export async function setNoticeEmailAction(" in actions
    assert "export async function sendEmail(" in files["src/shared/auth/mail.ts"]
    assert 'requirePageUser("/notice-settings")' in files["app/notice-settings/page.tsx"]
    assert 'href="/notice-settings"' in files["src/features/notices/ui/notice-bell.tsx"]
    assert "for job in notice_emails; do" in files["compose.yaml"]


def test_the_react_app_keeps_the_choices_in_the_browser_tab() -> None:
    files = files_of(BASE, react.BINDING)
    page = files["src/features/notices/ui/notice-settings-page.tsx"]
    label = '"task_assigned": { label: "Task assigned", description: "A task gets you as its'
    assert label in page
    assert "<Switch" in page
    assert 'path: "/notice-settings"' in files["src/app/router.tsx"]
    notices = files["src/shared/api/notices.ts"]
    assert "SETTINGS_KEY" in notices
    assert "src/features/notices/ui/notice-settings-page.tsx" not in files_of(
        WITHOUT_EMAILS, react.BINDING
    )


@pytest.mark.parametrize("binding", [fastapi.BINDING, nextjs.BINDING])
def test_the_name_of_the_job_is_taken(binding: Binding) -> None:
    job = BASE + 'jobs:\n  notice_emails: { schedule: "@daily" }\n'
    with pytest.raises(GenerationError, match="built-in job of the emails"):
        files_of(job, binding)
